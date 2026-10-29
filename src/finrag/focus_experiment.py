"""Controlled wide/focused/mixed query experiment on the existing PG index."""

import argparse
import json
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter
from uuid import uuid4

from dotenv import dotenv_values

from .baseline import safe_error
from .coarse_experiment import LocalSources, protected
from .config import ROOT, settings
from .deadlines import DeadlineLLM
from .files import atomic_json, digest, read_jsonl
from .focused_query import VERSION, refine, search_signature, variants
from .generation import Budget, BudgetedVoyage, DeepSeek
from .models import Filing, Hit, IndexConfig
from .planned_retrieval import PlannedRetriever, prepare_searches, rank_records
from .planning import Catalog, PipelineConfig, Plan, Request, validate_plan
from .repository import Repository
from .rerank_context import candidates_for_rerank, select_reranked
from .reranking import grade_candidates
from .tracing import Trace

ARMS = ("wide", "focused", "mixed")
SOURCE = ROOT / "reports/planner/20261027T034153Z_198f65"
RERANK = ROOT / "reports/rerank/20261027T170703Z_9a25db"


def budget():
    return Budget(ROOT / "data/cache/baseline/budget.jsonl", stop_usd="1.60")


@contextmanager
def online(config):
    s = settings()
    key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("deepseek_key_missing")
    shared = budget()
    repo = Repository(s.database_url.get_secret_value())
    repo.connection.execute("SET default_transaction_read_only=on")
    repo.connection.execute("SET statement_timeout='15s'")
    embedder = BudgetedVoyage(s.voyage_api_key.get_secret_value(), ROOT / "data/cache/embeddings",
                             model=s.voyage_model, dimension=s.embedding_dimension, shared_budget=shared)
    llm = DeepSeek(key, shared)
    try:
        catalog = Catalog.load(ROOT)
        ix = next(IndexConfig(**r) for r in read_jsonl_config() if r["name"] == config.index_name)
        retriever = PlannedRetriever(repo, embedder, catalog, ix, config)
        yield retriever, DeadlineLLM(llm), shared
    finally:
        llm.close()
        embedder.close()
        repo.close()


def read_jsonl_config():
    return json.loads((ROOT / "configs/indexes.json").read_text())


def canonical_hits(arms):
    """Keep the wide hit's original distance for byte-identical control replay."""
    hits = {}
    for arm in ARMS:
        for raw in arms[arm]["candidate_hits"]:
            hits.setdefault(raw["chunk"]["id"], Hit(**raw))
    return hits


def fingerprint(retriever):
    return retriever.repository.connection.execute(
        "SELECT count(*) n, md5(string_agg(md5(payload::text || embedding::text),"
        "'|' ORDER BY id)) fingerprint FROM finrag.chunks WHERE index_id=%s",
        (retriever.index_id,),
    ).fetchone()


def protection():
    values = protected(SOURCE, RERANK)
    values.pop("data/cache/baseline/budget.jsonl", None)
    return values


def check_run(run):
    manifest = json.loads((run / "manifest.json").read_text())
    if manifest["version"] != VERSION or manifest["protected_files"] != protection():
        raise ValueError("experiment_inputs_changed")
    if any(digest((ROOT / "src/finrag" / p).read_bytes()) != h
           for p, h in manifest["code_sha256"].items()):
        raise ValueError("experiment_code_changed_create_new_run")
    return manifest


