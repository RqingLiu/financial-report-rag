"""Offline Top80 shortlist/reused-rerank screening. No DB or API clients."""

import argparse
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from uuid import uuid4

from .chunk import token_count
from .coarse_ranking import VARIANTS, shortlist
from .config import ROOT
from .files import atomic_json, digest, read_jsonl
from .models import Block, Filing, Hit
from .planning import PipelineConfig
from .rerank_context import select_reranked
from .reranking import source_lines


class LocalSources:
    def __init__(self, document_ids):
        self.data, self.hashes = {}, {}
        for doc in sorted(document_ids):
            path = ROOT / "data/processed" / f"{doc}.blocks.jsonl"
            self.hashes[str(path.relative_to(ROOT))] = digest(path.read_bytes())
            for row in read_jsonl(path):
                row.pop("structured", None)
                block = Block(**row)
                self.data[block.id] = block

    def blocks(self, ids):
        return {bid: self.data[bid] for bid in ids}


def protected(source, rerank):
    paths = [*source.rglob("*"), *rerank.rglob("*"),
             *(ROOT / "data/evaluation").rglob("*"), *(ROOT / "configs").glob("*.json"),
             ROOT / "data/sources.jsonl", ROOT / "data/cache/baseline/budget.jsonl",
             ROOT / "reports/test_release.json"]
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths if p.is_file()}


def select_shortlists(source, run):
    for path in sorted((source / "traces").glob("U*.json")):
        raw = json.loads(path.read_text())
        current = [h["chunk"]["id"] for h in raw["retrieval"]["ranked_hits"]]
        for variant in VARIANTS:
            start = perf_counter()
            ids, details = shortlist(raw["search_records"], raw["plan"]["tasks"], current, variant)
            atomic_json(run / variant / "shortlists" / path.name, {
                "query_id": path.stem, "chunk_ids": ids, "details": details,
                "cpu_seconds": perf_counter() - start,
                "source_trace_sha256": digest(path.read_bytes()),
                "selector_inputs": "runtime search records, plan tasks and original ranking only",
            })
        print(path.stem, "eight shortlists saved", flush=True)


def replay_contexts(source, rerank, run, filings, store):
    validations = []
    for path in sorted((source / "traces").glob("U*.json")):
        raw = json.loads(path.read_text())
        data = {"inputs": raw["inputs"], "plan": raw["plan"]}
        hits = {h["chunk"]["id"]: Hit(**h) for h in raw["retrieval"]["candidate_hits"]}
        config = PipelineConfig(**raw["config"])
        # Old grades enter only AFTER all shortlist variants were written.
        grade_data = json.loads((rerank / "grades" / path.name).read_text())
        grades = grade_data["grades"]
        old_inputs = json.loads((rerank / "inputs" / path.name).read_text())
        if old_inputs["source_trace_sha256"] != digest(path.read_bytes()):
            raise ValueError("rerank_source_changed")
        if set(grades) != set(hits):
            raise ValueError("candidate_grade_set_changed")
        candidate_texts = {}
        for candidate in old_inputs["candidates"]:
            actual = [s["text"] for s in source_lines(hits[candidate["chunk_id"]], store.data)]
            if actual != candidate["lines"]:
                raise ValueError("local_source_differs_from_graded_text")
            candidate_texts[candidate["chunk_id"]] = "".join(actual)
        baseline = json.loads((rerank / "baseline" / path.name).read_text())
        evidence_cap = baseline["evidence_tokens"]
        prompt_cap = baseline["full_prompt_proxy_tokens"]
        for variant in VARIANTS:
            shortlist_data = json.loads((run / variant / "shortlists" / path.name).read_text())
            ids = shortlist_data["chunk_ids"]
            if len(ids) > 80 or len(ids) != len(set(ids)) or set(ids) - hits.keys():
                raise ValueError("shortlist_scope_violation")
            if any(str(filings[hits[c].chunk.document_id].filed_at) > data["inputs"]["as_of"]
                   for c in ids):
                raise ValueError("late_document")
            selected, texts, evidence, meta = select_reranked(
                [hits[c] for c in ids], grades, store.data, store, filings, config, data,
                evidence_cap, prompt_cap, compact=False, balanced=False,
            )
            if variant == "current":
                expected = json.loads((rerank / "rerank80_full" / path.name).read_text())
                if ([h.model_dump(mode="json") for h in selected] != expected["selected_hits"]
                        or texts != expected["texts"]):
                    raise ValueError("original_top80_context_replay_changed")
            atomic_json(run / variant / "contexts" / path.name, {
                **data, "query_id": path.stem,
                "selected_hits": [h.model_dump(mode="json") for h in selected],
                "texts": texts, "runtime_evidence": evidence, "metadata": meta,
                "llm_relevance_proxy_ge3": mean(grades[c]["s"] >= 3 for c in ids) if ids else 0,
                "shortlist_source_proxy_tokens": sum(token_count(candidate_texts[c]) for c in ids),
                "new_api_calls": 0, "generation": "not_run",
            })
            validations.append({"query_id": path.stem, "variant": variant,
                                "shortlist_count": len(ids), "context_count": len(selected),
                                "evidence_cap_ok": meta["evidence_tokens"] <= evidence_cap,
                                "prompt_cap_ok": meta["full_prompt_proxy_tokens"] <= prompt_cap})
        print(path.stem, "reused-grade contexts saved", flush=True)
    return validations


