"""Fault-injected request controls: no network, credentials, or live database required."""

import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from decimal import Decimal
from threading import Event
from types import SimpleNamespace

import httpx
import psycopg
import pytest
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from test_agent_graph import setup_receipts

from finrag.agent.planner import PipelineConfig, PlanRejected, Request, plan_request
from finrag.agent.policy import PolicyStop, RunControl, RunPolicy, bind_control
from finrag.agent.runner import execute, lifecycle
from finrag.core.tracing import Trace
from finrag.providers.llm import Budget, BudgetExceeded, DeepSeek, ProviderFailure, budget_scope
from finrag.providers.traced import TracedModel
from finrag.retrieval.store import LiveStore
from finrag.serving import runtime
from finrag.serving.api import create_app
from finrag.serving.config import ServingConfig


class Clock:
    now = 0

    def __call__(self):
        return self.now


def response(answer="{}"):
    return httpx.Response(
        200,
        json={
            "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
            "choices": [{"message": {"content": answer}, "finish_reason": "stop"}],
        },
    )


def test_deadline_is_monotonic_and_clamps_native_timeout():
    clock = Clock()
    control = RunControl("run", RunPolicy(deadline_seconds=3), clock=clock)
    clock.now = 2.5
    assert control.timeout(60) == 0.5
    assert control.sql_timeout_ms(5000) == 500
    clock.now = 3
    with pytest.raises(PolicyStop, match="deadline"):
        control.before_model()
    assert control.model_calls == 0


@pytest.mark.parametrize("failure", ["cancel", "deadline"])
def test_late_provider_response_is_settled_but_not_delivered(tmp_path, failure):
    clock, cancel, seen = Clock(), Event(), []
    control = RunControl("run", RunPolicy(deadline_seconds=2), cancel.is_set, clock)
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")

    def respond(req):
        seen.append(req.extensions["timeout"])
        if failure == "cancel":
            cancel.set()
        else:
            clock.now = 3
        return response()

    model = DeepSeek("FAKE", ledger, transport=httpx.MockTransport(respond))
    trace = Trace("q", {})
    try:
        with bind_control(control), pytest.raises(PolicyStop):
            TracedModel(model, trace).generate([{"role": "user", "content": "hi"}])
    finally:
        model.close()
    assert len(seen) == control.provider_calls == control.model_calls == 1
    assert all(t == 2 for t in seen[0].values())
    assert not ledger.snapshot()["unresolved_requests"]
    assert Decimal(ledger.snapshot()["known_peak_list_cost_usd"]) > 0
    assert trace.data["stages"][0]["status"] == "error"
    assert trace.data["stages"][0]["outputs"]["usage"]["total_tokens"] == 25
    with bind_control(control), pytest.raises(PolicyStop):
        ledger.reserve(".01", "fake", "later")


def test_headroom_is_atomic_persistent_and_replaced_for_answer(tmp_path):
    ledger = Budget(tmp_path / "ledger.jsonl", ".3")
    c = RunControl(
        "one", RunPolicy(max_request_usd=".2", answer_headroom_usd=".08"), answer_expected=True
    )
    with bind_control(c):
        c.enter_node("context")
        rid = ledger.reserve(".03", "fake", "rerank")
        assert Decimal(ledger.snapshot()["unresolved_reserved_usd"]) == Decimal(".11")
        # A separate process/client observes the hold in the original ledger.
        with bind_control(None), pytest.raises(BudgetExceeded):
            Budget(ledger.path, ".3").reserve(".20", "fake", "other_run")
        ledger.settle(rid, ".01", {})
        c.enter_node("answer")
        answer_id = ledger.reserve(".06", "fake", "answer")
        assert c.headroom_id is None
        assert Decimal(ledger.snapshot()["unresolved_reserved_usd"]) == Decimal(".06")
        ledger.settle(answer_id, ".02", {})
        c.release_headroom()
    assert c.spent == Decimal(".03") and not c.held
    rows = [json.loads(s) for s in ledger.path.read_text().splitlines()]
    assert len([r for r in rows if r.get("purpose") == "answer_headroom"]) == 1


