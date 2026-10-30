"""One bounded pipeline for real queries and the optional HTTP API; no gold imports."""

import json
import os
from contextlib import ExitStack, contextmanager
from datetime import UTC, datetime
from uuid import uuid4

from dotenv import dotenv_values

from ..answering import generate_answer
from ..chunk import config_id
from ..config import ROOT, settings
from ..files import atomic_json, digest
from ..generation import Budget, DeepSeek
from ..models import IndexConfig
from ..planned_retrieval import PlannedRetriever, rank_records
from ..planning import PlanRejected, plan_request
from ..rerank_context import candidates_for_rerank, fetch_blocks, select_reranked
from ..reranking import grade_candidates
from ..tracing import Trace
from .config import ServingConfig
from .providers import CrossEncoder, DocumentEmbedder
from .regroup import regroup
from .store import LiveStore


def load_config(path=None):
    return ServingConfig(**json.loads((path or ROOT / "configs/serving.json").read_text()))


def index_config(config):
    rows = json.loads((ROOT / "configs/indexes.json").read_text())
    return next(IndexConfig(**r) for r in rows if r["name"] == config.pipeline.index_name)


def shared_budget(config):
    return Budget(ROOT / "data/cache/baseline/budget.jsonl", stop_usd=config.stop_usd)


def safe_failure(exc):
    # Never render exception text from psycopg/httpx/Pydantic (can contain inputs/credentials).
    return {
        "type": type(exc).__name__,
        "code": str(exc)
        if isinstance(exc, PlanRejected)
        else getattr(exc, "code", "operation_failed_see_stage_and_exception_type"),
    }


class TracedModel:
    def __init__(self, llm, trace):
        self.llm, self.trace = llm, trace

    def generate(self, messages, **kwargs):
        with self.trace.stage("llm_call", {"messages": messages, **kwargs}) as s:
            result = self.llm.generate(messages, **kwargs)
            s["outputs"] = result
            return result


@contextmanager
def resources(config, *, models=True):
    s = settings()
    with ExitStack() as stack:
        store = LiveStore(s.database_url.get_secret_value(), config, index_config(config))
        stack.callback(store.close)
        if not models:
            yield store, None, None, None
            return
        key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(ROOT / ".env").get(
            "DEEPSEEK_API_KEY"
        )
        if not key:
            raise ValueError("generation_key_missing")
        budget = shared_budget(config)
        llm = DeepSeek(key, budget)
        stack.callback(llm.close)
        embedder = DocumentEmbedder(
            s.voyage_api_key.get_secret_value(),
            ROOT / "data/cache/embeddings",
            model=store.index_config.embedding_model,
            dimension=store.index_config.dimension,
            shared_budget=budget,
        )
        stack.callback(embedder.close)
        ce = None
        if config.reranker == "crossencoder":
            ce = CrossEncoder(
                s.voyage_api_key.get_secret_value(),
                budget,
                ROOT / "data/cache/crossencoder",
                model=config.crossencoder_model,
            )
            stack.callback(ce.close)
        yield store, llm, embedder, ce


def select_context(data, plan, ranked, store, catalog, config, llm, ce, trace):
    shortlist = ranked[: config.pipeline.context_candidate_limit]
    if len(shortlist) > 80 and config.reranker == "crossencoder":
        raise PlanRejected("crossencoder_limit80")
    blocks = fetch_blocks(shortlist, store)
    grades, priorities = {}, None
    with trace.stage(
        "rerank",
        {
            "method": config.reranker,
            "candidates": len(shortlist),
            "candidate_ids": [h.chunk.id for h in shortlist],
            "need_ids": [n.id for n in plan.needs],
        },
    ) as stage:
        if config.reranker == "llm":
            candidates = candidates_for_rerank(shortlist, blocks, catalog.by_id)
            logs = ROOT / "logs/serving_rerank" / data["query_id"]
            logs.mkdir(parents=True, exist_ok=True)
            grades, event = grade_candidates(
                data["inputs"],
                plan.model_dump(mode="json"),
                candidates,
                llm,
                ROOT / "data/cache/rerank",
                logs,
            )
        elif config.reranker == "crossencoder":
            query = json.dumps(
                {
                    "question": data["inputs"]["original_question"],
                    "reading_context": data["inputs"]["reading_context"],
                    "confirmed_context": data["inputs"]["confirmed_context"],
                    "as_of": data["inputs"]["as_of"],
                },
                ensure_ascii=False,
            )
            scores, event = ce.rank(query, [h.chunk.embedding_text for h in shortlist])
            priorities = {h.chunk.id: scores[i] for i, h in enumerate(shortlist)}
        else:
            priorities = {h.chunk.id: -i for i, h in enumerate(shortlist)}
            event = {"method": "coarse_order_only"}
        if priorities is not None:
            grades = {h.chunk.id: {"s": 1, "n": [], "l": []} for h in shortlist}
        stage["outputs"] = {
            "event": event,
            "scores": priorities if priorities is not None else grades,
        }
    with trace.stage(
        "context_build",
        {
            "evidence_cap": config.evidence_tokens,
            "prompt_cap": config.full_prompt_tokens,
            "candidate_ids": [h.chunk.id for h in shortlist],
        },
    ) as stage:
        selected, texts, evidence, metadata = select_reranked(
            shortlist,
            grades,
            blocks,
            store,
            catalog.by_id,
            config.pipeline,
            data,
            config.evidence_tokens,
            config.full_prompt_tokens,
            priority_scores=priorities,
            max_items=config.max_context_items,
        )
        stage["outputs"] = {**metadata, "evidence": evidence}
    return selected, texts, evidence, metadata


