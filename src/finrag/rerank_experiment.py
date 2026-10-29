"""Fixed-actual-context-cost reranking experiment; evaluate only after selection."""

import argparse
import json
import os
import shutil
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from statistics import mean
from uuid import uuid4

from dotenv import dotenv_values

from .baseline import safe_error
from .config import ROOT
from .context import EvidenceStore
from .context_experiment import protected_files
from .deadlines import DeadlineLLM
from .files import atomic_json, digest, read_jsonl
from .generation import Budget, DeepSeek
from .models import Filing, Hit
from .planning import PipelineConfig
from .repository import Repository
from .rerank_context import (
    candidates_for_rerank,
    evidence_records,
    fetch_blocks,
    prompt_tokens,
    select_reranked,
)
from .reranking import grade_candidates

VARIANTS = (
    ("rerank80_full", 80, False, False),
    ("rerank_all_full", None, False, False),
    ("rerank_all_compact", None, True, False),
    ("rerank_all_compact_balanced", None, True, True),
)


def baseline_context(data, reference, filings):
    hits = [Hit(**h) for h in reference["selected_hits"]]
    texts = reference["texts"]
    evidence = evidence_records(hits, texts, filings)
    cap = reference["context_metadata"]["context_proxy_tokens"]
    return cap, prompt_tokens(data, evidence)


def selection_phase(source, contexts, run, ids, llm, store, filings, reuse=None):
    for path in sorted((source / "traces").glob("U*.json")):
        if ids and path.stem not in ids:
            continue
        if reuse is not None:
            names = [
                "inputs",
                "grades",
                "baseline",
                *[v[0] for v in VARIANTS],
                "compact_original10_cost",
            ]
            old_files = [reuse / name / path.name for name in names]
            if all(p.exists() for p in old_files):
                old_input = json.loads(old_files[0].read_text())
                if old_input["source_trace_sha256"] != digest(path.read_bytes()):
                    raise ValueError("reused_input_source_changed")
                old_manifest = json.loads((reuse / "manifest.json").read_text())
                for module in ["reranking.py", "rerank_context.py", "answering.py"]:
                    if old_manifest["source_code_sha256"][module] != digest(
                        (ROOT / "src/finrag" / module).read_bytes()
                    ):
                        raise ValueError("reused_selection_algorithm_changed")
                for old in old_files:
                    target = run / old.parent.name / old.name
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(old, target)
                print(f"{path.stem}: reused completed selections from {reuse.name}", flush=True)
                continue
        original = json.loads(path.read_text())
        # Explicit projection: old answers/evaluation fields never cross the reranking boundary.
        data = {"inputs": original["inputs"], "plan": original["plan"]}
        config = PipelineConfig(**original["config"])
        hits = [Hit(**h) for h in original["retrieval"]["candidate_hits"]]
        ranked_ids = [h["chunk"]["id"] for h in original["retrieval"]["ranked_hits"]]
        positions = {cid: i for i, cid in enumerate(ranked_ids)}
        hits.sort(key=lambda h: positions.get(h.chunk.id, len(positions)))
        blocks = fetch_blocks(hits, store)
        candidates = candidates_for_rerank(hits, blocks, filings)
        atomic_json(
            run / "inputs" / f"{path.stem}.json",
            {
                **data,
                "source_trace_sha256": digest(path.read_bytes()),
                "candidates": candidates,
            },
        )
        print(f"{path.stem}: grade {len(candidates)} unique candidates", flush=True)
        grades, events = grade_candidates(
            data["inputs"],
            data["plan"],
            candidates,
            llm,
            ROOT / "data/cache/rerank",
            run / "batches" / path.stem,
        )
        atomic_json(run / "grades" / path.name, {"grades": grades, "events": events})
        reference = json.loads((contexts / "rank30/traces" / path.name).read_text())
        evidence_cap, prompt_cap = baseline_context(data, reference, filings)
        atomic_json(
            run / "baseline" / path.name,
            {
                "query_id": path.stem,
                "selected_hits": reference["selected_hits"],
                "evidence_tokens": evidence_cap,
                "full_prompt_proxy_tokens": prompt_cap,
            },
        )
        for name, window, compact, balanced in VARIANTS:
            pool = [h for h in hits if window is None or positions.get(h.chunk.id, 999999) < window]
            selected, texts, evidence, metadata = select_reranked(
                pool,
                grades,
                blocks,
                store,
                filings,
                config,
                data,
                evidence_cap,
                prompt_cap,
                compact=compact,
                balanced=balanced,
            )
            atomic_json(
                run / name / path.name,
                {
                    "query_id": path.stem,
                    "plan": data["plan"],
                    "inputs": data["inputs"],
                    "selected_hits": [h.model_dump() for h in selected],
                    "texts": texts,
                    "runtime_evidence": evidence,
                    "metadata": metadata,
                    "generation": "not_run",
                },
            )
        # Stricter original10 actual input budget: reuse grades, no new model calls.
        strict = json.loads((contexts / "rank10/traces" / path.name).read_text())
        strict_evidence, strict_prompt = baseline_context(data, strict, filings)
        selected, texts, evidence, metadata = select_reranked(
            hits,
            grades,
            blocks,
            store,
            filings,
            config,
            data,
            strict_evidence,
            strict_prompt,
            compact=True,
            balanced=True,
        )
        atomic_json(
            run / "compact_original10_cost" / path.name,
            {
                "query_id": path.stem,
                "selected_hits": [h.model_dump() for h in selected],
                "texts": texts,
                "runtime_evidence": evidence,
                "metadata": metadata,
                "baseline_hits": strict["selected_hits"],
                "generation": "not_run",
            },
        )
        print(f"{path.stem}: all selections saved", flush=True)


