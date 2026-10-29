"""Same-SQL regroup / BM25 / crossencoder comparison; saved contexts before gold loading."""

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean
from time import perf_counter

from ..answering import generate_answer
from ..chunk import config_id
from ..config import ROOT
from ..context import EvidenceStore
from ..evaluation import score
from ..files import atomic_json, digest, read_jsonl
from ..models import Hit, Question
from ..planned_retrieval import PlannedRetriever, prepare_searches, rank_records
from ..planning import Plan
from ..rerank_context import candidates_for_rerank, fetch_blocks, select_reranked
from ..reranking import grade_candidates
from ..serving.regroup import regroup
from ..serving.runtime import TracedModel, load_config, resources, select_context, shared_budget
from ..tracing import Trace

SOURCE = ROOT / "reports/planner/20261027T034153Z_198f65"
OLD = ROOT / "reports/rerank/20261027T170703Z_9a25db"


def bm25_records(plan, retriever, cfg, trace):
    jobs = prepare_searches(plan, retriever.catalog, cfg)
    dense_queries = list(dict.fromkeys(j["query"] for j in jobs))
    vectors = dict(
        zip(dense_queries, retriever.embedder.embed(dense_queries, input_type="query"), strict=True)
    )
    seen = {}
    tasks = {t.id: t for t in plan.tasks}
    records = []
    for job in jobs:
        key = (job["task_id"], tuple(job["group"]))
        seen[key] = seen.get(key, 0) + 1
        lexical = job["variants"] >= 2 and seen[key] == 2
        query = " ".join(tasks[job["task_id"]].keywords) if lexical else job["query"]
        found = retriever.repository.search(
            retriever.index_id,
            job["documents"],
            str(plan.as_of),
            job["k"],
            vector=None if lexical else vectors[query],
            query=query if lexical else None,
        )
        records.append(
            {
                **job,
                "method": "fts" if lexical else "dense",
                "query": query,
                "variants": 1,
                "hits": [h.model_dump() for h in found],
            }
        )
    return records


