"""Zero-model-API, read-only replay of context budgets on saved development candidates."""

import argparse
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from statistics import mean, median
from time import perf_counter
from uuid import uuid4

from dotenv import dotenv_values

from .chunk import token_count
from .config import ROOT
from .context import EvidenceStore, build_context
from .files import atomic_json, digest, read_jsonl
from .models import Filing
from .planned_retrieval import rank_records
from .planning import PipelineConfig, Plan
from .repository import Repository

VARIANTS = (
    ("rank10", "rank", 10),
    ("rank30", "rank", 30),
    ("need10", "need_budget", 10),
    ("need30", "need_budget", 30),
)


def checksums(paths):
    return {str(p.relative_to(ROOT)): digest(p.read_bytes()) for p in paths if p.is_file()}


def protected_files(source):
    paths = list(source.rglob("*"))
    paths += list((ROOT / "data/evaluation").rglob("*"))
    paths += [
        ROOT / p
        for p in (
            "data/sources.jsonl",
            "configs/best.json",
            "configs/indexes.json",
            "configs/pipeline_dev_selected.json",
            "data/cache/baseline/budget.jsonl",
            "reports/test_release.json",
        )
    ]
    return checksums(paths)


def select(source, run, store, filings):
    """All selection finishes before evaluation labels are loaded."""
    for path in sorted((source / "traces").glob("U*.json")):
        original = json.loads(path.read_text())
        plan = Plan(**original["plan"])
        base = PipelineConfig(**original["config"])
        records = original["search_records"]
        ranked, provenance = rank_records(records, base)
        ranked = ranked[: base.max_unique_candidates]
        for name, strategy, cap in VARIANTS:
            config = base.model_copy(
                update={
                    "context_strategy": strategy,
                    "context_k": cap,
                    "context_tokens": 8000,
                }
            )
            started = perf_counter()
            final, texts, metadata = build_context(
                ranked,
                provenance,
                store,
                filings,
                config,
                plan=plan,
                search_records=records,
            )
            elapsed = perf_counter() - started
            actual_tokens = sum(token_count(text) for text in texts.values())
            if actual_tokens != metadata["context_proxy_tokens"] or actual_tokens > 8000:
                raise ValueError("actual_context_token_budget_mismatch")
            if len(final) > cap:
                raise ValueError("actual_context_item_limit")
            baseline_identical = None
            if name == "rank10":
                baseline_identical = [h.model_dump() for h in final] == original["retrieval"][
                    "final_hits"
                ] and texts == {e["chunk_id"]: e["text"] for e in original["runtime_evidence"]}
                if not baseline_identical:
                    raise ValueError("original_context_replay_changed")
            atomic_json(
                run / name / "traces" / path.name,
                {
                    "query_id": original["query_id"],
                    "inputs": original["inputs"],
                    "plan": original["plan"],
                    "config": config.model_dump(),
                    "source_trace": str(path.relative_to(ROOT)),
                    "source_trace_sha256": digest(path.read_bytes()),
                    "selected_hits": [h.model_dump() for h in final],
                    "texts": texts,
                    "context_metadata": metadata,
                    "context_build_seconds": elapsed,
                    "baseline_identical": baseline_identical,
                    "generation": "not_run",
                    "model_api_calls": 0,
                },
            )
        print(original["query_id"], "four selections saved", flush=True)


