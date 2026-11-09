"""Request-local execution guards. The persistent provider ledger remains authoritative."""

import time
from collections.abc import Callable
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field

from finrag.agent.state import Outcome

_ACTIVE: ContextVar["RunControl | None"] = ContextVar("finrag_run_control", default=None)


class RunPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    max_nodes: int = Field(default=16, ge=1, le=64)
    max_model_calls: int = Field(default=32, ge=0, le=128)
    deadline_seconds: float | None = Field(default=None, gt=0, le=3600)
    max_request_usd: Decimal | None = Field(default=None, gt=0, le=5)


class PolicyStop(RuntimeError):
    def __init__(self, code, outcome):
        self.code, self.outcome = code, outcome
        super().__init__(code)


@dataclass
class RunControl:
    run_id: str
    policy: RunPolicy
    cancelled: Callable[[], bool] = lambda: False
    started: float = field(default_factory=time.monotonic)
    node_count: int = 0
    model_calls: int = 0
    operation_id: str = ""
    held: dict[str, Decimal] = field(default_factory=dict)
    spent: Decimal = Decimal(0)

    def check(self):
        if self.cancelled():
            raise PolicyStop("request_cancelled", Outcome.CANCELLED)
        seconds = self.policy.deadline_seconds
        if seconds is not None and time.monotonic() - self.started >= seconds:
            raise PolicyStop("request_deadline_exceeded", Outcome.TIMEOUT)

    def enter_node(self, name):
        self.check()
        if self.node_count >= self.policy.max_nodes:
            raise PolicyStop("node_budget_exhausted", Outcome.BUDGET)
        self.node_count += 1
        self.operation_id = f"{self.run_id}:{self.node_count}:{name}"

    def before_model(self):
        self.check()
        if self.model_calls >= self.policy.max_model_calls:
            raise PolicyStop("model_call_budget_exhausted", Outcome.BUDGET)
        self.model_calls += 1

    def check_reservation(self, amount):
        self.check()
        cap = self.policy.max_request_usd
        if cap is not None and self.spent + sum(self.held.values(), Decimal(0)) + amount >= cap:
            raise PolicyStop("request_cost_budget_exhausted", Outcome.BUDGET)

    def reserved(self, rid, amount):
        self.held[rid] = amount

    def settled(self, rid, amount):
        if rid in self.held:
            self.held.pop(rid)
            self.spent += amount

    def snapshot(self):
        return {
            "nodes": self.node_count,
            "model_calls": self.model_calls,
            "paid_known_usd": str(self.spent),
            "paid_unresolved_usd": str(sum(self.held.values(), Decimal(0))),
            "policy": self.policy.model_dump(mode="json"),
        }


def current_control():
    return _ACTIVE.get()


@contextmanager
def bind_control(control):
    token = _ACTIVE.set(control)
    try:
        yield
    finally:
        _ACTIVE.reset(token)