def run(run_dir, ids):
    cfg = load_config().model_copy(update={"vector_search": "exact", "reranker": "crossencoder"})
    with resources(cfg) as (store, llm, emb, ce):
        catalog = store.catalog()
        retriever = PlannedRetriever(store, emb, catalog, store.index_config, cfg.pipeline)
        for path in sorted((SOURCE / "traces").glob("U*.json")):
            if ids and path.stem not in ids:
                continue
            old = json.loads(path.read_text())
            original = Plan(**old["plan"])
            log = Trace(path.stem, old["inputs"])
            model = TracedModel(llm, log)
            saved_plan = run_dir / "plans" / path.name
            if saved_plan.exists():
                new = Plan(**json.loads(saved_plan.read_text())["plan"])
            else:
                new, event = regroup(
                    original, catalog, cfg.pipeline, model, ROOT / "data/cache/regroup"
                )
                atomic_json(
                    saved_plan,
                    {
                        "plan": new.model_dump(mode="json"),
                        "event": event,
                        "stages": log.data["stages"],
                    },
                )
            arms = {"wide_dense": original, "regroup_dense": new, "wide_hybrid": original}
            for arm, plan in arms.items():
                out = run_dir / arm / path.name
                if out.exists():
                    continue
                trace = Trace(path.stem, old["inputs"])
                model = TracedModel(llm, trace)
                started = perf_counter()
                # Identical base candidates for the original dense arm; no paid or SQL replay.
                if arm == "wide_dense":
                    records = old["search_records"]
                elif arm == "wide_hybrid":
                    records = bm25_records(plan, retriever, cfg.pipeline, trace)
                else:
                    records = retriever.search(plan, cfg.pipeline, trace)
                fusion_cfg = (
                    cfg.pipeline.model_copy(update={"dense_weight": 1.0, "fts_weight": 1.0})
                    if arm == "wide_hybrid"
                    else cfg.pipeline
                )
                ranked, _ = rank_records(records, fusion_cfg)
                ranked = ranked[: cfg.pipeline.max_unique_candidates]
                shortlist = ranked[:80]
                cap = json.loads((OLD / "baseline" / path.name).read_text())
                cfg_arm = cfg.model_copy(
                    update={
                        "evidence_tokens": cap["evidence_tokens"],
                        "full_prompt_tokens": cap["full_prompt_proxy_tokens"],
                    }
                )
                data = {
                    "query_id": path.stem,
                    "inputs": old["inputs"],
                    "plan": original.model_dump(mode="json"),
                }
                store_evidence = EvidenceStore(store)
                # Use original immutable need/answer plan in both rankers for fair prompt cost.
                selected, _texts, evidence, meta = select_context(
                    data, original, ranked, store_evidence, catalog, cfg_arm, model, ce, trace
                )
                contexts = {
                    "crossencoder": {
                        "selected_hits": [h.model_dump() for h in selected],
                        "runtime_evidence": evidence,
                        "metadata": meta,
                    }
                }
                if arm == "wide_dense":
                    control = json.loads((OLD / "rerank80_full" / path.name).read_text())
                    contexts["llm"] = {
                        "selected_hits": control["selected_hits"],
                        "runtime_evidence": control["runtime_evidence"],
                        "metadata": control["metadata"],
                        "basis": "historical same original Top80 grading",
                    }
                else:
                    grades = json.loads((OLD / "grades" / path.name).read_text())["grades"]
                    blocks = fetch_blocks(shortlist, store_evidence)
                    missing = [h for h in shortlist if h.chunk.id not in grades]
                    candidates = candidates_for_rerank(missing, blocks, catalog.by_id)
                    logs = run_dir / "batches" / arm / path.stem
                    logs.mkdir(parents=True, exist_ok=True)
                    fresh, event = grade_candidates(
                        old["inputs"],
                        original.model_dump(mode="json"),
                        candidates,
                        model,
                        ROOT / "data/cache/rerank",
                        logs,
                    )
                    grades.update(fresh)
                    selected, _texts, evidence, meta = select_reranked(
                        shortlist,
                        grades,
                        blocks,
                        store_evidence,
                        catalog.by_id,
                        cfg.pipeline,
                        data,
                        cap["evidence_tokens"],
                        cap["full_prompt_proxy_tokens"],
                    )
                    contexts["llm"] = {
                        "selected_hits": [h.model_dump() for h in selected],
                        "runtime_evidence": evidence,
                        "metadata": meta,
                        "new_grades": len(missing),
                        "grading_events": event,
                    }
                atomic_json(
                    out,
                    {
                        "query_id": path.stem,
                        "arm": arm,
                        "inputs": old["inputs"],
                        "plan": plan.model_dump(mode="json"),
                        "answer_plan": original.model_dump(mode="json"),
                        "config": cfg_arm.model_dump(),
                        "index_id": config_id(store.index_config),
                        "search_records": records,
                        "sql_job_count": len(records),
                        "base_sql_job_count": len(old["search_records"]),
                        "candidate_hits": list(
                            {h["chunk"]["id"]: h for r in records for h in r["hits"]}.values()
                        ),
                        "shortlist": [h.model_dump() for h in shortlist],
                        "contexts": contexts,
                        "stages": trace.data["stages"],
                        "elapsed_seconds": perf_counter() - started,
                    },
                )
                print(
                    path.stem, arm, len(records), "SQL jobs", len(ranked), "candidates", flush=True
                )
        atomic_json(run_dir / "budget.json", shared_budget(cfg).snapshot())