def evaluate(source, run):
    # Labels only enter this offline scoring phase, not selection/ranking modules.
    from .evaluation import score
    from .models import Hit, Question

    gold_path = ROOT / "data/evaluation/golden_v2/golden.jsonl"
    gold = {q.id: q for q in (Question(**r) for r in read_jsonl(gold_path))}
    rows, summaries = [], []
    for name, strategy, cap in VARIANTS:
        current = []
        for path in sorted((run / name / "traces").glob("*.json")):
            data = json.loads(path.read_text())
            original = json.loads((source / "traces" / path.name).read_text())
            hits = [Hit(**h) for h in data["selected_hits"]]
            old = [Hit(**h) for h in original["retrieval"]["final_hits"]]
            result, previous = (
                score(gold[data["query_id"]], hits),
                score(gold[data["query_id"]], old),
            )
            row = {
                "query_id": data["query_id"],
                "variant": name,
                "score": result,
                "delta_recall_vs_rank10": result["recall"] - previous["recall"],
                "context_proxy_tokens": data["context_metadata"]["context_proxy_tokens"],
                "context_items": len(hits),
                "context_build_seconds": data["context_build_seconds"],
            }
            rows.append(row)
            current.append(row)
        summaries.append(
            {
                "variant": name,
                "strategy": strategy,
                "item_safety_cap": cap,
                "token_budget": 8000,
                "n": len(current),
                "macro_recall": mean(r["score"]["recall"] for r in current),
                "micro_found": sum(r["score"]["groups_found"] for r in current),
                "micro_required": sum(r["score"]["groups_required"] for r in current),
                "complete_questions": sum(r["score"]["complete"] for r in current),
                "improved_vs_rank10": sum(r["delta_recall_vs_rank10"] > 0 for r in current),
                "regressed_vs_rank10": [
                    r["query_id"] for r in current if r["delta_recall_vs_rank10"] < 0
                ],
                "mean_tokens": mean(r["context_proxy_tokens"] for r in current),
                "max_tokens": max(r["context_proxy_tokens"] for r in current),
                "mean_items": mean(r["context_items"] for r in current),
                "median_context_build_seconds": median(r["context_build_seconds"] for r in current),
            }
        )
    result = {
        "dataset": "golden_v2: 20 development questions, not independent holdout",
        "metric": "exact source-span evidence-group recall; not answer accuracy",
        "gold_sha256": digest(gold_path.read_bytes()),
        "model_api_calls": 0,
        "new_model_api_cost_usd": 0,
        "controlled": "same saved plans/dense candidates/window80/table expansion/8K; no new queries",
        "timing_note": "local context build only, shared warm source cache, not end-to-end latency/SLA",
        "metrics": summaries,
        "per_question": rows,
    }
    atomic_json(run / "results.json", result)
    lines = [
        "# 上下文预算实验",
        "",
        "同20题dev、同候选/80窗口、同表格规则、同8K代理token；零模型API调用。",
        "",
        "| 策略 | 条数上限 | 宏证据Recall | 命中组 | 全证据齐全 | 平均tokens | 平均条数 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in summaries:
        lines.append(
            f"| {row['variant']} | {row['item_safety_cap']} | {row['macro_recall']:.2%} "
            f"| {row['micro_found']}/{row['micro_required']} | {row['complete_questions']}/20 "
            f"| {row['mean_tokens']:.0f} | {row['mean_items']:.1f} |"
        )
    lines += [
        "",
        "逐题完整分数及退步见results.json；各策略traces保存实际文本、来源span与选择决策。",
        "need策略只用运行时任务/来源排名代理，不证明语义完整；未重新生成答案。",
    ]
    (run / "review.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(summaries, ensure_ascii=False, indent=2))
    return result


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_run.resolve()
    run = (
        ROOT
        / "reports/context_budget"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
    )
    run.mkdir(parents=True)
    before = protected_files(source)
    atomic_json(
        run / "manifest.json",
        {
            "created_at": datetime.now(UTC).isoformat(),
            "source_run": str(source.relative_to(ROOT)),
            "variants": VARIANTS,
            "protected_sha256": before,
            "source_code_sha256": checksums((ROOT / "src/finrag").glob("*.py")),
            "selection_reads_gold": False,
            "model_api_clients_created": False,
        },
    )
    print(f"RUN_DIR={run}", flush=True)
    # Offline replay needs database credentials only, not either model API key.
    database_url = (
        os.environ.get("DATABASE_URL")
        or dotenv_values(ROOT / ".env").get("DATABASE_URL")
        or "postgresql://localhost/financial_report_rag"
    )
    repository = Repository(database_url)
    try:
        repository.connection.execute("SET default_transaction_read_only=on")
        if (
            repository.connection.execute("SHOW transaction_read_only").fetchone()[
                "transaction_read_only"
            ]
            != "on"
        ):
            raise ValueError("readonly_connection_required")
        filings = [Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl")]
        store = EvidenceStore(repository)
        select(source, run, store, filings)
    finally:
        repository.close()
    result = evaluate(source, run)
    after = protected_files(source)
    changed = [key for key in before.keys() | after.keys() if before.get(key) != after.get(key)]
    atomic_json(
        run / "validation.json",
        {
            "protected_files_unchanged": not changed,
            "changed_files": changed,
            "rank10_replays_identical": all(
                json.loads(p.read_text())["baseline_identical"]
                for p in (run / "rank10/traces").glob("*.json")
            ),
            "selection_completed_before_gold_loaded": True,
            "all_contexts_within_token_budget": all(
                r["max_tokens"] <= 8000 for r in result["metrics"]
            ),
            "model_api_calls": 0,
        },
    )
    if changed:
        raise ValueError("protected_artifacts_changed")


def main():
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 — never emit DSNs/provider bodies from offline CLI
        print(json.dumps({"status": "context_experiment_error", "type": type(exc).__name__}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
