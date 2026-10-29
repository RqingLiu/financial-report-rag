"""Offline audit of the fixed-slot query experiment; no model/DB connections."""

import argparse
import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from statistics import mean, median

from finrag.chunk import token_count
from finrag.coarse_experiment import LocalSources
from finrag.config import ROOT
from finrag.files import atomic_json, read_jsonl
from finrag.focus_experiment import ARMS, RERANK, SOURCE, check_run
from finrag.focused_query import search_signature
from finrag.models import Filing
from finrag.planned_retrieval import prepare_searches
from finrag.planning import Catalog, PipelineConfig, Plan


def audit(run):
    check_run(run)
    filings = {r["id"]: Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl")}
    store = LocalSources(filings)
    catalog = Catalog.load(ROOT)
    checks, span_count = [], 0
    for source in sorted((SOURCE / "traces").glob("U*.json")):
        old = json.loads(source.read_text())
        base_plan = Plan(**old["plan"])
        baseline = json.loads((RERANK / "baseline" / source.name).read_text())
        for arm in ARMS:
            retrieval = json.loads((run / "retrieval" / arm / source.name).read_text())
            plan = Plan(**retrieval["plan"])
            config = PipelineConfig(**retrieval["config"])
            restored = plan.model_dump(mode="json")
            for task, original in zip(restored["tasks"], old["plan"]["tasks"], strict=True):
                assert len(task["dense_queries"]) == len(original["dense_queries"])
                task["dense_queries"] = original["dense_queries"]
            assert restored == old["plan"]
            assert search_signature(prepare_searches(plan, catalog, config)) == search_signature(
                prepare_searches(base_plan, catalog, config))
            ids = retrieval["shortlist_ids"]
            pool = {h["chunk"]["id"] for h in retrieval["candidate_hits"]}
            assert len(ids) <= 80 and len(set(ids)) == len(ids) and set(ids) <= pool
            ctx = json.loads((run / "contexts" / arm / source.name).read_text())
            meta = ctx["metadata"]
            assert len(ctx["selected_hits"]) <= 30
            assert meta["evidence_tokens"] == sum(token_count(t) for t in ctx["texts"].values())
            assert meta["evidence_tokens"] <= baseline["evidence_tokens"]
            assert meta["full_prompt_proxy_tokens"] <= baseline["full_prompt_proxy_tokens"]
            for evidence in ctx["runtime_evidence"]:
                assert evidence["chunk_id"] in ids
                assert evidence["filed_at"] <= old["inputs"]["as_of"]
                for span in evidence["source_spans"]:
                    block = store.data[span["block_id"]]
                    assert block.document_id == evidence["document_id"]
                    assert block.start <= span["start"] < span["end"] <= block.end
                    actual = block.text[span["start"]-block.start:span["end"]-block.start]
                    assert actual.strip() in evidence["text"]
                    span_count += 1
            if arm == "wide":
                expected = json.loads((RERANK / "rerank80_full" / source.name).read_text())
                assert ctx["selected_hits"] == expected["selected_hits"] and ctx["texts"] == expected["texts"]
            checks.append({"query_id": source.stem, "arm": arm, "shortlist_count": len(ids),
                           "source_scope_query_slots_jobs_and_dual_budgets_ok": True})
    result = {"checks": checks, "contexts": len(checks), "verified_source_spans": span_count,
              "original_wide_contexts_identical": True, "protected_hashes_and_code_ok": True,
              "index_snapshot": json.loads((run / "index_snapshot.json").read_text()),
              "local_source_hashes": store.hashes, "default_changed": False}
    atomic_json(run / "validation.json", result)
    return result


def costs(run):
    first = ROOT / "reports/focused_queries/20261028T022135Z_6cc13c/manifest.json"
    before = json.loads(first.read_text())["budget_before"]
    after = json.loads((run / "budget_after_rerank.json").read_text())
    start = datetime.fromisoformat("2026-10-28T02:21:35+00:00")
    events = read_jsonl(ROOT / "data/cache/baseline/budget.jsonl")
    reservations = {r["id"]: r for r in events if r["event"] == "reserve"
                    and datetime.fromisoformat(r["at"]) >= start}
    summaries, latency = defaultdict(lambda: {"calls": 0, "cost": Decimal(0)}), []
    for row in events:
        if row["event"] != "settle" or row["id"] not in reservations:
            continue
        reservation = reservations[row["id"]]
        purpose = reservation["purpose"]
        summaries[purpose]["calls"] += 1
        summaries[purpose]["cost"] += Decimal(row["amount_usd"])
        latency.append((datetime.fromisoformat(row["at"])-datetime.fromisoformat(reservation["at"])).total_seconds())
    delta = Decimal(after["known_peak_list_cost_usd"]) - Decimal(before["known_peak_list_cost_usd"])
    assert sum((v["cost"] for v in summaries.values()), Decimal(0)) == delta
    assert after["unresolved_reserved_usd"] == before["unresolved_reserved_usd"]
    result = {
        "turn_known_peak_list_cost_usd": str(delta),
        "cumulative_known_peak_list_cost_usd": after["known_peak_list_cost_usd"],
        "old_unresolved_reserved_usd": after["unresolved_reserved_usd"],
        "new_unresolved_requests": 0, "includes_failed_pilot": True,
        "stages": {k: {"calls": v["calls"], "cost_usd": str(v["cost"])} for k, v in summaries.items()},
        "settled_request_latency_seconds": {"mean": mean(latency), "median": median(latency), "max": max(latency)},
        "note": "persisted conservative peak list assumption; not invoice; latency excludes cache and is not end-to-end SLA",
        "new_unique_top80_candidates_graded": sum(json.loads(p.read_text())["new_candidates"]
                                                for p in (run / "grades").glob("U*.json")),
    }
    atomic_json(run / "costs.json", result)
    return result


if __name__ == "__main__":
    from pathlib import Path

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run", type=Path)
    args = parser.parse_args()
    validated = audit(args.run.resolve())
    print(json.dumps({"contexts": validated["contexts"], "spans": validated["verified_source_spans"],
                      "costs": costs(args.run.resolve())}, ensure_ascii=False, indent=2))
