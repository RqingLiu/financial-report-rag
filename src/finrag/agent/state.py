"""Per-run business state; live clients and credentials belong in RunContext."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Literal, TypedDict

from finrag.agent.planner import Plan, Request
from finrag.core.models import Hit


class Outcome(StrEnum):
    ANSWERED = "answered"
    PARTIAL = "partial_answer"
    RETRIEVED = "retrieved"
    CLARIFY = "clarification_required"
    INSUFFICIENT = "insufficient_evidence"
    DEPENDENCY = "dependency_failure"
    INVALID = "invalid_result"
    BUDGET = "budget_exhausted"
    CANCELLED = "cancelled"
    TIMEOUT = "deadline_exceeded"


class ToolResult(TypedDict):
    operation_id: str
    tool: str
    status: Literal["ok", "empty", "error"]
    output_fields: list[str]
    error: dict[str, str] | None


class RunState(TypedDict, total=False):
    query_id: str
    request: Request
    original_plan: Plan
    plan: Plan
    catalog_fingerprint: str
    records: list[dict]
    ranked: list[Hit]
    selected: list[Hit]
    evidence: list[dict]
    context_metadata: dict
    evidence_status: Literal["available_unverified", "empty"]
    generation: dict
    calculation_results: dict
    status: str
    outcome: Outcome
    error: dict[str, str]
    tools: list[ToolResult]


@dataclass
class RunContext:
    """Request-local dependency injection; never placed in graph state/checkpoints."""

    config: Any
    store: Any
    model: Any
    embedder: Any
    ce: Any
    trace: Any
    control: Any
    do_generate: bool = True
    catalog: Any = None
    retriever: Any = None
    transitions: list[dict] = field(default_factory=list)

    @property
    def data(self):
        return self.trace.data
