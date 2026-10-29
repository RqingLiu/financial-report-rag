"""Explicit catalog/planner RAG CLI. Legacy fr-rag query remains a frozen comparison path."""

import argparse
import json
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from dotenv import dotenv_values

from .answering import generate_answer
from .baseline import QUERY_KEYS, file_versions, report, safe_error, score_trace, select_rows
from .config import ROOT, settings
from .files import atomic_json, digest, read_jsonl
from .generation import Budget, BudgetedVoyage, DeepSeek
from .models import IndexConfig, Question
from .planned_retrieval import PlannedRetriever
from .planning import Catalog, PipelineConfig, PlanRejected, Request, plan_request
from .repository import Repository
from .tracing import Trace


def inputs_from_query(row):
    if set(row) != QUERY_KEYS:
        raise PlanRejected("query_only_contract_contains_extra_fields")
    confirmed = row["confirmed_context"] or {}
    if confirmed.get("as_of") and confirmed["as_of"] != row["as_of"]:
        raise PlanRejected("confirmed_cutoff_conflict")
    # Document IDs are opaque metadata keys; do not parse ticker/year out of their names.
    text = row["question"] + "\n" + row["reading_context"]
    if confirmed:
        text += "\n用户已确认：" + json.dumps(confirmed, ensure_ascii=False)
    return {
        "query_id": row["id"],
        "original_question": row["question"],
        "reading_context": row["reading_context"],
        "confirmed_context": row["confirmed_context"],
        "as_of": row["as_of"],
        "corpus_scope": row["corpus_scope"],
        "effective_question": text,
    }


class TracedLLM:
    def __init__(self, llm, trace):
        self.llm, self.trace = llm, trace

    def generate(self, messages, **kwargs):
        with self.trace.stage("llm_call", {"messages": messages, **kwargs}) as s:
            result = self.llm.generate(messages, **kwargs)
            s["outputs"] = result
            return result


@contextmanager
def resources(config):
    import os

    s = settings()
    key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(ROOT / ".env").get("DEEPSEEK_API_KEY")
    if not key:
        raise ValueError("DEEPSEEK_API_KEY missing")
    budget = Budget(ROOT / "data/cache/baseline/budget.jsonl")
    repo = Repository(s.database_url.get_secret_value())
    repo.connection.execute("SET default_transaction_read_only=on")
    embedder = BudgetedVoyage(
        s.voyage_api_key.get_secret_value(),
        ROOT / "data/cache/embeddings",
        model=s.voyage_model,
        dimension=s.embedding_dimension,
        shared_budget=budget,
    )
    llm = DeepSeek(key, budget)
    try:
        catalog = Catalog.load(ROOT)
        indexes = [
            IndexConfig(**r) for r in json.loads((ROOT / "configs/indexes.json").read_text())
        ]
        ix = next(i for i in indexes if i.name == config.index_name)
        retriever = PlannedRetriever(repo, embedder, catalog, ix, config)
        yield retriever, llm, budget
    finally:
        llm.close()
        embedder.close()
        repo.close()


def retrieve_one(row, retriever, llm, config):
    inputs = inputs_from_query(row)
    trace = Trace(row["id"], inputs)
    data = trace.data
    data["pipeline"] = "catalog_queryplan_v1"
    data["config"] = config.model_dump()
    try:
        request = Request(
            question=row["question"],
            reading_context=row["reading_context"],
            confirmed_context=row["confirmed_context"],
            as_of=row["as_of"],
        )
        with trace.stage("query_plan", {"request": request.model_dump(mode="json")}) as s:
            plan, record = plan_request(
                request, retriever.catalog, config, TracedLLM(llm, trace), ROOT / "data/cache/plans"
            )
            data["plan"] = plan.model_dump(mode="json")
            s["outputs"] = {"plan": data["plan"], **record}
        data["policy"] = {
            "outcome": plan.action,
            "reason": plan.clarification_questions or plan.limitations or ["valid_plan"],
        }
        if plan.action != "retrieve":
            data["status"] = plan.action
            data["runtime_evidence"] = []
            return data
        records = retriever.search(plan, config, trace)
        data["search_records"] = records
        ranked, final, texts, context_meta = retriever.context(records, config, trace, plan=plan)
        candidates = list({h["chunk"]["id"]: h for r in records for h in r["hits"]}.values())
        data["retrieval"] = {
            "candidate_hits": candidates,
            "ranked_hits": [h.model_dump() for h in ranked],
            "final_hits": [h.model_dump() for h in final],
            "metadata": {
                "scope": sorted({d for r in records for d in r["documents"]}),
                **context_meta,
            },
        }
        evidence = []
        for i, hit in enumerate(final, 1):
            f = retriever.catalog.by_id[hit.chunk.document_id]
            evidence.append(
                {
                    "citation": f"E{i}",
                    "document_id": f.id,
                    "ticker": f.ticker,
                    "fiscal_year": f.fiscal_year,
                    "period_end": f.period_end,
                    "filed_at": f.filed_at,
                    "source_url": f.source_url,
                    "chunk_id": hit.chunk.id,
                    "source_spans": [*hit.chunk.spans, *hit.expanded_spans],
                    "text": texts[hit.chunk.id],
                }
            )
        data["runtime_evidence"] = evidence
        data["status"] = "retrieved" if final else "insufficient_evidence"
    except Exception as exc:  # noqa: BLE001 — persist typed per-query failure, never widen scope
        data["status"], data["error"] = "error", safe_error(exc)
        if isinstance(exc, PlanRejected):
            data["error"]["code"] = str(exc)
    return data