def test_concurrent_headroom_cannot_overspend_shared_ledger(tmp_path):
    path = tmp_path / "ledger.jsonl"

    def attempt(i):
        c = RunControl(
            str(i), RunPolicy(max_request_usd=".2", answer_headroom_usd=".06"), answer_expected=True
        )
        with bind_control(c):
            try:
                Budget(path, ".15").reserve(".03", "fake", "rerank")
                return True
            except BudgetExceeded:
                return False

    with ThreadPoolExecutor(2) as pool:
        assert sum(pool.map(attempt, range(2))) == 1
    assert Decimal(Budget(path, ".15").snapshot()["unresolved_reserved_usd"]) == Decimal(".09")


def test_finish_releases_only_unused_policy_hold_not_uncertain_call(tmp_path):
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    c = RunControl("one", RunPolicy(), answer_expected=True)
    with bind_control(c):
        rid = ledger.reserve(".01", "fake", "query_plan")
        c.release_headroom()
    assert list(c.held) == [rid]
    assert ledger.snapshot()["unresolved_requests"] == [rid]
    with pytest.raises(ValueError, match="not_a_policy_hold"):
        ledger.release_policy_hold(rid)


def test_request_or_batch_preflight_writes_no_partial_policy_hold(tmp_path):
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    c = RunControl(
        "one", RunPolicy(max_request_usd=".05", answer_headroom_usd=".04"), answer_expected=True
    )
    with bind_control(c), pytest.raises(PolicyStop, match="request_cost"):
        ledger.reserve(".02", "fake", "planner")
    assert not ledger.snapshot()["unresolved_requests"] and not c.held
    c = RunControl("two", RunPolicy(), answer_expected=True)
    with budget_scope("batch", ".05"), bind_control(c), pytest.raises(BudgetExceeded):
        ledger.reserve(".02", "fake", "planner")
    assert not ledger.snapshot()["unresolved_requests"] and not c.held


def test_batch_resume_counts_spend_unknown_holds_and_preserves_limit(tmp_path):
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    with budget_scope("batch", ".1"):
        rid = ledger.reserve(".05", "fake", "first")
        ledger.settle(rid, ".02", {})
        ledger.reserve(".04", "fake", "uncertain")
    with budget_scope("batch", ".1"), pytest.raises(BudgetExceeded):
        Budget(ledger.path, ".5").reserve(".04", "fake", "resume")
    with budget_scope("batch", ".2"), pytest.raises(ValueError, match="batch_budget_changed"):
        ledger.reserve(".01", "fake", "silent_raise")
    with budget_scope("another_batch", ".1"):
        ledger.reserve(".01", "fake", "independent")


@pytest.mark.parametrize("mode,expected", [("connect", 2), ("read", 1), ("http", 1)])
def test_only_known_unsubmitted_connection_can_retry(tmp_path, mode, expected):
    calls = []

    def respond(req):
        calls.append(req)
        if mode == "connect" and len(calls) == 1:
            raise httpx.ConnectError("PRIVATE", request=req)
        if mode == "read":
            raise httpx.ReadTimeout("PRIVATE", request=req)
        if mode == "http":
            return httpx.Response(429, json={"secret": "PRIVATE"})
        return response()

    c = RunControl("one", RunPolicy(max_connect_retries=1))
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    model = DeepSeek("FAKE", ledger, transport=httpx.MockTransport(respond))
    try:
        with bind_control(c):
            if mode == "connect":
                model.generate([{"role": "user", "content": "hi"}])
            else:
                with pytest.raises(ProviderFailure):
                    model.generate([{"role": "user", "content": "hi"}])
    finally:
        model.close()
    assert len(calls) == c.provider_calls == expected
    assert c.connect_retries == (1 if mode == "connect" else 0)
    assert bool(ledger.snapshot()["unresolved_requests"]) == (mode != "connect")
    assert "PRIVATE" not in ledger.path.read_text()


def test_provider_cap_blocks_before_reservation_or_http(tmp_path):
    c = RunControl("one", RunPolicy(max_provider_calls=0))
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    model = DeepSeek("FAKE", ledger, transport=httpx.MockTransport(lambda _: pytest.fail("HTTP")))
    try:
        with bind_control(c), pytest.raises(PolicyStop, match="provider_call"):
            model.generate([{"role": "user", "content": "hi"}])
    finally:
        model.close()
    assert not ledger.snapshot()["unresolved_requests"]


