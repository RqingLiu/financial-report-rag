"""Stage adapters reuse existing algorithms; nodes return typed business-state updates."""

import json

from langgraph.runtime import Runtime

from finrag.agent.planner import plan_request
from finrag.agent.regroup import regroup
from finrag.agent.state import Outcome, RunContext, RunState
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
from finrag.retrieval.search import PlannedRetriever, rank_records
from finrag.retrieval.selection import select_context


def catalog(state: RunState, runtime: Runtime[RunContext]):
    ctx, request = runtime.context, state["request"]
    if hasattr(ctx.store, "begin_query"):
        ctx.store.begin_query()
    with ctx.trace.stage("catalog_snapshot", {"as_of": str(request.as_of)}) as stage:
        ctx.catalog = ctx.store.catalog()
        snapshot = ctx.catalog.metadata(request.as_of)
        fingerprint = digest(json.dumps(snapshot, sort_keys=True))
        stage["outputs"] = {
            "documents": len(ctx.catalog.filings),
            "fingerprint": fingerprint,
            "catalog": snapshot,
        }
    return {"catalog_fingerprint": fingerprint}


def plan(state: RunState, runtime: Runtime[RunContext]):
    ctx, request = runtime.context, state["request"]
    with ctx.trace.stage("query_plan", {"request": request.model_dump(mode="json")}) as stage:
        result, event = plan_request(
            request, ctx.catalog, ctx.config.pipeline, ctx.model, ROOT / "data/cache/plans"
        )
        stage["outputs"] = {**event, "validated_plan": result.model_dump(mode="json")}
    ctx.data["original_plan"] = result.model_dump(mode="json")
    ctx.data["plan"] = result.model_dump(mode="json")
    update = {"original_plan": result, "plan": result}
    if result.action != "retrieve":
        ctx.data.update(status=result.action, runtime_evidence=[])
        update.update(
            status=result.action,
            outcome=Outcome.CLARIFY if result.action == "clarify" else Outcome.INSUFFICIENT,
        )
    return update


def regroup_plan(state: RunState, runtime: Runtime[RunContext]):
    ctx, result = runtime.context, state["plan"]
    with ctx.trace.stage("evidence_regroup", {"need_ids": [n.id for n in result.needs]}) as stage:
        result, event = regroup(
            result, ctx.catalog, ctx.config.pipeline, ctx.model, ROOT / "data/cache/regroup"
        )
        stage["outputs"] = {**event, "validated_plan": result.model_dump(mode="json")}
    ctx.data["plan"] = result.model_dump(mode="json")
    return {"plan": result}


def retrieve(state: RunState, runtime: Runtime[RunContext]):
    ctx = runtime.context
    ctx.retriever = PlannedRetriever(
        ctx.store, ctx.embedder, ctx.catalog, ctx.store.index_config, ctx.config.pipeline
    )
    records = ctx.retriever.search(state["plan"], ctx.config.pipeline, ctx.trace)
    ctx.data["search_records"] = records
    return {"records": records}


def fuse(state: RunState, runtime: Runtime[RunContext]):
    ctx, records = runtime.context, state["records"]
    config = (
        ctx.config.pipeline.model_copy(update={"fts_weight": 1.0})
        if ctx.config.coarse_policy == "hybrid_replace"
        else ctx.config.pipeline
    )
    with ctx.trace.stage(
        "fusion",
        {
            "rrf_c": config.rrf_c,
            "coarse_policy": ctx.config.coarse_policy,
            "lexical_weight": config.fts_weight,
            "search_count": len(records),
        },
    ) as stage:
        ranked, provenance = rank_records(records, config)
        raw = len(ranked)
        ranked = ranked[: ctx.config.pipeline.max_unique_candidates]
        stage["outputs"] = {
            "raw_candidates": raw,
            "retained": len(ranked),
            "provenance": provenance,
            "ranked_hits": [h.model_dump() for h in ranked],
        }
    return {"ranked": ranked}


def context(state: RunState, runtime: Runtime[RunContext]):
    ctx = runtime.context
    selected, _texts, evidence, meta = select_context(
        ctx.data,
        state["plan"],
        state["ranked"],
        ctx.retriever.store,
        ctx.catalog,
        ctx.config,
        ctx.model,
        ctx.ce,
        ctx.trace,
    )
    ctx.data["runtime_evidence"] = evidence
    ctx.data["retrieval"] = {
        "candidate_hits": list(
            {h["chunk"]["id"]: h for r in state["records"] for h in r["hits"]}.values()
        ),
        "ranked_hits": [h.model_dump() for h in state["ranked"]],
        "final_hits": [h.model_dump() for h in selected],
        "metadata": meta,
    }
    status = "retrieved" if evidence else "insufficient_evidence"
    ctx.data["status"] = status
    return {"selected": selected, "evidence": evidence, "context_metadata": meta, "status": status}


def evidence_gate(state: RunState, runtime: Runtime[RunContext]):
    # Availability is deliberately not a claim of semantic sufficiency.
    if not state["evidence"]:
        return {"evidence_status": "empty", "outcome": Outcome.INSUFFICIENT}
    return {"evidence_status": "available_unverified", "outcome": Outcome.RETRIEVED}


def calculate(state: RunState, runtime: Runtime[RunContext]):
    ctx = runtime.context
    with ctx.trace.stage("calculation_prepare", {"version": CALCULATION_VERSION}) as stage:
        result, audit = prepare_calculations(
            ctx.data,
            ctx.model,
            full_prompt_tokens=ctx.config.full_prompt_tokens,
            answer_prompt=PRECISION_ANSWER_PROMPT,
        )
        ctx.data["calculation_results"] = result
        stage["outputs"] = audit
    return {"calculation_results": result}


def answer(state: RunState, runtime: Runtime[RunContext]):
    ctx, request = runtime.context, state["request"]
    with ctx.trace.stage(
        "generation",
        {
            "request": request.model_dump(mode="json"),
            "evidence_ids": [e["citation"] for e in state["evidence"]],
        },
    ) as stage:
        result = generate_answer(
            ctx.data,
            ctx.model,
            full_prompt_tokens=ctx.config.full_prompt_tokens,
            system_prompt=PRECISION_ANSWER_PROMPT if ctx.config.calculation_tool else ANSWER_PROMPT,
            prompt_version=PRECISION_ANSWER_VERSION
            if ctx.config.calculation_tool
            else ANSWER_VERSION,
        )
        stage["outputs"] = result
        ctx.data["generation"] = result
    ctx.data["status"] = "generated"
    return {"generation": result, "status": "generated"}


def validate(state: RunState, runtime: Runtime[RunContext]):
    # generate_answer already enforces shape and citation IDs. Do not add a new judge.
    sections = state["generation"].get("structured_answer", {}).get("sections", [])
    partial = any(s["status"] != "supported" for s in sections)
    return {"outcome": Outcome.PARTIAL if partial else Outcome.ANSWERED}