def evaluate(run_dir):
    # ONLY after context artifacts exist do we open evaluation labels.
    gold = {
        r["id"]: Question(**r) for r in read_jsonl(ROOT / "data/evaluation/golden_v2/golden.jsonl")
    }
    per = []
    for arm in ("wide_dense", "regroup_dense", "wide_hybrid"):
        for path in sorted((run_dir / arm).glob("U*.json")):
            data = json.loads(path.read_text())
            for ranker, context in data["contexts"].items():
                scores = {
                    stage: score(gold[path.stem], [Hit(**h) for h in raw])
                    for stage, raw in {
                        "candidate": data["candidate_hits"],
                        "ranked_candidate": data["shortlist"],
                        "final_context": context["selected_hits"],
                    }.items()
                }
                per.append(
                    {
                        "id": path.stem,
                        "arm": arm,
                        "ranker": ranker,
                        "scores": scores,
                        "sql_jobs": data["sql_job_count"],
                        "base_sql_jobs": data["base_sql_job_count"],
                    }
                )
    metrics = []
    for arm in ("wide_dense", "regroup_dense", "wide_hybrid"):
        for ranker in ("llm", "crossencoder"):
            rows = [r for r in per if (r["arm"], r["ranker"]) == (arm, ranker)]
            if not rows:
                continue
            metrics.append(
                {
                    "arm": arm,
                    "ranker": ranker,
                    "n": len(rows),
                    **{
                        stage: mean(r["scores"][stage]["recall"] for r in rows)
                        for stage in ("candidate", "ranked_candidate", "final_context")
                    },
                    "groups_found": sum(r["scores"]["final_context"]["groups_found"] for r in rows),
                    "complete": sum(r["scores"]["final_context"]["complete"] for r in rows),
                    "sql_jobs": sum(r["sql_jobs"] for r in rows),
                    "base_sql_jobs": sum(r["base_sql_jobs"] for r in rows),
                }
            )
    result = {
        "metrics": metrics,
        "per_question": per,
        "scope": "20 development queries, no holdout; "
        "same per-question SQL upper bound/k/index/context caps. Hybrid replaces the second dense "
        "variant with BM25, not extra calls. LLM mixes validated historical judgments and new "
        "Top80 judgments; CrossEncoder fresh on each shortlist. Not answer accuracy.",
    }
    atomic_json(run_dir / "evaluation.json", result)
    print(json.dumps(metrics, indent=2))


def generate(run_dir, ids):
    cfg = load_config()
    with resources(cfg) as (_store, llm, _emb, _ce):
        for arm in ("regroup_dense", "wide_hybrid"):
            for qid in ids:
                path = run_dir / arm / f"{qid}.json"
                if not path.exists():
                    continue
                saved = json.loads(path.read_text())
                for ranker in ("llm", "crossencoder"):
                    out = run_dir / "answers" / arm / ranker / f"{qid}.json"
                    if out.exists():
                        continue
                    trace = Trace(qid, saved["inputs"])
                    data = trace.data
                    data.update(
                        plan=saved["answer_plan"],
                        runtime_evidence=saved["contexts"][ranker]["runtime_evidence"],
                    )
                    try:
                        answer = generate_answer(data, TracedModel(llm, trace))
                        atomic_json(out, {**data, "generation": answer, "status": "generated"})
                    except Exception as exc:
                        from ..serving.runtime import safe_failure

                        atomic_json(out, {**data, "status": "error", "error": safe_failure(exc)})
                        raise
                    print(qid, arm, ranker, "generated", flush=True)
        atomic_json(run_dir / "budget.json", shared_budget(cfg).snapshot())


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=["run", "evaluate", "generate"])
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--ids", default="")
    args = p.parse_args()
    ids = set(filter(None, args.ids.split(",")))
    args.run.mkdir(parents=True, exist_ok=True)
    if args.command == "evaluate":
        evaluate(args.run)
    elif args.command == "generate":
        generate(args.run, sorted(ids))
    else:
        manifest = args.run / "manifest.json"
        if not manifest.exists():
            atomic_json(
                manifest,
                {
                    "created_at": datetime.now(UTC).isoformat(),
                    "source": str(SOURCE),
                    "source_hashes": {
                        p.name: digest(p.read_bytes()) for p in (SOURCE / "traces").glob("U*.json")
                    },
                    "code_hashes": {
                        str(p.relative_to(ROOT)): digest(p.read_bytes())
                        for p in (ROOT / "src/finrag").rglob("*.py")
                    },
                    "budget_before": shared_budget(load_config()).snapshot(),
                },
            )
        run(args.run, ids)


if __name__ == "__main__":
    main()
