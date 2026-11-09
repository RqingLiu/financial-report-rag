"""Graph parity uses deterministic receipts, never paid calls or claimed financial scores."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finrag.agent import nodes, reference
from finrag.agent.graph import build_graph
from finrag.agent.planner import Catalog, Plan, PlanRejected, Request
from finrag.agent.policy import RunPolicy
from finrag.agent.runner import execute
from finrag.core.models import Chunk, Filing, Hit, IndexConfig
from finrag.providers.llm import Budget, BudgetExceeded
from finrag.serving.config import ServingConfig


def setup_receipts(monkeypatch, tmp_path, *, action="retrieve", evidence=True, failure=None):
    from finrag.agent.planner import Need, Task

    f = Filing(
        id="ACME2025",
        ticker="ACME",
        cik=123,
        fiscal_year=2025,
        form="10-K",
        accession="acme",
        period_end="2025-12-31",
        filed_at="2026-02-01",
        source_url="https://example.test/10k",
    )
    store = SimpleNamespace(
        index_config=IndexConfig(name="fixture", chunk_size=128, overlap=0),
        catalog=lambda: Catalog([f]),
    )
    c = Chunk(
        id="c1",
        document_id=f.id,
        index_id="ix",
        section="Item 7",
        text="Revenue 100",
        embedding_text="Revenue 100",
        tokens=3,
        spans=[],
        block_ids=[],
    )
    h = Hit(chunk=c, score=1.0, method="dense")
    p = Plan(
        action=action,
        as_of="2026-11-08",
        companies=[{"ticker": "ACME", "source_mention": "ACME", "report_years": [2025]}],
        period_basis="report_fy",
        period_interpretation="report FY",
        needs=[Need(id="n1", description="Revenue", source_quote="revenue")],
        tasks=[
            Task(
                id="t1",
                need_ids=["n1"],
                tickers=["ACME"],
                dense_queries=["revenue"],
                keywords=["revenue"],
            )
        ],
    )

    def planner(*args):
        if failure:
            raise failure
        return p, {"cached": True}

    class Retriever:
        def __init__(self, *args):
            self.store = store

        def search(self, *args):
            return [{"hits": [h.model_dump()]}]

    def rank(*args):
        return [h], {"c1": []}

    ev = [
        {
            "citation": "E1",
            "document_id": f.id,
            "ticker": "ACME",
            "fiscal_year": 2025,
            "period_end": f.period_end,
            "filed_at": f.filed_at,
            "source_url": f.source_url,
            "text": "Revenue 100",
            "source_spans": [],
        }
    ]

    def select(*args):
        return [h], ["Revenue 100"], ev if evidence else [], {"proxy_tokens": 3}

    for mod in (nodes, reference):
        monkeypatch.setattr(mod, "ROOT", tmp_path)
        monkeypatch.setattr(mod, "plan_request", planner)
        monkeypatch.setattr(mod, "PlannedRetriever", Retriever)
        monkeypatch.setattr(mod, "rank_records", rank)
        monkeypatch.setattr(mod, "select_context", select)

    class Model:
        def __init__(self):
            self.messages = []

        def generate(self, messages, **kwargs):
            self.messages.append(messages)
            return {
                "answer": json.dumps(
                    {
                        "sections": [
                            {
                                "need_id": "n1",
                                "status": "supported",
                                "answer": "Revenue 100 [E1]",
                                "citations": ["E1"],
                                "missing_evidence": [],
                            }
                        ],
                        "limitations": [],
                    }
                ),
                "finish_reason": "stop",
            }

    request = Request(question="ACME FY2025 revenue", as_of="2026-11-08")
    return request, store, Model


def test_graph_matches_sequential_receipts_and_prompts(monkeypatch, tmp_path):
    req, store, model = setup_receipts(monkeypatch, tmp_path)
    a, b = model(), model()
    old = execute(req, ServingConfig(engine="sequential"), store, a, None, query_id="old")
    new = execute(req, ServingConfig(), store, b, None, query_id="new")
    assert old["status"] == new["status"] == "generated"
    for key in (
        "original_plan",
        "plan",
        "search_records",
        "retrieval",
        "runtime_evidence",
        "generation",
    ):
        assert old[key] == new[key], key
    assert a.messages == b.messages and len(b.messages) == 1
    assert new["agent"]["outcome"] == "answered"
    assert [x["node"] for x in new["agent"]["transitions"]] == [
        "catalog",
        "plan",
        "retrieve",
        "fusion",
        "context",
        "evidence_gate",
        "answer",
        "validate",
    ]
    assert build_graph().get_graph().nodes["catalog"]


@pytest.mark.parametrize(
    ("action", "evidence", "generate", "expected"),
    [
        ("clarify", True, True, "clarification_required"),
        ("insufficient_evidence", True, True, "insufficient_evidence"),
        ("retrieve", False, True, "insufficient_evidence"),
        ("retrieve", True, False, "retrieved"),
    ],
)
def test_short_paths_do_not_generate(monkeypatch, tmp_path, action, evidence, generate, expected):
    req, store, model = setup_receipts(monkeypatch, tmp_path, action=action, evidence=evidence)
    llm = model()
    result = execute(req, ServingConfig(), store, llm, None, do_generate=generate)
    assert result["agent"]["outcome"] == expected
    assert not llm.messages


@pytest.mark.parametrize(
    ("failure", "expected"),
    [
        (BudgetExceeded("stop"), "budget_exhausted"),
        (RuntimeError("sensitive body"), "dependency_failure"),
        (PlanRejected("invalid_plan"), "invalid_result"),
    ],
)
def test_errors_terminate_without_retry_or_secret_body(monkeypatch, tmp_path, failure, expected):
    req, store, model = setup_receipts(monkeypatch, tmp_path, failure=failure)
    result = execute(req, ServingConfig(), store, model(), None)
    assert result["status"] == "error" and result["agent"]["outcome"] == expected
    assert [r["node"] for r in result["agent"]["transitions"]] == ["catalog", "plan"]
    assert "sensitive body" not in json.dumps(result)


def test_node_model_and_cancel_limits(monkeypatch, tmp_path):
    req, store, model = setup_receipts(monkeypatch, tmp_path)
    stopped = execute(req, ServingConfig(), store, model(), None, policy=RunPolicy(max_nodes=1))
    assert stopped["agent"]["outcome"] == "budget_exhausted"
    llm = model()
    stopped = execute(req, ServingConfig(), store, llm, None, policy=RunPolicy(max_model_calls=0))
    assert stopped["agent"]["outcome"] == "budget_exhausted" and not llm.messages
    stopped = execute(req, ServingConfig(), store, llm, None, cancelled=lambda: True)
    assert stopped["agent"]["outcome"] == "cancelled" and not llm.messages


def test_request_cost_guard_uses_same_ledger_and_keeps_unknown_holds(tmp_path):
    from finrag.agent.policy import PolicyStop, RunControl, bind_control

    ledger = Budget(tmp_path / "budget.jsonl", stop_usd="1")
    control = RunControl("run", RunPolicy(max_request_usd=Decimal(".1")))
    with bind_control(control):
        control.enter_node("answer")
        rid = ledger.reserve(".06", "fake", "test")
        with pytest.raises(PolicyStop):
            ledger.reserve(".06", "fake", "test")
        assert ledger.snapshot()["unresolved_reserved_usd"] == "0.06"
        ledger.settle(rid, ".03", {})
    assert control.snapshot()["paid_known_usd"] == "0.03"
    rows = [json.loads(s) for s in ledger.path.read_text().splitlines()]
    assert rows[0]["run_id"] == "run" and rows[0]["operation_id"] == "run:1:answer"


def test_parallel_requests_have_separate_states(monkeypatch, tmp_path):
    req, store, model = setup_receipts(monkeypatch, tmp_path)

    def run(i):
        return execute(req, ServingConfig(), store, model(), None, query_id=str(i))

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(run, range(2)))
    assert all(r["status"] == "generated" for r in results)
    assert results[0]["agent"]["transitions"] is not results[1]["agent"]["transitions"]
    assert {
        t["operation_id"].split(":")[0] for r in results for t in r["agent"]["transitions"]
    } == {r["run_id"] for r in results}