def retrieve(run, ids):
    check_run(run)
    config = PipelineConfig(**json.loads((ROOT / "configs/pipeline_dev_selected.json").read_text()))
    paths = [p for p in sorted((SOURCE / "traces").glob("U*.json")) if not ids or p.stem in ids]
    if ids - {p.stem for p in paths}:
        raise ValueError("unknown_query_ids")
    with online(config) as (retriever, llm, shared):
        before = fingerprint(retriever)
        snapshot = run / "index_snapshot.json"
        if snapshot.exists() and json.loads(snapshot.read_text()) != before:
            raise ValueError("index_changed_since_prior_stage")
        atomic_json(snapshot, before)
        for path in paths:
            old = json.loads(path.read_text())
            original = Plan(**old["plan"])
            request = Request(question=old["inputs"]["original_question"],
                              reading_context=old["inputs"]["reading_context"],
                              confirmed_context=old["inputs"]["confirmed_context"],
                              as_of=old["inputs"]["as_of"])
            log = run / "refinements" / path.name
            focused, event = refine(old["inputs"], original, llm, ROOT / "data/cache/focused_queries", log)
            for arm, plan in variants(original, focused).items():
                target = run / "retrieval" / arm / path.name
                if target.exists():
                    saved = json.loads(target.read_text())
                    if saved["plan"] != plan.model_dump(mode="json"):
                        raise ValueError("saved_arm_plan_changed")
                    print(path.stem, arm, "reused", flush=True)
                    continue
                validate_plan(plan, request, retriever.catalog, config)
                jobs = prepare_searches(plan, retriever.catalog, config)
                if search_signature(jobs) != search_signature(prepare_searches(original, retriever.catalog, config)):
                    raise ValueError("search_scope_or_budget_changed")
                trace = Trace(path.stem, old["inputs"])
                start = perf_counter()
                records = old["search_records"] if arm == "wide" else retriever.search(plan, config, trace)
                ranked, _ = rank_records(records, config)
                raw = {h["chunk"]["id"]: h for r in records for h in r["hits"]}
                ranked = ranked[:config.max_unique_candidates]
                short = ranked[:80]
                if arm == "wide" and [h.chunk.id for h in short] != [h["chunk"]["id"] for h in old["retrieval"]["ranked_hits"][:80]]:
                    raise ValueError("wide_shortlist_replay_changed")
                atomic_json(target, {
                    "query_id": path.stem, "arm": arm, "inputs": old["inputs"],
                    "plan": plan.model_dump(mode="json"), "config": config.model_dump(),
                    "source_trace_sha256": digest(path.read_bytes()), "refinement_event": event,
                    "search_records": records, "candidate_hits": list(raw.values()),
                    "shortlist_ids": [h.chunk.id for h in short], "stages": trace.data["stages"],
                    "search_job_count": len(jobs), "elapsed_seconds": perf_counter()-start,
                    "scope_and_job_budget_equal": True, "index_id": retriever.index_id,
                })
                print(path.stem, arm, len(raw), "candidates", len(short), "shortlist", flush=True)
        if before != fingerprint(retriever):
            raise ValueError("index_changed_during_readonly_retrieval")
        atomic_json(run / "budget_after_retrieval.json", shared.snapshot())


