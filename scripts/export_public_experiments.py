"""Export allowlisted historical results. Requires ignored local runs; no DB/model calls."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "reports/public/experiments"
SOURCES = {
    "v1_dev": "reports/dev_comparison.json",
    "context": "reports/context_budget/20261027T072215Z_6c99b5/results.json",
    "funnel": "reports/context_budget/20261027T072215Z_6c99b5/funnel_analysis.json",
    "rerank": "reports/rerank/20261027T170703Z_9a25db/results.json",
    "coarse": "reports/coarse_rank/20261028T014418Z_b5443e/results.json",
    "focused": "reports/focused_queries/20261028T022730Z_78c0ce/results.json",
    "serving": "reports/serving/20261028_objective_v4/evaluation.json",
    "ann_real": "reports/serving/ann_benchmark.json",
    "ann_synthetic": "reports/ann_scale/20261028_scale_v1/summary.json",
}


def pick(value, keys):
    return {k: value[k] for k in keys.split() if k in value}


def score(value):
    return pick(value, "recall groups_found groups_required complete")


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--check", action="store_true")
    args = p.parse_args()
    results = {}
    manifest = {
        "schema_version": 1,
        "snapshot_date": "2026-10-29",
        "note": "Allowlisted copies of historical observations; no new benchmark. Raw runs stay local.",
        "sources": {},
    }
    for name, relative in SOURCES.items():
        raw = (ROOT / relative).read_bytes()
        d = json.loads(raw)
        manifest["sources"][name] = {
            "local_source": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        if name == "v1_dev":
            result = {
                "scope": "Historical v1:30 dev queries,25 answerable;28 configurations, not28 chunk strategies; references not independently reviewed.",
                "rows": [
                    pick(
                        r,
                        "config split answer_questions evaluated_at metric at median_latency_seconds mean_context_proxy_tokens",
                    )
                    for r in d
                ],
            }
        elif name == "funnel":
            result = pick(
                d,
                "dataset source_run context_run golden_sha256 scoring_code_sha256 diagnostic_script_sha256 model_api_calls metrics pool_counts final_missing_group_stage_counts interpretation",
            )
        elif name in {"context", "rerank"}:
            result = pick(
                d,
                "dataset metric gold_sha256 scope controlled model_api_calls new_model_api_cost_usd metrics",
            )
            result["per_question"] = [
                {
                    **pick(
                        r,
                        "query_id variant evidence_tokens full_prompt_proxy_tokens context_proxy_tokens context_items",
                    ),
                    "score": score(r["score"]),
                }
                for r in d["per_question"]
            ]
        elif name in {"focused", "coarse"}:
            result = pick(d, "scope summary new_api_calls dataset_profile")
            stages = (
                ("candidate", "shortlist", "context")
                if name == "focused"
                else ("shortlist", "context")
            )
            result["per_question"] = [
                {
                    **pick(
                        r,
                        "query_id arm variant search_jobs candidate_count count evidence_tokens prompt_tokens",
                    ),
                    **{s: score(r[s]) for s in stages},
                }
                for r in d["per_question"]
            ]
        elif name == "serving":
            result = pick(d, "scope metrics")
            result["per_question"] = [
                {
                    **pick(r, "id arm ranker sql_jobs base_sql_jobs"),
                    "scores": {k: score(v) for k, v in r["scores"].items()},
                }
                for r in d["per_question"]
            ]
        elif name == "ann_real":
            result = pick(
                d,
                "n mean_overlap_at20 ann_index_used exact_mean_ms ann_mean_ms frozen_chunks identical_copied_chunks scope",
            )
        else:
            result = pick(d, "metrics source_unchanged limits")
            result["builds"] = [
                {
                    **pick(b, "method rows lists m ef_construction sizes"),
                    "resource": pick(
                        b["resource"],
                        "wall_seconds sampled_peak_backend_rss_bytes sample_interval_seconds",
                    ),
                }
                for b in d["builds"]
            ]
        results[name] = result
    extras = {
        "ann_setup": "reports/ann_scale/20261028_scale_v1/manifest.json",
        "ann_cleanup": "reports/ann_scale/20261028_scale_v1/cleanup.json",
        "rerank_cost": "reports/rerank/20261027T170703Z_9a25db/turn_cost_and_latency.json",
    }
    extra = {}
    for name, relative in extras.items():
        raw = (ROOT / relative).read_bytes()
        extra[name] = json.loads(raw)
        manifest["sources"][name] = {
            "local_source": relative,
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
    setup = extra["ann_setup"]
    results["ann_synthetic"]["setup"] = {
        **pick(setup, "recipe code_sha256"),
        "parameters": pick(
            setup["config"],
            "sizes seed noise_std query_count repeats k selectivities maintenance_mb work_mb",
        ),
        "dimension": setup["source"]["dimension"],
        "postgres_version": setup["database"]["postgres"].split()[1],
        "pgvector_version": setup["database"]["pgvector"],
    }
    results["ann_synthetic"]["cleanup"] = pick(
        extra["ann_cleanup"], "status schema_absent snapshots_absent source_unchanged"
    )
    results["rerank"]["experiment_cost_observation"] = pick(
        extra["rerank_cost"],
        "new_known_peak_list_cost_usd successful_or_schema_repair_responses completed_api_call_latency_seconds latency_note basis",
    )
    for name, result in results.items():
        result["provenance"] = manifest["sources"][name]
        result["interpretation_boundary"] = (
            "Nearest-neighbor overlap / SQL-only timing, not financial evidence or service RPS."
            if name.startswith("ann")
            else "Source-span evidence recall; not answer accuracy. Historical/dev conditions, not current production acceptance."
        )
    # A small recorded success/failure example; never export provider IDs/messages/config.
    success_path = "logs/serving/ea8275e908474d00ac8869b96561a4bc.json"
    failed_path = "logs/serving/49685ef07abf47649165e21e2381d4f1.json"
    success = json.loads((ROOT / success_path).read_bytes())
    failed = json.loads((ROOT / failed_path).read_bytes())
    answer = success["generation"]["structured_answer"]
    cited = json.dumps(answer, ensure_ascii=False)
    evidence = []
    for e in success["runtime_evidence"]:
        if "[" + e["citation"] + "]" not in cited:
            continue
        evidence.append(
            {
                **pick(
                    e,
                    "citation document_id ticker fiscal_year period_end filed_at source_url chunk_id source_spans",
                ),
                "preview": e["text"][:320],
                "preview_truncated": len(e["text"]) > 320,
            }
        )
    demo = {
        "status": "recorded_demo_not_live_or_ground_truth",
        "success": {
            "inputs": pick(success["inputs"], "original_question as_of"),
            "status": success["status"],
            "structured_answer": answer,
            "evidence": evidence,
            "structural_validation": success["generation"]["structural_validation"],
            "semantic_support": "not independently verified",
        },
        "failure": {
            "inputs": pick(failed["inputs"], "original_question as_of"),
            "status": failed["status"],
            "error": pick(failed["error"], "type code"),
            "explanation": "Planner schema rejected. Generic repair was insufficient; later fix supplies exact schema-field feedback. Not silently relaxed.",
        },
        "provenance": [
            {
                "source_kind": "saved_success_trace"
                if path == success_path
                else "saved_failed_trace",
                "sha256": hashlib.sha256((ROOT / path).read_bytes()).hexdigest(),
            }
            for path in (success_path, failed_path)
        ],
    }
    results["recorded_demo"] = demo
    OUT.mkdir(parents=True, exist_ok=True)
    for name, value in {**results, "manifest": manifest}.items():
        encoded = (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()
        path = OUT / f"{name}.json"
        if args.check:
            assert path.read_bytes() == encoded, f"Export differs: {path.name}"
        else:
            path.write_bytes(encoded)
    print(
        json.dumps(
            {
                "files": len(results) + 1,
                "mode": "check" if args.check else "export",
                "provider_calls": 0,
            }
        )
    )


if __name__ == "__main__":
    main()
