"""One request's execution limits; the persistent provider ledger owns all money."""

import math
import time
from collections import Counter
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
    max_provider_calls: int = Field(default=64, ge=0, le=256)
    max_sql_attempts: int = Field(default=192, ge=0, le=256)
    max_schema_repairs: int = Field(default=1, ge=0, le=1)
    max_sql_retries: int = Field(default=1, ge=0, le=1)
    max_connect_retries: int = Field(default=0, ge=0, le=1)
    deadline_seconds: float | None = Field(default=180, gt=0, le=3600)
    max_request_usd: Decimal | None = Field(default=Decimal(".15"), gt=0, le=5)
    answer_headroom_usd: Decimal = Field(default=Decimal(".04"), ge=0, le=5)
    fallback: str = Field(default="evidence_only", pattern=r"^(evidence_only|none)$")


class PolicyStop(RuntimeError):
    def __init__(self, code, outcome):
        self.code, self.outcome = code, outcome
        super().__init__(code)


@dataclass
class RunControl:
    run_id: str
    policy: RunPolicy
    cancelled: Callable[[], bool] = lambda: False
    clock: Callable[[], float] = time.monotonic
    answer_expected: bool = False
    sql_limit: int | None = None
    started: float = field(init=False)
    phase: str = "resource_setup"
    node_count: int = 0
    model_calls: int = 0
    provider_calls: int = 0
    sql_attempts: int = 0
    sql_retries: int = 0
    connect_retries: int = 0
    operation_id: str = ""
    held: dict[str, Decimal] = field(default_factory=dict)
    spent: Decimal = Decimal(0)
    repairs: Counter = field(default_factory=Counter)
    providers: Counter = field(default_factory=Counter)
    headroom_id: str | None = None
    headroom_ledger: object = None
    answer_started: bool = False

    def __post_init__(self):
        self.started = self.clock()
        self.sql_limit = min(
            self.sql_limit if self.sql_limit is not None else self.policy.max_sql_attempts,
            self.policy.max_sql_attempts,
        )

    def check(self):
        if self.cancelled():
            raise PolicyStop("request_cancelled", Outcome.CANCELLED)
        if (
            self.policy.deadline_seconds is not None
            and self.clock() - self.started >= self.policy.deadline_seconds
        ):
            raise PolicyStop("request_deadline_exceeded", Outcome.TIMEOUT)

    def timeout(self, native):
        self.check()
        remaining = self.policy.deadline_seconds
        if remaining is not None:
            remaining -= self.clock() - self.started
            if remaining <= 0:
                raise PolicyStop("request_deadline_exceeded", Outcome.TIMEOUT)
        if native is None:
            return remaining
        return min(native, remaining) if remaining is not None else native

    def sql_timeout_ms(self, native):
        return max(1, math.floor(self.timeout(native / 1000) * 1000))

    def enter_node(self, name):
        self.check()
        if self.node_count >= self.policy.max_nodes:
            raise PolicyStop("node_budget_exhausted", Outcome.BUDGET)
        self.node_count += 1
        self.phase = name
        self.operation_id = f"{self.run_id}:{self.node_count}:{name}"

    def before_model(self):
        self.check()
        if self.model_calls >= self.policy.max_model_calls:
            raise PolicyStop("model_call_budget_exhausted", Outcome.BUDGET)
        self.model_calls += 1

    def check_provider(self):
        self.check()
        if self.provider_calls >= self.policy.max_provider_calls:
            raise PolicyStop("provider_call_budget_exhausted", Outcome.BUDGET)

    def provider_started(self, provider, purpose):
        self.check_provider()
        self.provider_calls += 1
        self.providers[f"{provider}:{purpose}"] += 1

    def before_sql(self):
        self.check()
        if self.sql_attempts >= self.sql_limit:
            raise PolicyStop("search_attempt_budget_exhausted", Outcome.BUDGET)
        self.sql_attempts += 1

    def sql_recovery(self):
        self.check()
        if self.sql_retries >= self.policy.max_sql_retries or self.sql_attempts >= self.sql_limit:
            return False
        self.sql_retries += 1
        return True

    def connect_recovery(self):
        self.check()
        if self.connect_retries >= self.policy.max_connect_retries:
            return False
        self.check_provider()
        self.connect_retries += 1
        return True

    def repair(self, key):
        self.check()
        if self.repairs[key] >= self.policy.max_schema_repairs:
            raise PolicyStop("schema_repair_budget_exhausted", Outcome.INVALID)
        if self.model_calls >= self.policy.max_model_calls:
            raise PolicyStop("model_call_budget_exhausted", Outcome.BUDGET)
        self.repairs[key] += 1

    def check_reservation(self, amount, *, replace=Decimal(0)):
        self.check()
        cap = self.policy.max_request_usd
        if (
            cap is not None
            and self.spent + sum(self.held.values(), Decimal(0)) - replace + amount >= cap
        ):
            raise PolicyStop("request_cost_budget_exhausted", Outcome.BUDGET)

    def reserved(self, rid, amount):
        self.held[rid] = amount

    def settled(self, rid, amount):
        if rid in self.held:
            self.held.pop(rid)
            self.spent += amount

    def release_headroom(self):
        if self.headroom_id is not None:
            self.headroom_ledger.release_policy_hold(self.headroom_id)
            self.headroom_id = None
            self.headroom_ledger = None

    def snapshot(self):
        return {
            "nodes": self.node_count,
            "model_calls": self.model_calls,
            "provider_calls": self.provider_calls,
            "provider_attempts_by_purpose": dict(self.providers),
            "sql_attempts": self.sql_attempts,
            "sql_retries": self.sql_retries,
            "connect_retries": self.connect_retries,
            "schema_repairs": dict(self.repairs),
            "paid_known_usd": str(self.spent),
            "paid_unresolved_usd": str(sum(self.held.values(), Decimal(0))),
            "policy": self.policy.model_dump(mode="json"),
        }


def current_control():
    return _ACTIVE.get()


def check_control():
    if control := current_control():
        control.check()


def claim_repair(key):
    if control := current_control():
        control.repair(key)


@contextmanager
def bind_control(control):
    token = _ACTIVE.set(control)
    try:
        yield
    finally:
        _ACTIVE.reset(token)


def terminal_failure(exc, control):
    """A stop requested during a failing tool still prevents subsequent actions."""
    if not isinstance(exc, PolicyStop):
        try:
            control.check()
        except PolicyStop as stop:
            return stop
    return exc