@pytest.mark.parametrize("repairs,expected", [(0, 1), (1, 2)])
def test_real_planner_repair_loop_respects_shared_policy(monkeypatch, tmp_path, repairs, expected):
    req, store, _ = setup_receipts(monkeypatch, tmp_path)
    calls = []

    class Invalid:
        def generate(self, *args, **kwargs):
            calls.append(1)
            return {"answer": "{}", "finish_reason": "stop"}

    c = RunControl("one", RunPolicy(max_schema_repairs=repairs))
    with bind_control(c), pytest.raises((PlanRejected, PolicyStop)):
        plan_request(
            req,
            store.catalog(),
            PipelineConfig(),
            TracedModel(Invalid(), Trace("q", {})),
            tmp_path / "plans",
        )
    assert len(calls) == c.model_calls == expected
    assert c.repairs["planner"] == repairs


class StatementTimeout(psycopg.errors.QueryCanceled):
    @property
    def diag(self):
        return SimpleNamespace(message_primary="canceling statement due to statement timeout")


@pytest.mark.parametrize(
    "mode,attempts,retries",
    [("recover", 2, 1), ("cap", 1, 0), ("cancel", 1, 0), ("deadline", 1, 0)],
)
def test_sql_recovery_inherits_attempt_deadline_and_cancel_limits(mode, attempts, retries):
    clock, cancel = Clock(), Event()
    c = RunControl(
        "one",
        RunPolicy(max_sql_attempts=1 if mode == "cap" else 3, deadline_seconds=2),
        cancel.is_set,
        clock,
    )
    store = LiveStore.__new__(LiveStore)
    store.config = ServingConfig()
    store.begin_query()
    calls = []

    def search_once(*args, **kwargs):
        calls.append(1)
        if len(calls) > 1:
            return []
        if mode == "cancel":
            cancel.set()
        if mode == "deadline":
            clock.now = 3
        raise StatementTimeout()

    store._search_once = search_once
    with bind_control(c):
        if mode == "recover":
            assert store.search() == []
        else:
            with pytest.raises((PolicyStop, psycopg.errors.QueryCanceled)):
                store.search()
    assert len(calls) == c.sql_attempts == attempts
    assert c.sql_retries == retries
    assert store.search_diagnostics[0]["status"] == "statement_timeout"


@pytest.mark.parametrize("mode", ["setup", "cancel_before_setup", "cancel_during_setup"])
def test_full_request_captures_resource_failures_and_cleans_up(monkeypatch, tmp_path, mode):
    req, store, model = setup_receipts(monkeypatch, tmp_path)
    cancel, events = Event(), []
    monkeypatch.setattr(runtime, "ROOT", tmp_path)

    @contextmanager
    def resources(config):
        events.append("open")
        if mode == "setup":
            raise RuntimeError("PRIVATE database credentials")
        try:
            cancel.set()
            yield store, model(), None, None
        finally:
            events.append("closed")

    monkeypatch.setattr(runtime, "resources", resources)
    if mode == "cancel_before_setup":
        cancel.set()
    result = runtime.query(req, ServingConfig(), query_id="q", cancelled=cancel.is_set)
    assert result["status"] == "error"
    assert result["agent"]["outcome"] == ("dependency_failure" if mode == "setup" else "cancelled")
    assert result["agent"]["usage"]["model_calls"] == 0
    assert "PRIVATE" not in json.dumps(result)
    if mode == "cancel_before_setup":
        assert not events
    elif mode == "cancel_during_setup":
        assert events == ["open", "closed"]
    assert json.loads((tmp_path / "logs/serving/q.json").read_text())["agent"] == result["agent"]


@pytest.mark.parametrize("fallback", ["evidence_only", "none"])
def test_generation_failure_is_visible_without_delivering_invalid_answer(
    monkeypatch, tmp_path, fallback
):
    req, store, _ = setup_receipts(monkeypatch, tmp_path)
    calls = []

    class Invalid:
        def generate(self, *args, **kwargs):
            calls.append(1)
            return {"answer": "{}", "finish_reason": "stop"}

    result = execute(
        req, ServingConfig(), store, Invalid(), None, policy=RunPolicy(fallback=fallback)
    )
    assert len(calls) == 2 and result["agent"]["outcome"] == "invalid_result"
    assert "generation" not in result
    assert len(result["runtime_evidence"]) == 1
    assert ("fallback" in result) == (fallback == "evidence_only")
    if fallback == "evidence_only":
        assert result["fallback"]["answer_generated"] is False
        assert result["fallback"]["evidence_ids"] == ["E1"]


