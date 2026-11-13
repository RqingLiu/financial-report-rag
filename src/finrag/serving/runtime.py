"""Stable CLI/API adapter; LangGraph owns query control flow."""

from contextlib import ExitStack

from finrag.agent.policy import bind_control, terminal_failure
from finrag.agent.runner import execute, finish, lifecycle, release_unused
from finrag.core.config import ROOT
from finrag.core.files import atomic_json
from finrag.serving.resources import (
    index_config,
    load_config,
    resources,
    safe_failure,
    shared_budget,
)

__all__ = [
    "execute",
    "index_config",
    "load_config",
    "query",
    "resources",
    "safe_failure",
    "shared_budget",
]


def query(request, config, *, do_generate=True, query_id=None, on_event=None, cancelled=None):
    if config.engine == "sequential":
        # Reference harness only; do not imply it offers LangGraph request controls.
        raise ValueError("serving_requires_graph_engine")
    from finrag.agent.graph import error_outcome

    trace, control = lifecycle(
        request,
        config,
        query_id=query_id,
        on_event=on_event,
        cancelled=cancelled,
        do_generate=do_generate,
    )
    data = trace.data
    with bind_control(control):
        try:
            control.check()
            with ExitStack() as stack:
                with trace.stage("resource_setup"):
                    store, llm, embedder, ce = stack.enter_context(resources(config))
                    control.check()
                data = execute(
                    request,
                    config,
                    store,
                    llm,
                    embedder,
                    ce,
                    do_generate=do_generate,
                    trace=trace,
                    control=control,
                )
            control.check()
        except Exception as exc:  # noqa: BLE001 — includes resource setup/cleanup failures
            exc = terminal_failure(exc, control)
            data.update(status="error", error=safe_failure(exc))
            finish(
                trace,
                control,
                {"outcome": error_outcome(exc)},
                data.get("agent", {}).get("transitions", []),
            )
        finally:
            prior = data.get("agent", {})
            final = release_unused(
                trace, control, {"outcome": prior.get("outcome", "dependency_failure")}
            )
            finish(trace, control, final, prior.get("transitions", []))
    path = ROOT / "logs/serving" / f"{data['query_id']}.json"
    atomic_json(path, data)
    return data