def dataset_profile():
    profiles = {}
    for version, path in [("v1", ROOT / "data/evaluation/golden_v1.jsonl"),
                          ("v2", ROOT / "data/evaluation/golden_v2/golden.jsonl")]:
        rows = read_jsonl(path)
        answerable = [r for r in rows if r.get("outcome", "answer") == "answer"]
        counts = [len(r["evidence_groups"]) for r in answerable]
        profiles[version] = {
            "questions": len(rows), "splits": dict(Counter(r["split"] for r in rows)),
            "answerable": len(answerable), "groups": sum(counts),
            "mean_groups": mean(counts), "median_groups": median(counts),
            "group_range": [min(counts), max(counts)],
            "mean_documents": mean(len(r["documents"]) for r in answerable),
            "categories": dict(Counter(r["category"] for r in rows)),
            "usage": "annotation profile only; old test not used for strategy selection",
        }
    return profiles


def evaluate(source, run):
    # All shortlists and contexts already exist before any gold is deserialized here.
    from .evaluation import covers, score
    from .models import Question

    gold = {r["id"]: Question(**r) for r in read_jsonl(
        ROOT / "data/evaluation/golden_v2/golden.jsonl")}
    rows, candidate_misses = [], []
    for path in sorted((source / "traces").glob("U*.json")):
        trace = json.loads(path.read_text())
        hits = [Hit(**h) for h in trace["retrieval"]["candidate_hits"]]
        blocks = {bid for h in hits for bid in h.chunk.block_ids}
        for i, group in enumerate(gold[path.stem].evidence_groups):
            if not any(covers(e, hits) for e in group):
                candidate_misses.append({
                    "query_id": path.stem, "group": i,
                    "reason": "same_block_incomplete_span" if any(e.block_id in blocks for e in group)
                    else "source_block_not_retrieved",
                    "block_ids": [e.block_id for e in group],
                })
    for variant in VARIANTS:
        for path in sorted((run / variant / "shortlists").glob("U*.json")):
            selected = json.loads(path.read_text())
            old = json.loads((source / "traces" / path.name).read_text())
            hits = {h["chunk"]["id"]: Hit(**h) for h in old["retrieval"]["candidate_hits"]}
            context = json.loads((run / variant / "contexts" / path.name).read_text())
            rows.append({"query_id": path.stem, "variant": variant,
                         "shortlist": score(gold[path.stem], [hits[c] for c in selected["chunk_ids"]]),
                         "context": score(gold[path.stem], [Hit(**h) for h in context["selected_hits"]]),
                         "count": len(selected["chunk_ids"]),
                         "cpu_seconds": selected["cpu_seconds"],
                         "llm_relevance_proxy_ge3": context["llm_relevance_proxy_ge3"],
                         "shortlist_source_proxy_tokens": context["shortlist_source_proxy_tokens"],
                         "evidence_tokens": context["metadata"]["evidence_tokens"],
                         "prompt_tokens": context["metadata"]["full_prompt_proxy_tokens"]})
    base = {r["query_id"]: r for r in rows if r["variant"] == "current"}
    summaries = []
    for variant in VARIANTS:
        values = [r for r in rows if r["variant"] == variant]
        result = {"variant": variant, "n": len(values)}
        for stage in ["shortlist", "context"]:
            result[stage] = {
                "macro_recall": mean(r[stage]["recall"] for r in values),
                "micro_found": sum(r[stage]["groups_found"] for r in values),
                "complete": sum(r[stage]["complete"] for r in values),
                "improved": sum(r[stage]["recall"] > base[r["query_id"]][stage]["recall"] for r in values),
                "same": sum(r[stage]["recall"] == base[r["query_id"]][stage]["recall"] for r in values),
                "regressed": [r["query_id"] for r in values
                              if r[stage]["recall"] < base[r["query_id"]][stage]["recall"]],
            }
        for key in ["count", "cpu_seconds", "llm_relevance_proxy_ge3", "evidence_tokens", "prompt_tokens",
                    "shortlist_source_proxy_tokens"]:
            result["mean_" + key] = mean(r[key] for r in values)
        summaries.append(result)
    result = {"summary": summaries, "per_question": rows,
              "candidate_misses": candidate_misses,
              "candidate_miss_counts": dict(Counter(m["reason"] for m in candidate_misses)),
              "dataset_profile": dataset_profile(), "new_api_calls": 0,
              "scope": "20 dev, fixed raw pool and Top80; cached-grade context replay, not fresh rerank or human precision"}
    atomic_json(run / "results.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=ROOT / "reports/planner/20261027T034153Z_198f65")
    parser.add_argument("--rerank", type=Path, default=ROOT / "reports/rerank/20261027T170703Z_9a25db")
    args = parser.parse_args()
    source, rerank = args.source.resolve(), args.rerank.resolve()
    before = protected(source, rerank)
    run = ROOT / "reports/coarse_rank" / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
    run.mkdir(parents=True)
    atomic_json(run / "manifest.json", {
        "source": str(source.relative_to(ROOT)), "rerank": str(rerank.relative_to(ROOT)),
        "variants_predeclared": VARIANTS, "limit": 80, "protected_files": before,
        "code_sha256": {p.name: digest(p.read_bytes()) for p in (ROOT / "src/finrag").glob("*.py")},
        "stages": "all shortlists -> cached grades/context -> gold evaluation",
        "new_api_calls": 0, "default_changed": False,
    })
    select_shortlists(source, run)
    filings = {r["id"]: Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl")}
    store = LocalSources(filings)
    validation = replay_contexts(source, rerank, run, filings, store)
    result = evaluate(source, run)
    if not all(v["evidence_cap_ok"] and v["prompt_cap_ok"] for v in validation):
        raise ValueError("context_budget_violation")
    if before != protected(source, rerank):
        raise ValueError("protected_file_changed")
    atomic_json(run / "validation.json", {
        "checks": validation, "protected_hashes_unchanged": True,
        "source_files_sha256": store.hashes, "original_context_replay_identical": True,
        "new_api_calls": 0,
    })
    print(json.dumps({"run": str(run), "summary": result["summary"]}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
