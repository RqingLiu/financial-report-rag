"""Request lifecycle and compatibility projection around the compiled graph."""

from datetime import UTC, datetime
from uuid import uuid4

from langsmith import tracing_context

from finrag.agent.policy import RunControl, bind_control
from finrag.agent.state import RunContext
from finrag.core.tracing import Trace
from finrag.ingestion.chunk import config_id
from finrag.providers.traced import TracedModel


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
    policy=None,
    cancelled=None,
):
    if config.engine == "sequential":
        from finrag.agent.reference import execute as sequential

        if policy is not None or cancelled is not None:
            raise ValueError("request_policy_requires_graph_engine")
        return sequential(
            request,
            config,
            store,
            llm,
            embedder,
            ce,
            query_id=query_id,
            do_generate=do_generate,
            on_event=on_event,
        )
    from finrag.agent.graph import build_graph, error_outcome
    from finrag.serving.resources import safe_failure

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
    control = RunControl(data["run_id"], policy or config.run_policy, cancelled or (lambda: False))
    ctx = RunContext(
        config, store, TracedModel(llm, trace), embedder, ce, trace, control, do_generate
    )
    final = {}
    try:
        with tracing_context(enabled=False), bind_control(control):
            final = build_graph().invoke(
                {"request": request, "query_id": qid, "tools": []},
                config={"recursion_limit": control.policy.max_nodes + 2},
                context=ctx,
            )
    except Exception as exc:  # noqa: BLE001 — sanitized adapter boundary; never retry graph
        data.update(status="error", error=safe_failure(exc))
        final = {"outcome": error_outcome(exc)}
    data["agent"] = {
        "engine": "langgraph",
        "state_version": 1,
        "outcome": str(final.get("outcome", "dependency_failure")),
        "transitions": ctx.transitions,
        "usage": control.snapshot(),
        "evidence_status": final.get("evidence_status"),
        "tools": final.get("tools", []),
    }
    return data
