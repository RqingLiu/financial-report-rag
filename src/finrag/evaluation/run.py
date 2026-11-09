"""Run query-only development requests through unchanged serving defaults; local artifacts only."""

import argparse
import json
import re
from decimal import Decimal
from pathlib import Path

from finrag.agent.planner import Request
from finrag.core.config import ROOT
from finrag.core.deadlines import DeadlineLLM
from finrag.core.files import atomic_json, digest, read_jsonl
from finrag.serving.runtime import execute, load_config, resources, shared_budget


def snapshot(budget):
    return {k: v for k, v in budget.snapshot().items() if k != "unresolved_requests"}


def run(
    out, stop_usd=None, *, ids=None, calculation_tool=False, queries_path=None, retrieve_only=False
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
    with resources(config) as (store, llm, embedder, ce):
        identity = {
            "config": config.model_dump(mode="json"),
            "queries_sha256": digest(query_path.read_bytes()),
            "selected_ids": [q["id"] for q in queries],
            "evaluation_path": "planner_retrieval" if retrieve_only else "end_to_end",
            "sources": {
                str(p.relative_to(ROOT)): digest(p.read_bytes())
                for p in sorted((ROOT / "src/finrag").rglob("*.py"))
            },
            "catalog": store.catalog().metadata(queries[0]["as_of"]),
        }
        manifest_path = out / "manifest.json"
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text())
            if manifest["identity"] != identity:
                raise ValueError("resume_identity_changed_use_new_output_directory")
        else:
            manifest = {"identity": identity, "budget_before": snapshot(budget)}
            atomic_json(manifest_path, manifest)
        model = DeadlineLLM(llm)
        statuses = []
        for row in queries:
            path = out / "traces" / f"{row['id']}.json"
            if path.exists():
                data = json.loads(path.read_text())
                print(row["id"], "saved", data["status"], flush=True)
            else:
                request = Request(
                    **{
                        k: row[k]
                        for k in ("question", "reading_context", "confirmed_context", "as_of")
                    }
                )
                embedder.events.clear()
                data = execute(
                    request,
                    config,
                    store,
                    model,
                    embedder,
                    ce,
                    query_id=row["id"],
                    do_generate=not retrieve_only,
                )
                # Evaluation metadata is not part of the model-facing request.
                data["inputs"]["corpus_scope"] = row["corpus_scope"]
                data["embedding_events"] = list(embedder.events)
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
            if data.get("error", {}).get("type") in ("BudgetExceeded", "ProviderFailure"):
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
    args = parser.parse_args()
    run(
        args.out,
        args.stop_usd,
        ids=args.ids,
        calculation_tool=args.calculation_tool,
        queries_path=args.queries,
        retrieve_only=args.retrieve_only,
    )


if __name__ == "__main__":
    main()
