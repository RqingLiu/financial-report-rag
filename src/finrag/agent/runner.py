"""Request lifecycle and compatibility projection around the compiled graph."""

from datetime import UTC, datetime
from uuid import uuid4

from langsmith import tracing_context

from finrag.agent.policy import RunControl, bind_control, terminal_failure
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
    trace=None,
    control=None,
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

    trace, control = lifecycle(
        request,
        config,
        query_id=query_id,
        on_event=on_event,
        policy=policy,
        cancelled=cancelled,
        do_generate=do_generate,
        trace=trace,
        control=control,
    )
    qid, data = trace.data["query_id"], trace.data
    data["index_id"] = config_id(store.index_config)
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
        exc = terminal_failure(exc, control)
        data.update(status="error", error=safe_failure(exc))
        final = {"outcome": error_outcome(exc)}
    final = release_unused(trace, control, final)
    finish(trace, control, final, ctx.transitions)
    return data


def lifecycle(
    request,
    config,
    *,
    query_id=None,
    on_event=None,
    policy=None,
    cancelled=None,
    do_generate=True,
    trace=None,
    control=None,
):
    if trace is None:
        trace = Trace(
            query_id or uuid4().hex,
            {
                "original_question": request.question,
                "reading_context": request.reading_context,
                "confirmed_context": request.confirmed_context,
                "as_of": str(request.as_of),
            },
            on_event=on_event,
        )
        trace.data.update(
            pipeline="serving-v1",
            config=config.model_dump(mode="json"),
            created_at=datetime.now(UTC).isoformat(),
        )
    if control is None:
        control = RunControl(
            trace.data["run_id"],
            policy or config.run_policy,
            cancelled or (lambda: False),
            answer_expected=do_generate,
            sql_limit=config.pipeline.max_search_calls,
        )
    return trace, control


def finish(trace, control, final, transitions):
    data = trace.data
    if data.get("status") == "error":
        data.pop("fallback", None)
        # Only a fully validated successful response may occupy the user answer field.
        data.pop("generation", None)
        if (
            control.policy.fallback == "evidence_only"
            and data.get("runtime_evidence")
            and str(final.get("outcome")) not in {"cancelled", "deadline_exceeded"}
        ):
            data["fallback"] = {
                "type": "evidence_only",
                "answer_generated": False,
                "reason": str(final.get("outcome", "dependency_failure")),
                "evidence_ids": [e["citation"] for e in data["runtime_evidence"]],
            }
    data["duration_seconds"] = max(0, control.clock() - control.started)
    data["agent"] = {
        "engine": "langgraph",
        "state_version": 1,
        "outcome": str(final.get("outcome", "dependency_failure")),
        "transitions": transitions,
        "usage": control.snapshot(),
        "evidence_status": final.get(
            "evidence_status", data.get("agent", {}).get("evidence_status")
        ),
        "tools": final.get("tools", data.get("agent", {}).get("tools", [])),
    }


def release_unused(trace, control, final):
    """Ledger cleanup failure is visible; uncertain holds never disappear from accounting."""
    from finrag.agent.graph import error_outcome
    from finrag.serving.resources import safe_failure

    try:
        with bind_control(control):
            control.release_headroom()
    except Exception as exc:  # noqa: BLE001 — a ledger outage must not erase the run trace
        exc = terminal_failure(exc, control)
        error = safe_failure(exc)
        trace.data["cleanup_error"] = error
        if trace.data.get("status") != "error":
            trace.data.update(status="error", error=error)
            final = {**final, "outcome": error_outcome(exc)}
    return final
