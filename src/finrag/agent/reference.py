"""Sequential parity/rollback adapter; not the default execution engine."""

"""One bounded pipeline for real queries and the optional HTTP API; no gold imports."""

import json
from datetime import UTC, datetime
from uuid import uuid4

from finrag.agent.planner import plan_request
from finrag.agent.regroup import regroup
from finrag.answering.calculations import CALCULATION_VERSION, prepare_calculations
from finrag.answering.generation import (
    ANSWER_PROMPT,
    ANSWER_VERSION,
    PRECISION_ANSWER_PROMPT,
    PRECISION_ANSWER_VERSION,
    generate_answer,
)
from finrag.core.config import ROOT
from finrag.core.files import digest
from finrag.core.tracing import Trace
from finrag.ingestion.chunk import config_id
from finrag.providers.traced import TracedModel
from finrag.retrieval.search import PlannedRetriever, rank_records
from finrag.retrieval.selection import select_context
from finrag.serving.resources import safe_failure


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
        config=config.model_dump(mode="json"),
        index_id=config_id(store.index_config),
        created_at=datetime.now(UTC).isoformat(),
    )
    model = TracedModel(llm, trace)
    try:
        if hasattr(store, "begin_query"):
            store.begin_query()
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
            if config.calculation_tool:
                with trace.stage("calculation_prepare", {"version": CALCULATION_VERSION}) as stage:
                    data["calculation_results"], audit = prepare_calculations(
                        data,
                        model,
                        full_prompt_tokens=config.full_prompt_tokens,
                        answer_prompt=PRECISION_ANSWER_PROMPT,
                    )
                    stage["outputs"] = audit
            with trace.stage(
                "generation",
                {
                    "request": request.model_dump(mode="json"),
                    "evidence_ids": [e["citation"] for e in evidence],
                },
            ) as stage:
                data["generation"] = generate_answer(
                    data,
                    model,
                    full_prompt_tokens=config.full_prompt_tokens,
                    system_prompt=PRECISION_ANSWER_PROMPT
                    if config.calculation_tool
                    else ANSWER_PROMPT,
                    prompt_version=PRECISION_ANSWER_VERSION
                    if config.calculation_tool
                    else ANSWER_VERSION,
                )
                stage["outputs"] = data["generation"]
            data["status"] = "generated"
    except Exception as exc:  # noqa: BLE001 — safe API boundary, retain successful prior stages
        data.update(status="error", error=safe_failure(exc))
    return data