def rerank(run):
    manifest = check_run(run)
    for arm in ARMS:
        if len(list((run / "retrieval" / arm).glob("U*.json"))) != 20:
            raise ValueError("complete_all_twenty_shortlists_before_reranking")
    filings = {r["id"]: Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl")}
    store = LocalSources(filings)
    key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("deepseek_key_missing")
    raw_llm = DeepSeek(key, budget())
    llm = DeadlineLLM(raw_llm)
    try:
        for path in sorted((SOURCE / "traces").glob("U*.json")):
            targets = [run / "contexts" / arm / path.name for arm in ARMS]
            if all(p.exists() for p in targets):
                print(path.stem, "contexts reused", flush=True)
                continue
            original = json.loads(path.read_text())
            data = {"inputs": original["inputs"], "plan": original["plan"]}
            grades = json.loads((RERANK / "grades" / path.name).read_text())["grades"]
            old_inputs = json.loads((RERANK / "inputs" / path.name).read_text())
            if old_inputs["source_trace_sha256"] != digest(path.read_bytes()):
                raise ValueError("old_grading_source_changed")
            arm_data = {a: json.loads((run / "retrieval" / a / path.name).read_text()) for a in ARMS}
            hits = canonical_hits(arm_data)
            needed_ids = list(dict.fromkeys(c for a in ARMS for c in arm_data[a]["shortlist_ids"]))
            # Verify reused grades against actual source text; never infer a grade for new chunks.
            old_candidates = {c["chunk_id"]: c for c in old_inputs["candidates"]}
            from .reranking import source_lines

            for cid in needed_ids:
                if cid in grades and [s["text"] for s in source_lines(hits[cid], store.data)] != old_candidates[cid]["lines"]:
                    raise ValueError("reused_grade_source_text_changed")
            missing = [hits[c] for c in needed_ids if c not in grades]
            candidates = candidates_for_rerank(missing, store.data, filings)
            atomic_json(run / "new_grade_inputs" / path.name,
                        {**data, "candidates": candidates, "reused_old_grades": len(needed_ids)-len(missing)})
            fresh, events = grade_candidates(data["inputs"], data["plan"], candidates, llm,
                                             ROOT / "data/cache/rerank", run / "batches" / path.stem)
            grades.update(fresh)
            atomic_json(run / "grades" / path.name, {"grades": grades, "new_events": events,
                                                    "new_candidates": len(missing)})
            cap = json.loads((RERANK / "baseline" / path.name).read_text())
            for arm in ARMS:
                config = PipelineConfig(**arm_data[arm]["config"])
                pool = [hits[c] for c in arm_data[arm]["shortlist_ids"]]
                selected, texts, evidence, meta = select_reranked(
                    pool, grades, store.data, store, filings, config, data,
                    cap["evidence_tokens"], cap["full_prompt_proxy_tokens"], compact=False, balanced=False)
                if arm == "wide":
                    expected = json.loads((RERANK / "rerank80_full" / path.name).read_text())
                    if [h.model_dump(mode="json") for h in selected] != expected["selected_hits"] or texts != expected["texts"]:
                        raise ValueError("wide_context_replay_changed")
                atomic_json(run / "contexts" / arm / path.name, {
                    **data, "query_id": path.stem, "arm": arm,
                    "selected_hits": [h.model_dump(mode="json") for h in selected],
                    "texts": texts, "runtime_evidence": evidence, "metadata": meta,
                    "llm_relevance_proxy_ge3": mean(grades[h.chunk.id]["s"]>=3 for h in pool),
                    "generation": "not_run", "grading_basis": "old same-input grades plus new top80-only candidates",
                })
            print(path.stem, len(missing), "new grades", "three contexts saved", flush=True)
    finally:
        raw_llm.close()
        atomic_json(run / "budget_after_rerank.json", budget().snapshot())
    if manifest["protected_files"] != protection():
        raise ValueError("protected_file_changed")


def evaluate(run):
    check_run(run)
    for arm in ARMS:
        if len(list((run / "retrieval" / arm).glob("U*.json"))) != 20:
            raise ValueError("complete_all_twenty_retrievals_before_scoring")
    # Offline scoring only. No labels flow back into refiner, retrieval or reranker.
    from .evaluation import score
    from .models import Question

    gold = {r["id"]: Question(**r) for r in read_jsonl(ROOT / "data/evaluation/golden_v2/golden.jsonl")}
    rows = []
    for arm in ARMS:
        for path in sorted((run / "retrieval" / arm).glob("U*.json")):
            r = json.loads(path.read_text())
            hits = {h["chunk"]["id"]: Hit(**h) for h in r["candidate_hits"]}
            row = {"query_id": path.stem, "arm": arm,
                   "candidate": score(gold[path.stem], list(hits.values())),
                   "shortlist": score(gold[path.stem], [hits[c] for c in r["shortlist_ids"]]),
                   "candidate_count": len(hits), "search_jobs": r["search_job_count"]}
            ctx = run / "contexts" / arm / path.name
            if ctx.exists():
                d = json.loads(ctx.read_text())
                row.update(context=score(gold[path.stem], [Hit(**h) for h in d["selected_hits"]]),
                           evidence_tokens=d["metadata"]["evidence_tokens"],
                           prompt_tokens=d["metadata"]["full_prompt_proxy_tokens"],
                           llm_relevance_proxy_ge3=d["llm_relevance_proxy_ge3"])
            rows.append(row)
    baseline = {r["query_id"]: r for r in rows if r["arm"] == "wide"}
    summaries = []
    for arm in ARMS:
        rs = [r for r in rows if r["arm"] == arm]
        summary = {"arm": arm, "n": len(rs), "mean_candidate_count": mean(r["candidate_count"] for r in rs)}
        for stage in ["candidate", "shortlist", "context"]:
            if not all(stage in r for r in rs):
                continue
            summary[stage] = {
                "macro_recall": mean(r[stage]["recall"] for r in rs),
                "micro_found": sum(r[stage]["groups_found"] for r in rs),
                "complete": sum(r[stage]["complete"] for r in rs),
                "improved": [r["query_id"] for r in rs if r[stage]["recall"] > baseline[r["query_id"]][stage]["recall"]],
                "regressed": [r["query_id"] for r in rs if r[stage]["recall"] < baseline[r["query_id"]][stage]["recall"]],
            }
        summaries.append(summary)
    result = {"scope": "20 dev; unchanged index/scope/search budgets/Top80; no answer generation",
              "summary": summaries, "per_question": rows, "budget_now": budget().snapshot()}
    atomic_json(run / "results.json", result)
    print(json.dumps({"run": str(run), "summary": summaries}, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["retrieve", "rerank", "evaluate"])
    parser.add_argument("--run", type=Path)
    parser.add_argument("--ids", default="")
    args = parser.parse_args()
    run = args.run.resolve() if args.run else ROOT / "reports/focused_queries" / (
        datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
    if not args.run:
        if args.command != "retrieve":
            raise ValueError("explicit_run_required")
        run.mkdir(parents=True)
        atomic_json(run / "manifest.json", {
            "version": VERSION, "arms": ARMS, "stop_usd": "1.60", "budget_before": budget().snapshot(),
            "source": str(SOURCE.relative_to(ROOT)), "rerank": str(RERANK.relative_to(ROOT)),
            "protected_files": protection(), "default_changed": False,
            "code_sha256": {p.name: digest(p.read_bytes()) for p in (ROOT / "src/finrag").glob("*.py")},
        })
    print("RUN_DIR=" + str(run), flush=True)
    try:
        if args.command == "retrieve":
            retrieve(run, set(filter(None, args.ids.split(","))))
        elif args.command == "rerank":
            rerank(run)
        else:
            evaluate(run)
    except Exception as exc:  # noqa: BLE001 — CLI boundary persists safe typed errors, never headers/DSN
        atomic_json(run / (args.command + "_error.json"), safe_error(exc))
        print("FAILED " + type(exc).__name__, flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