def evaluate(run):
    # This is the only label-read phase; all runtime selections already exist on disk.
    from .evaluation import score
    from .models import Question

    gold = {
        q.id: q
        for q in (
            Question(**r) for r in read_jsonl(ROOT / "data/evaluation/golden_v2/golden.jsonl")
        )
    }
    rows, metrics = [], []
    names = ["baseline", *[v[0] for v in VARIANTS], "compact_original10_cost"]
    for name in names:
        current = []
        for path in sorted((run / name).glob("U*.json")):
            data = json.loads(path.read_text())
            q = gold[data["query_id"]]
            result = score(q, [Hit(**h) for h in data["selected_hits"]])
            meta = data.get("metadata", data)
            if name != "baseline":
                assert meta["evidence_tokens"] <= meta["evidence_token_cap"]
                assert meta["full_prompt_proxy_tokens"] <= meta["full_prompt_cap"]
            previous = json.loads((run / "baseline" / path.name).read_text())
            old = score(q, [Hit(**h) for h in previous["selected_hits"]])
            if name == "compact_original10_cost":
                old = score(q, [Hit(**h) for h in data["baseline_hits"]])
            row = {
                "query_id": q.id,
                "variant": name,
                "score": result,
                "baseline_recall": old["recall"],
                "delta": result["recall"] - old["recall"],
                "comparison_baseline": "original10_actual_cost"
                if name == "compact_original10_cost"
                else "rank30_actual_cost",
                "evidence_tokens": meta["evidence_tokens"],
                "full_prompt_proxy_tokens": meta["full_prompt_proxy_tokens"],
            }
            if name == "compact_original10_cost":
                row["strict_original10_recall"] = old["recall"]
            rows.append(row)
            current.append(row)
        if current:
            metrics.append(
                {
                    "variant": name,
                    "n": len(current),
                    "macro_recall": mean(r["score"]["recall"] for r in current),
                    "micro_found": sum(r["score"]["groups_found"] for r in current),
                    "micro_required": sum(r["score"]["groups_required"] for r in current),
                    "complete": sum(r["score"]["complete"] for r in current),
                    "improved": sum(r["delta"] > 0 for r in current),
                    "regressions": [r["query_id"] for r in current if r["delta"] < 0],
                    "mean_evidence_tokens": mean(r["evidence_tokens"] for r in current),
                    "mean_full_prompt_tokens": mean(r["full_prompt_proxy_tokens"] for r in current),
                }
            )
    result = {
        "scope": "dev only; all selections saved before labels loaded; no answer generation",
        "target_macro_recall": 0.70,
        "metrics": metrics,
        "per_question": rows,
    }
    atomic_json(run / "results.json", result)
    print(json.dumps(metrics, ensure_ascii=False, indent=2), flush=True)
    return result


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--source-run", type=Path, default=ROOT / "reports/planner/20261027T034153Z_198f65"
    )
    parser.add_argument(
        "--context-run", type=Path, default=ROOT / "reports/context_budget/20261027T072215Z_6c99b5"
    )
    parser.add_argument("--ids", default="")
    parser.add_argument(
        "--reuse-completed",
        type=Path,
        help="Reuse completed selections from an interrupted run; verifies source/prompt/selector hashes",
    )
    args = parser.parse_args()
    run = (
        ROOT
        / "reports/rerank"
        / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
    )
    run.mkdir(parents=True)
    print(f"RUN_DIR={run}", flush=True)
    before = protected_files(args.source_run.resolve())
    before.pop("data/cache/baseline/budget.jsonl", None)  # New authorized reranking is paid.
    budget = Budget(ROOT / "data/cache/baseline/budget.jsonl", stop_usd="2.00")
    prior = budget.snapshot()
    atomic_json(
        run / "manifest.json",
        {
            "source_run": str(args.source_run),
            "context_run": str(args.context_run),
            "target": 0.70,
            "budget_before": prior,
            "protected_files": before,
            "source_code_sha256": {
                p.name: digest(p.read_bytes()) for p in (ROOT / "src/finrag").glob("*.py")
            },
            "cost_control": "each query <= rank30 actual evidence AND full serialized answer-input proxy tokens",
            "reranking_cost_is_additional": True,
            "reuse_completed_from": str(args.reuse_completed) if args.reuse_completed else None,
            "absolute_request_deadline_seconds": 60,
        },
    )
    env = dotenv_values(ROOT / ".env")
    key = os.environ.get("DEEPSEEK_API_KEY") or env.get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("missing_model_configuration")
    repository = Repository(
        os.environ.get("DATABASE_URL")
        or env.get("DATABASE_URL")
        or "postgresql://localhost/financial_report_rag"
    )
    llm = DeepSeek(key, budget)
    try:
        repository.connection.execute("SET default_transaction_read_only=on")
        filings = {f.id: f for f in (Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl"))}
        selection_phase(
            args.source_run,
            args.context_run,
            run,
            set(args.ids.split(",")) - {""},
            DeadlineLLM(llm),
            EvidenceStore(repository),
            filings,
            reuse=args.reuse_completed,
        )
    finally:
        llm.close()
        repository.close()
        after_budget = budget.snapshot()
        atomic_json(
            run / "cost.json",
            {
                "before": prior,
                "after": after_budget,
                "new_peak_list_cost_usd": str(
                    Decimal(after_budget["known_peak_list_cost_usd"])
                    - Decimal(prior["known_peak_list_cost_usd"])
                ),
            },
        )
    result = evaluate(run)
    after = protected_files(args.source_run.resolve())
    after.pop("data/cache/baseline/budget.jsonl", None)
    atomic_json(
        run / "validation.json",
        {
            "protected_files_unchanged": before == after,
            "all_contexts_within_both_per_query_actual_caps": True,
            "selection_completed_before_gold_loaded": True,
            "attempted_questions": len(list((run / "baseline").glob("*.json"))),
            "target_met_variants": [
                m["variant"] for m in result["metrics"] if m["macro_recall"] >= 0.70
            ],
            "answer_generation": "not_run",
            "database_writes": False,
        },
    )
    if before != after:
        raise ValueError("protected_files_changed")


def main():
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 — persist paid raw output, do not print credentials
        print(
            json.dumps({"status": "rerank_experiment_error", "error": safe_error(exc)}), flush=True
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