def test_cancel_after_node_output_removes_answer_from_delivery(monkeypatch, tmp_path):
    from finrag.agent import nodes

    req, store, model = setup_receipts(monkeypatch, tmp_path)
    cancel = Event()
    original = nodes.answer

    def cancelled_answer(*args):
        result = original(*args)
        cancel.set()
        return result

    # The compiled graph retains nodes, so invalidate only this test's cached graph.
    from finrag.agent.graph import build_graph

    monkeypatch.setattr(nodes, "answer", cancelled_answer)
    build_graph.cache_clear()
    try:
        result = execute(req, ServingConfig(), store, model(), None, cancelled=cancel.is_set)
    finally:
        build_graph.cache_clear()
    assert result["agent"]["outcome"] == "cancelled"
    assert "generation" not in result and "fallback" not in result


def test_stream_disconnect_signals_cancel_without_freeing_busy_worker(monkeypatch):
    started, release, signals = Event(), Event(), []

    def slow(*args, cancelled, query_id, **kwargs):
        signals.append(cancelled)
        started.set()
        assert release.wait(5)
        return {"query_id": query_id, "status": "error", "stages": []}

    monkeypatch.setattr("finrag.serving.api.query", slow)

    async def scenario():
        app = create_app(ServingConfig(max_inflight=1))
        stream = next(r.endpoint for r in app.routes if r.path == "/query/stream")
        cancel = next(r.endpoint for r in app.routes if r.path == "/queries/{query_id}/cancel")
        req = Request(question="q", as_of="2025-01-01")
        response = await stream(req)
        iterator = response.body_iterator
        accepted = await anext(iterator)
        qid = json.loads(accepted.split("data: ")[1])["query_id"]
        assert await run_in_threadpool(started.wait, 3)
        assert (await cancel(qid))["status"] == "cancellation_requested"
        assert signals[0]()
        await iterator.aclose()
        try:
            with pytest.raises(HTTPException) as err:
                await stream(req)
            assert err.value.status_code == 429
            assert qid in app.state.cancellations
        finally:
            release.set()
            await asyncio.gather(*app.state.workers)
        assert not app.state.cancellations
        with pytest.raises(HTTPException) as err:
            await cancel(qid)
        assert err.value.status_code == 404
        with app.state.admission.enter():
            pass

    asyncio.run(scenario())


@pytest.mark.parametrize("mode", ["cancel", "deadline"])
def test_unknown_billing_at_stop_remains_held_in_graph(tmp_path, monkeypatch, mode):
    req, store, _ = setup_receipts(monkeypatch, tmp_path)
    clock, cancel, calls = Clock(), Event(), []
    cfg = ServingConfig(run_policy=RunPolicy(deadline_seconds=2))
    trace, control = lifecycle(req, cfg, cancelled=cancel.is_set)
    control.clock, control.started = clock, 0
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")

    def fail(req):
        calls.append(1)
        if mode == "cancel":
            cancel.set()
        else:
            clock.now = 3
        raise httpx.ReadTimeout("PRIVATE", request=req)

    model = DeepSeek("FAKE", ledger, transport=httpx.MockTransport(fail))
    try:
        result = execute(req, cfg, store, model, None, trace=trace, control=control)
    finally:
        model.close()
    assert result["agent"]["outcome"] == ("cancelled" if mode == "cancel" else "deadline_exceeded")
    assert "generation" not in result and "fallback" not in result and len(calls) == 1
    assert len(ledger.snapshot()["unresolved_requests"]) == 1
    assert result["agent"]["usage"]["paid_unresolved_usd"] != "0"
    assert "PRIVATE" not in json.dumps(result)


def test_cancel_between_reservation_and_submission_releases_only_unsubmitted_cost(tmp_path):
    cancel = Event()
    control = RunControl("one", RunPolicy(), cancel.is_set, answer_expected=True)

    class InterruptedBudget(Budget):
        def reserve(self, *args):
            rid = super().reserve(*args)
            cancel.set()
            return rid

    ledger = InterruptedBudget(tmp_path / "ledger.jsonl", ".5")
    model = DeepSeek("FAKE", ledger, transport=httpx.MockTransport(lambda _: pytest.fail("HTTP")))
    try:
        with bind_control(control), pytest.raises(PolicyStop):
            model.generate([{"role": "user", "content": "hi"}])
    finally:
        with bind_control(control):
            control.release_headroom()
        model.close()
    assert control.provider_calls == 0 and not ledger.snapshot()["unresolved_requests"]
    assert control.spent == 0


