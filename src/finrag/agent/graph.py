"""Actual bounded StateGraph; no retry policies, persistence or autonomous follow-up."""

import time
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from finrag.agent import nodes
from finrag.agent.planner import PlanRejected
from finrag.agent.policy import PolicyStop
from finrag.agent.state import Outcome, RunContext, RunState
from finrag.providers.llm import BudgetExceeded
from finrag.serving.resources import safe_failure


def error_outcome(exc):
    if isinstance(exc, PolicyStop):
        return exc.outcome
    if isinstance(exc, BudgetExceeded):
        return Outcome.BUDGET
    if isinstance(exc, PlanRejected):
        return Outcome.INVALID
    return Outcome.DEPENDENCY


def summary(state):
    return {
        "status": state.get("status", "running"),
        "needs": len(state["plan"].needs) if state.get("plan") else 0,
        "tasks": len(state["plan"].tasks) if state.get("plan") else 0,
        "searches": len(state.get("records", [])),
        "candidates": len(state.get("ranked", [])),
        "evidence": len(state.get("evidence", [])),
        "outcome": str(state["outcome"]) if state.get("outcome") else None,
    }


def wrap(name, function):
    def run(state: RunState, runtime: Runtime[RunContext]):
        ctx = runtime.context
        row = {
            "operation_id": f"{ctx.control.run_id}:attempt:{len(ctx.transitions) + 1}:{name}",
            "node": name,
            "input": summary(state),
            "status": "running",
        }
        ctx.transitions.append(row)
        started = time.perf_counter()
        try:
            ctx.control.enter_node(name)
            row["operation_id"] = ctx.control.operation_id
            ctx.trace.emit("node_started", row)
            update = function(state, runtime)
            ctx.control.check()
            row["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 — single sanitized execution boundary
            error = safe_failure(exc)
            update = {"error": error, "status": "error", "outcome": error_outcome(exc)}
            ctx.data.update(status="error", error=error)
            row.update(status="error", error=error)
        row["output"] = summary({**state, **update})
        row["duration_seconds"] = time.perf_counter() - started
        result = {
            "operation_id": row["operation_id"],
            "tool": name,
            "status": "error"
            if "error" in update
            else (
                "empty"
                if name == "retrieve" and not any(r.get("hits") for r in update.get("records", []))
                else "ok"
            ),
            "output_fields": sorted(update),
            "error": update.get("error"),
        }
        update["tools"] = [*state.get("tools", []), result]
        ctx.trace.emit("node_finished", row)
        return update

    return run


def after_plan(state: RunState, runtime: Runtime[RunContext]):
    if state.get("error") or state["plan"].action != "retrieve":
        return END
    return "regroup" if runtime.context.config.regroup else "retrieve"


def after_gate(state: RunState, runtime: Runtime[RunContext]):
    if state.get("error") or not state.get("evidence") or not runtime.context.do_generate:
        return END
    return "calculate" if runtime.context.config.calculation_tool else "answer"


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(RunState, context_schema=RunContext)
    functions = {
        "catalog": nodes.catalog,
        "plan": nodes.plan,
        "regroup": nodes.regroup_plan,
        "retrieve": nodes.retrieve,
        "fusion": nodes.fuse,
        "context": nodes.context,
        "evidence_gate": nodes.evidence_gate,
        "calculate": nodes.calculate,
        "answer": nodes.answer,
        "validate": nodes.validate,
    }
    for name, function in functions.items():
        graph.add_node(name, wrap(name, function))
    graph.add_edge(START, "catalog")
    graph.add_conditional_edges(
        "catalog", lambda s: END if s.get("error") else "plan", [END, "plan"]
    )
    graph.add_conditional_edges("plan", after_plan, [END, "regroup", "retrieve"])
    for source, dest in [
        ("regroup", "retrieve"),
        ("retrieve", "fusion"),
        ("fusion", "context"),
        ("context", "evidence_gate"),
        ("calculate", "answer"),
        ("answer", "validate"),
    ]:
        graph.add_conditional_edges(
            source, lambda s, dest=dest: END if s.get("error") else dest, [END, dest]
        )
    graph.add_conditional_edges("evidence_gate", after_gate, [END, "calculate", "answer"])
    graph.add_edge("validate", END)
    return graph.compile(name="finrag")
