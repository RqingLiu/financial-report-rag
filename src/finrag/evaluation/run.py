"""Run query-only development requests through unchanged serving defaults; local artifacts only."""

import argparse
import json
import re
from contextlib import nullcontext
from decimal import Decimal
from pathlib import Path

from finrag.agent.planner import Request
from finrag.core.config import ROOT
from finrag.core.files import atomic_json, digest, read_jsonl
from finrag.providers.llm import budget_scope
from finrag.serving.runtime import load_config, query, resources, shared_budget


def snapshot(budget):
    return {k: v for k, v in budget.snapshot().items() if k != "unresolved_requests"}


def run(
    out,
    stop_usd=None,
    *,
    ids=None,
    calculation_tool=False,
    queries_path=None,
    retrieve_only=False,
    batch_usd=None,
):
    scope = (
        budget_scope("evaluation:" + digest(str(out.resolve())), batch_usd)
        if batch_usd is not None
        else nullcontext()
    )
    with scope:
        return _run(
            out,
            stop_usd,
            ids=ids,
            calculation_tool=calculation_tool,
            queries_path=queries_path,
            retrieve_only=retrieve_only,
            batch_usd=batch_usd,
        )


def _run(
    out,
    stop_usd=None,
    *,
    ids=None,
    calculation_tool=False,
    queries_path=None,
    retrieve_only=False,
    batch_usd=None,
):
    config = load_config()
    if calculation_tool:
        config = config.model_copy(update={"calculation_tool": True})
    if stop_usd is not None:
        # An explicit CLI override is for an authorized experiment, never a serving edit.
        config = type(config)(**{**config.model_dump(), "stop_usd": stop_usd})
    query_path = queries_path or ROOT / "data/evaluation/golden_v2/retrieval_queries.jsonl"
    queries = read_jsonl(query_path)
    allowed = {"id", "question", "reading_context", "confirmed_context", "as_of", "corpus_scope"}
    if not queries or any(set(q) != allowed for q in queries):
        raise ValueError("use_query_only_records_without_reference_or_labels")
    if any(
        not isinstance(q["id"], str)
        or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", q["id"])
        or ".." in q["id"]
        for q in queries
    ) or len({q["id"] for q in queries}) != len(queries):
        raise ValueError("unsafe_or_duplicate_query_id")
    if ids:
        if len(ids) != len(set(ids)) or set(ids) - {q["id"] for q in queries}:
            raise ValueError("invalid_query_subset")
        queries = [q for q in queries if q["id"] in ids]
    budget = shared_budget(config)
    with resources(config, models=False) as (store, *_):
        catalog = store.catalog().metadata(queries[0]["as_of"])
    identity = {
        "config": config.model_dump(mode="json"),
        "queries_sha256": digest(query_path.read_bytes()),
        "selected_ids": [q["id"] for q in queries],
        "evaluation_path": "planner_retrieval" if retrieve_only else "end_to_end",
        "sources": {
            str(p.relative_to(ROOT)): digest(p.read_bytes())
            for p in sorted((ROOT / "src/finrag").rglob("*.py"))
        },
        "catalog": catalog,
        "batch_usd": str(batch_usd) if batch_usd is not None else None,
    }
    manifest_path = out / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["identity"] != identity:
            raise ValueError("resume_identity_changed_use_new_output_directory")
    else:
        manifest = {"identity": identity, "budget_before": snapshot(budget)}
        atomic_json(manifest_path, manifest)
    statuses = []
    for row in queries:
        path = out / "traces" / f"{row['id']}.json"
        if path.exists():
            data = json.loads(path.read_text())
            print(row["id"], "saved", data["status"], flush=True)
        else:
            request = Request(
                **{k: row[k] for k in ("question", "reading_context", "confirmed_context", "as_of")}
            )
            data = query(
                request,
                config,
                query_id=row["id"],
                do_generate=not retrieve_only,
            )
            # Evaluation metadata is not part of the model-facing request.
            data["inputs"]["corpus_scope"] = row["corpus_scope"]
            atomic_json(path, data)
            print(row["id"], data["status"], flush=True)
        statuses.append({"id": row["id"], "status": data["status"]})
        after = snapshot(budget)
        atomic_json(
            out / "progress.json",
            {
                "attempts": statuses,
                "budget_after": after,
                "new_known_peak_list_cost_usd": str(
                    Decimal(after["known_peak_list_cost_usd"])
                    - Decimal(manifest["budget_before"]["known_peak_list_cost_usd"])
                ),
            },
        )
        # Do not turn unknown billing or exhausted credit into repeated paid attempts.
        if data.get("error", {}).get("type") in ("BudgetExceeded", "ProviderFailure") or data.get(
            "agent", {}
        ).get("outcome") in ("budget_exhausted", "cancelled", "deadline_exceeded"):
            break


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ids", nargs="+")
    parser.add_argument("--calculation-tool", action="store_true")
    parser.add_argument("--queries", type=Path, help="Query-only JSONL; never a gold/answer file")
    parser.add_argument(
        "--retrieve-only",
        action="store_true",
        help="Run planner plus retrieval/context; skip calculation and generation",
    )
    parser.add_argument(
        "--stop-usd",
        type=float,
        help="Experiment-only cumulative stop; requires explicit authorization",
    )
    parser.add_argument(
        "--batch-usd", type=Decimal, help="Explicit additional batch cap; same persistent ledger"
    )
    args = parser.parse_args()
    run(
        args.out,
        args.stop_usd,
        ids=args.ids,
        calculation_tool=args.calculation_tool,
        queries_path=args.queries,
        retrieve_only=args.retrieve_only,
        batch_usd=args.batch_usd,
    )


if __name__ == "__main__":
    main()