def execute(
    request,
    config,
    store,
    llm,
    embedder,
    ce=None,
    *,
    query_id=None,
    do_generate=True,
    on_event=None,
):
    qid = query_id or uuid4().hex
    inputs = {
        "original_question": request.question,
        "reading_context": request.reading_context,
        "confirmed_context": request.confirmed_context,
        "as_of": str(request.as_of),
    }
    trace = Trace(qid, inputs, on_event=on_event)
    data = trace.data
    data.update(
        pipeline="serving-v1",
        config=config.model_dump(),
        index_id=config_id(store.index_config),
        created_at=datetime.now(UTC).isoformat(),
    )
    model = TracedModel(llm, trace)
    try:
        with trace.stage("catalog_snapshot", {"as_of": str(request.as_of)}) as stage:
            catalog = store.catalog()
            stage["outputs"] = {
                "documents": len(catalog.filings),
                "fingerprint": digest(json.dumps(catalog.metadata(request.as_of), sort_keys=True)),
                "catalog": catalog.metadata(request.as_of),
            }
        with trace.stage("query_plan", {"request": request.model_dump(mode="json")}) as stage:
            plan, event = plan_request(
                request, catalog, config.pipeline, model, ROOT / "data/cache/plans"
            )
            stage["outputs"] = {**event, "validated_plan": plan.model_dump(mode="json")}
        data["original_plan"] = plan.model_dump(mode="json")
        if plan.action == "retrieve" and config.regroup:
            with trace.stage("evidence_regroup", {"need_ids": [n.id for n in plan.needs]}) as stage:
                plan, event = regroup(
                    plan, catalog, config.pipeline, model, ROOT / "data/cache/regroup"
                )
                stage["outputs"] = {**event, "validated_plan": plan.model_dump(mode="json")}
        data["plan"] = plan.model_dump(mode="json")
        if plan.action != "retrieve":
            data.update(status=plan.action, runtime_evidence=[])
            return data
        retriever = PlannedRetriever(store, embedder, catalog, store.index_config, config.pipeline)
        records = retriever.search(plan, config.pipeline, trace)
        data["search_records"] = records
        fusion_config = (
            config.pipeline.model_copy(update={"fts_weight": 1.0})
            if config.coarse_policy == "hybrid_replace"
            else config.pipeline
        )
        with trace.stage(
            "fusion",
            {
                "rrf_c": fusion_config.rrf_c,
                "coarse_policy": config.coarse_policy,
                "lexical_weight": fusion_config.fts_weight,
                "search_count": len(records),
            },
        ) as stage:
            ranked, provenance = rank_records(records, fusion_config)
            raw = len(ranked)
            ranked = ranked[: config.pipeline.max_unique_candidates]
            stage["outputs"] = {
                "raw_candidates": raw,
                "retained": len(ranked),
                "provenance": provenance,
                "ranked_hits": [h.model_dump() for h in ranked],
            }
        selected, _texts, evidence, meta = select_context(
            data, plan, ranked, retriever.store, catalog, config, model, ce, trace
        )
        # store arg above is EvidenceStore; no DB writes during evidence construction.
        data["runtime_evidence"] = evidence
        data["retrieval"] = {
            "candidate_hits": list(
                {h["chunk"]["id"]: h for r in records for h in r["hits"]}.values()
            ),
            "ranked_hits": [h.model_dump() for h in ranked],
            "final_hits": [h.model_dump() for h in selected],
            "metadata": meta,
        }
        data["status"] = "retrieved" if evidence else "insufficient_evidence"
        if evidence and do_generate:
            with trace.stage(
                "generation",
                {
                    "request": request.model_dump(mode="json"),
                    "evidence_ids": [e["citation"] for e in evidence],
                },
            ) as stage:
                data["generation"] = generate_answer(data, model)
                stage["outputs"] = data["generation"]
            data["status"] = "generated"
    except Exception as exc:  # noqa: BLE001 — safe API boundary, retain successful prior stages
        data.update(status="error", error=safe_failure(exc))
    return data


def query(request, config, *, do_generate=True, query_id=None, on_event=None):
    with resources(config) as (store, llm, embedder, ce):
        data = execute(
            request,
            config,
            store,
            llm,
            embedder,
            ce,
            do_generate=do_generate,
            query_id=query_id,
            on_event=on_event,
        )
    path = ROOT / "logs/serving" / f"{data['query_id']}.json"
    atomic_json(path, data)
    return data