def answer_one(data, llm):
    if data.get("generation") or data["status"] != "retrieved":
        return data
    trace = Trace(data["query_id"], data["inputs"])
    trace.data = data
    try:
        with trace.stage("generation", {"prompt_version": "need-aligned-answer-v1"}) as s:
            result = generate_answer(data, TracedLLM(llm, trace))
            s["outputs"] = result
            data["generation"] = result
            data["status"] = "generated"
    except Exception as exc:  # noqa: BLE001 — paid output remains inside llm_call trace on validation failure
        data["status"], data["error"] = "error", safe_error(exc)
        if isinstance(exc, PlanRejected):
            data["error"]["code"] = str(exc)
    return data


def ablate(run, retriever):
    """Replay saved candidates only. Never call planner or embedder, never choose using test."""
    gold = {
        q.id: q
        for q in (
            Question(**r) for r in read_jsonl(ROOT / "data/evaluation/golden_v2/golden.jsonl")
        )
    }
    values = []
    for path in sorted((run / "traces").glob("*.json")):
        data = json.loads(path.read_text())
        if not data.get("search_records"):
            continue
        config = PipelineConfig(**data["config"])
        for mode in ["dense", "fts", "equal_rrf", "weighted_rrf"]:
            for strategy in ["rank", "coverage"]:
                for tables in [False, True]:
                    cfg = config.model_copy(
                        update={"context_strategy": strategy, "expand_tables": tables}
                    )
                    t = Trace(data["query_id"], data["inputs"])
                    ranked, final, texts, metadata = retriever.context(
                        data["search_records"], cfg, t, mode
                    )
                    trial = {
                        **data,
                        "retrieval": {
                            "candidate_hits": data["retrieval"]["candidate_hits"],
                            "ranked_hits": [h.model_dump() for h in ranked],
                            "final_hits": [h.model_dump() for h in final],
                        },
                    }
                    scores = score_trace(trial, gold[data["query_id"]])
                    values.append(
                        {
                            "query_id": data["query_id"],
                            "mode": mode,
                            "strategy": strategy,
                            "tables": tables,
                            "score": scores["final_context"],
                            "context_proxy_tokens": metadata["context_proxy_tokens"],
                            "final_hits": trial["retrieval"]["final_hits"],
                            "texts": texts,
                        }
                    )
    from statistics import mean

    metrics = []
    for mode in ["dense", "fts", "equal_rrf", "weighted_rrf"]:
        for strategy in ["rank", "coverage"]:
            for tables in [False, True]:
                rows = [
                    v
                    for v in values
                    if (v["mode"], v["strategy"], v["tables"]) == (mode, strategy, tables)
                ]
                if not rows:
                    continue
                metrics.append(
                    {
                        "mode": mode,
                        "strategy": strategy,
                        "tables": tables,
                        "n": len(rows),
                        "macro_recall": mean(r["score"]["recall"] for r in rows),
                        "micro_found": sum(r["score"]["groups_found"] for r in rows),
                        "micro_required": sum(r["score"]["groups_required"] for r in rows),
                        "complete": sum(r["score"]["complete"] for r in rows),
                        "mean_context_tokens": mean(r["context_proxy_tokens"] for r in rows),
                    }
                )
    atomic_json(
        run / "ablations.json",
        {
            "scope": "same saved candidates; all dev; zero API calls",
            "metrics": metrics,
            "per_question": values,
        },
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


def _main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("run")
    p.add_argument("--ids", default="")
    p.add_argument("--config", type=Path, default=ROOT / "configs/pipeline_dev_selected.json")
    p = sub.add_parser("generate")
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--ids", default="U02,U03,U06,U09,U12,U14")
    p = sub.add_parser("ablate")
    p.add_argument("--run", type=Path, required=True)
    p = sub.add_parser("query")
    p.add_argument("question")
    p.add_argument("--as-of", required=True, help="Explicit filing cutoff YYYY-MM-DD")
    p.add_argument("--reading-context", default="")
    p.add_argument("--config", type=Path, default=ROOT / "configs/pipeline_dev_selected.json")
    args = parser.parse_args()
    config = PipelineConfig(
        **json.loads(
            (
                args.config
                if args.command in ("run", "query")
                else ROOT / "configs/pipeline_dev_selected.json"
            ).read_text()
        )
    )
    if args.command in ("run", "query"):
        run = (
            ROOT
            / "reports/planner"
            / (datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ") + "_" + uuid4().hex[:6])
        )
        (run / "traces").mkdir(parents=True)
        atomic_json(
            run / "manifest.json",
            {
                "created_at": datetime.now(UTC).isoformat(),
                "pipeline": "catalog_queryplan_v1",
                "config": config.model_dump(),
                "versions": file_versions(),
                "baseline": "20261027T025455Z_3031fa",
                "source_code": {
                    p.name: digest(p.read_bytes()) for p in (ROOT / "src/finrag").glob("*.py")
                },
            },
        )
        print(f"RUN_DIR={run}", flush=True)
    else:
        run = args.run
    with resources(config) as (retriever, llm, budget):
        if args.command == "ablate":
            ablate(run, retriever)
            return
        if args.command in ("run", "query"):
            rows = (
                select_rows(args.ids)
                if args.command == "run"
                else [
                    {
                        "id": "query",
                        "question": args.question,
                        "reading_context": args.reading_context,
                        "confirmed_context": None,
                        "as_of": args.as_of,
                        "corpus_scope": {
                            c["ticker"]: sorted({r["report_fy"] for r in c["reports"]})
                            for c in retriever.catalog.metadata(args.as_of)
                        },
                    }
                ]
            )
            consecutive_errors = 0
            for row in rows:
                data = retrieve_one(row, retriever, llm, config)
                if args.command == "query":
                    data = answer_one(data, llm)
                atomic_json(run / "traces" / f"{row['id']}.json", data)
                print(row["id"], data["status"], data.get("error", ""), flush=True)
                consecutive_errors = consecutive_errors + 1 if data["status"] == "error" else 0
                if (
                    data.get("error", {}).get("type") in ("ProviderFailure", "BudgetExceeded")
                    or consecutive_errors >= 3
                ):
                    break
        else:
            for row in select_rows(args.ids):
                path = run / "traces" / f"{row['id']}.json"
                if not path.exists():
                    continue
                data = answer_one(json.loads(path.read_text()), llm)
                atomic_json(path, data)
                print(row["id"], data["status"], data.get("error", ""), flush=True)
                if data.get("error", {}).get("type") in ("ProviderFailure", "BudgetExceeded"):
                    break
    if args.command != "query":
        summary = report(run)
        print(
            json.dumps(
                {"run": str(run), "budget": budget.snapshot(), "metrics": summary["metrics"]}
            ),
            flush=True,
        )
    else:
        print(json.dumps(data, ensure_ascii=False, indent=2))


def main():
    try:
        _main()
    except Exception as exc:  # noqa: BLE001 — CLI startup/IO boundary; do not leak provider/DSN bodies
        record = {"status": "startup_or_io_error", "error": safe_error(exc)}
        if isinstance(exc, PlanRejected):
            record["error"]["code"] = str(exc)
        path = ROOT / "logs/pipeline_errors" / (uuid4().hex + ".json")
        atomic_json(path, record)
        print(json.dumps({**record, "error_record": str(path)}), flush=True)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
