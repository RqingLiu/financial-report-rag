"""Actual bounded StateGraph; no retry policies, persistence or autonomous follow-up."""

import time
from datetime import UTC, datetime
from functools import lru_cache

from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from finrag.agent import nodes
from finrag.agent.planner import PlanRejected
from finrag.agent.policy import PolicyStop, terminal_failure
from finrag.agent.state import Outcome, RunContext, RunState
from finrag.core.observations import snapshot
from finrag.providers.llm import BudgetExceeded
from finrag.serving.resources import safe_failure


def callsite_function(function):
    import hashlib
    import inspect
    from pathlib import Path

    from finrag.core.config import ROOT

    try:
        path = Path(inspect.getfile(function)).resolve()
        return {
            "path": str(path.relative_to(ROOT)),
            "function": function.__qualname__,
            "line": inspect.getsourcelines(function)[1],
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
    except (OSError, TypeError, ValueError):
        return None


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
            "started_at": datetime.now(UTC).isoformat(),
            "state_before": snapshot(state),
            "state_capture_version": 1,
            "status": "running",
        }
        ctx.transitions.append(row)
        started = time.perf_counter()
        try:
            ctx.control.enter_node(name)
            row["operation_id"] = ctx.control.operation_id
            ctx.trace.operation_id = row["operation_id"]
            row["source"] = callsite_function(function)
            ctx.trace.emit("node_started", row)
            update = function(state, runtime)
            ctx.control.check()
            row["status"] = "ok"
        except Exception as exc:  # noqa: BLE001 — single sanitized execution boundary
            exc = terminal_failure(exc, ctx.control)
            error = safe_failure(exc)
            update = {"error": error, "status": "error", "outcome": error_outcome(exc)}
            ctx.data.update(status="error", error=error)
            row.update(status="error", error=error)
        row["output"] = summary({**state, **update})
        row["duration_seconds"] = time.perf_counter() - started
        row["ended_at"] = datetime.now(UTC).isoformat()
        row["state_after"] = snapshot({**state, **update})
        row["changed_fields"] = [
            k for k in row["state_after"] if row["state_after"][k] != row["state_before"].get(k)
        ]
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
        ctx.trace.operation_id = None
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


FUNCTIONS = {
    "catalog": "catalog",
    "plan": "plan",
    "regroup": "regroup_plan",
    "retrieve": "retrieve",
    "fusion": "fuse",
    "context": "context",
    "evidence_gate": "evidence_gate",
    "calculate": "calculate",
    "answer": "answer",
    "validate": "validate",
}


@lru_cache(maxsize=1)
def build_graph():
    graph = StateGraph(RunState, context_schema=RunContext)
    for name, function in FUNCTIONS.items():
        graph.add_node(name, wrap(name, getattr(nodes, function)))
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


def workflow_view(config):
    """Graph-owned topology; no provider/DB setup."""
    descriptions = {
        "catalog": ("资料范围", "读取已发布年报，限定公开截止日。"),
        "plan": ("问题规划", "把原问转成有范围约束的需求、任务与检索查询。"),
        "regroup": ("任务重组", "可选：按证据目标重组原计划。"),
        "retrieve": ("检索", "生成query向量，按公司与财年执行数据库搜索。"),
        "fusion": ("候选融合", "融合多路排名并交错不同任务，保留有界候选。"),
        "context": ("精排与上下文", "精排Top80候选，去重并在预算内组装来源证据。"),
        "evidence_gate": ("证据检查", "判断是否有证据；不代表已验证回答正确。"),
        "calculate": ("财务计算", "可选：从证据取操作数并执行有界算术。"),
        "answer": ("生成回答", "用原问题、计划和实际证据生成带引用的答案。"),
        "validate": ("输出归类", "按已检查的结构与section状态归类；没有独立语义Judge。"),
    }
    return {
        "version": 1,
        "nodes": [
            {
                "id": name,
                "label": descriptions[name][0],
                "description": descriptions[name][1],
                "enabled": config.regroup
                if name == "regroup"
                else config.calculation_tool
                if name == "calculate"
                else True,
                "source": callsite_function(getattr(nodes, function)),
            }
            for name, function in FUNCTIONS.items()
        ],
        "edges": [
            {"source": e.source, "target": e.target, "conditional": e.conditional}
            for e in build_graph().get_graph().edges
        ],
    }