def test_cached_embedding_is_free_and_honors_cancellation(tmp_path):
    from finrag.core.files import atomic_json
    from finrag.providers.voyage import DocumentEmbedder

    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    embedder = DocumentEmbedder("FAKE", tmp_path / "cache", shared_budget=ledger)
    text = "Revenue?"
    vector = [1.0] + [0.0] * (embedder.dimension - 1)
    atomic_json(embedder.cache_dir / (embedder._key(text, "query") + ".json"), vector)
    c = RunControl("one", RunPolicy(max_provider_calls=0))
    try:
        with bind_control(c):
            assert embedder.embed([text], "query") == [vector]
        cancel = RunControl("two", RunPolicy(), lambda: True)
        with bind_control(cancel), pytest.raises(PolicyStop):
            embedder.embed([text], "query")
    finally:
        embedder.close()
    assert c.provider_calls == 0 and not ledger.snapshot()["unresolved_requests"]


def test_sql_native_timeout_uses_remaining_request_time():
    from contextlib import nullcontext

    from psycopg import sql

    clock = Clock()
    c = RunControl("one", RunPolicy(deadline_seconds=3), clock=clock)
    clock.now = 1.7
    seen = []

    class Connection:
        def transaction(self):
            return nullcontext()

        def execute(self, query, params=None):
            seen.append((query, params))
            return self

        def fetchall(self):
            return []

    store = LiveStore.__new__(LiveStore)
    store.config = ServingConfig(lexical="fts")
    store.index_id, store.ns, store.connection = "fixture", sql.Identifier("fixture"), Connection()
    store.begin_query()
    with bind_control(c):
        assert store.search("fixture", ["doc"], "2026-01-01", 20, query="revenue") == []
    assert seen[0][1] == ("1300",)
    assert c.sql_attempts == 1


def test_connection_closed_if_session_setup_fails(monkeypatch):
    from finrag.core.models import IndexConfig

    closed = []

    class Connection:
        def execute(self, *args):
            raise RuntimeError("PRIVATE")

        def close(self):
            closed.append(True)

    monkeypatch.setattr("finrag.retrieval.store.psycopg.connect", lambda *_, **__: Connection())
    with pytest.raises(RuntimeError):
        LiveStore("fake", ServingConfig(), IndexConfig(name="fixture", chunk_size=128, overlap=0))
    assert closed == [True]


def test_cli_ctrl_c_propagates_event_and_restores_signal_handler(monkeypatch):
    import signal
    import sys

    from finrag.serving import cli

    previous = signal.getsignal(signal.SIGINT)
    monkeypatch.setattr(sys, "argv", ["fr-rag", "query", "hi", "--as-of", "2026-01-01"])
    monkeypatch.setattr(cli, "load_config", lambda _: ServingConfig())

    def query(*args, cancelled, **kwargs):
        assert not cancelled()
        signal.raise_signal(signal.SIGINT)
        assert cancelled()
        return {"status": "error", "agent": {"outcome": "cancelled"}}

    monkeypatch.setattr(cli, "query", query)
    with pytest.raises(SystemExit) as err:
        cli.main()
    assert err.value.code == 1
    assert signal.getsignal(signal.SIGINT) is previous


def test_ledger_cleanup_failure_keeps_receipt_hold_and_rejects_delivery(monkeypatch, tmp_path):
    from finrag.agent import nodes
    from finrag.agent.policy import current_control

    req, store, model = setup_receipts(monkeypatch, tmp_path)
    ledger = Budget(tmp_path / "ledger.jsonl", ".5")
    planner = nodes.plan_request

    def reserve_then_plan(*args):
        rid = ledger.reserve(".001", "fake", "planner")
        ledger.settle(rid, "0", {})
        assert current_control().headroom_id is not None
        return planner(*args)

    def unavailable(*args):
        raise OSError("PRIVATE")

    monkeypatch.setattr(nodes, "plan_request", reserve_then_plan)
    monkeypatch.setattr(ledger, "release_policy_hold", unavailable)
    result = execute(req, ServingConfig(), store, model(), None)
    assert result["agent"]["outcome"] == "dependency_failure"
    assert "generation" not in result and "PRIVATE" not in json.dumps(result)
    assert result["cleanup_error"]["type"] == "OSError"
    assert Decimal(ledger.snapshot()["unresolved_reserved_usd"]) == Decimal(".04")
