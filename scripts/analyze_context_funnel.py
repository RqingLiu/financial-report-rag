"""Read saved traces only: attribute evidence loss without changing the RAG or calling APIs.

Run from the project root with .venv/bin/python scripts/analyze_context_funnel.py.
Labels are intentionally used for offline diagnosis, never runtime selection.
"""

import argparse
import json
from collections import Counter
from pathlib import Path
from statistics import mean

from finrag.config import ROOT
from finrag.evaluation import covers, score
from finrag.files import atomic_json, digest, read_jsonl
from finrag.models import Hit, Question


def analyze(source, contexts):
    gold_path = ROOT / "data/evaluation/golden_v2/golden.jsonl"
    gold = {q.id: q for q in (Question(**r) for r in read_jsonl(gold_path))}
    rows = []
    for path in sorted((source / "traces").glob("U*.json")):
        data = json.loads(path.read_text())
        q = gold[data["query_id"]]
        retrieval = data["retrieval"]
        candidates = [Hit(**h) for h in retrieval["candidate_hits"]]
        ranked = [Hit(**h) for h in retrieval["ranked_hits"]]
        context = json.loads((contexts / "rank30/traces" / path.name).read_text())
        final = [Hit(**h) for h in context["selected_hits"]]
        stages = {"candidate_union": candidates, "retained_ranked": ranked}
        stages.update({f"raw_top{k}": ranked[:k] for k in (10, 20, 40, 80)})
        stages["final_rank30_8K"] = final
        scores = {name: score(q, hits) for name, hits in stages.items()}
        decisions = {r["chunk_id"]: r["decision"] for r in context["context_metadata"]["decisions"]}
        missing_details = []
        for gi in scores["final_rank30_8K"]["missing_groups"]:
            if gi in scores["candidate_union"]["missing_groups"]:
                reason = "candidate_union_missing"
            elif gi in scores["retained_ranked"]["missing_groups"]:
                reason = "ranked_capacity_missing"
            elif gi in scores["raw_top80"]["missing_groups"]:
                reason = "outside_window80_or_span_not_complete_in_window"
            else:
                reason = "inside_window80_not_selected"
            supporting = [
                (i, h.chunk.id)
                for i, h in enumerate(ranked, 1)
                if any(covers(e, [h]) for e in q.evidence_groups[gi])
            ]
            missing_details.append(
                {
                    "group_index": gi,
                    "reason": reason,
                    "first_single_chunk_global_rank": supporting[0][0] if supporting else None,
                    "full_cover_candidates_in_window": [
                        {"rank": i, "chunk_id": cid, "context_decision": decisions.get(cid)}
                        for i, cid in supporting
                        if i <= 80
                    ],
                }
            )
        rows.append(
            {
                "query_id": q.id,
                "question": q.question,
                "source_trace_sha256": digest(path.read_bytes()),
                "search_calls": len(data["search_records"]),
                "raw_hits_with_repeats": sum(len(r["hits"]) for r in data["search_records"]),
                "unique_candidate_chunks": len(candidates),
                "retained_ranked_chunks": len(ranked),
                "context_window_chunks": min(80, len(ranked)),
                "final_items": len(final),
                "final_proxy_tokens": context["context_metadata"]["context_proxy_tokens"],
                "scores": scores,
                "missing_group_diagnosis": missing_details,
            }
        )
    metrics = {
        stage: {
            "macro_recall": mean(r["scores"][stage]["recall"] for r in rows),
            "found_groups": sum(r["scores"][stage]["groups_found"] for r in rows),
            "required_groups": sum(r["scores"][stage]["groups_required"] for r in rows),
            "complete_questions": sum(r["scores"][stage]["complete"] for r in rows),
        }
        for stage in rows[0]["scores"]
    }
    counts = {
        key: {
            "min": min(r[key] for r in rows),
            "mean": mean(r[key] for r in rows),
            "max": max(r[key] for r in rows),
        }
        for key in (
            "search_calls",
            "raw_hits_with_repeats",
            "unique_candidate_chunks",
            "retained_ranked_chunks",
            "context_window_chunks",
            "final_items",
        )
    }
    losses = Counter(m["reason"] for r in rows for m in r["missing_group_diagnosis"])
    inside = [
        m
        for r in rows
        for m in r["missing_group_diagnosis"]
        if m["reason"] == "inside_window80_not_selected"
    ]
    return {
        "dataset": "20 dev questions; offline gold-aware diagnosis only",
        "source_run": str(source.relative_to(ROOT)),
        "context_run": str(contexts.relative_to(ROOT)),
        "golden_sha256": digest(gold_path.read_bytes()),
        "scoring_code_sha256": digest((ROOT / "src/finrag/evaluation.py").read_bytes()),
        "diagnostic_script_sha256": digest(Path(__file__).read_bytes()),
        "model_api_calls": 0,
        "database_connections": 0,
        "metrics": metrics,
        "pool_counts": counts,
        "final_missing_group_stage_counts": dict(losses),
        "inside_window_missing_groups_with_full_cover_chunk_rejected_for_budget": sum(
            any(
                c["context_decision"] == "context_budget"
                for c in m["full_cover_candidates_in_window"]
            )
            for m in inside
        ),
        "interpretation": "Stage attribution, not proof of unique semantic cause. Raw prefixes exclude table expansion and token limits; final context includes both. No claim of answer accuracy or reliable precision.",
        "per_question": rows,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-run", type=Path, default=ROOT / "reports/planner/20261027T034153Z_198f65"
    )
    parser.add_argument(
        "--context-run", type=Path, default=ROOT / "reports/context_budget/20261027T072215Z_6c99b5"
    )
    args = parser.parse_args()
    target = args.context_run / "funnel_analysis.json"
    if target.exists():
        raise SystemExit(
            "Refusing to overwrite existing diagnosis; choose a separate context run copy"
        )
    result = analyze(args.source_run.resolve(), args.context_run.resolve())
    atomic_json(target, result)
    print(
        json.dumps(
            {
                key: result[key]
                for key in (
                    "metrics",
                    "pool_counts",
                    "final_missing_group_stage_counts",
                    "inside_window_missing_groups_with_full_cover_chunk_rejected_for_budget",
                )
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
