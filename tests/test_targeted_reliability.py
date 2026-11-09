"""Generic reliability contracts, independent of development question IDs or gold values."""

import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from finrag.agent.planner import PlanRejected
from finrag.answering.calculations import Worksheet, evaluate, execute_worksheet
from finrag.answering.generation import generate_answer
from finrag.providers.llm import ProviderFailure
from finrag.retrieval.store import LiveStore


def test_arithmetic_anchors_precision_signs_and_no_execution():
    sheet = Worksheet(
        values=[
            {
                "id": "v1",
                "value": "1200",
                "citation": "E1",
                "quote": "Revenue | 1,200",
                "unit": "USD_million",
                "label": "FictionalCo actual FY2030 revenue",
            },
            {
                "id": "v2",
                "value": "(150)",
                "citation": "E1",
                "quote": "Cost | (150)",
                "unit": "USD_million",
                "label": "FictionalCo signed adjustment",
            },
            {
                "id": "bad",
                "value": "999",
                "citation": "E1",
                "quote": "Revenue | 1,200",
                "unit": "USD_million",
                "label": "Ungrounded",
            },
        ],
        calculations=[
            {
                "id": "c1",
                "expression": "(v1+v2)/v1*100",
                "unit": "percent",
                "label": "Adjustment ratio",
            },
            {
                "id": "c2",
                "expression": "c1-100",
                "unit": "percentage_points",
                "label": "Difference",
            },
            {"id": "c3", "expression": "bad/v1", "unit": "ratio", "label": "Invalid dependency"},
        ],
    )
    result = execute_worksheet(sheet, [{"citation": "E1", "text": "Revenue | 1,200\nCost | (150)"}])
    assert result["results"][0]["value"] == "87.500"
    assert result["results"][1]["value"] == "-12.500"
    assert result["results"][1]["citations"] == ["E1"]
    assert {r["id"] for r in result["rejected"]} == {"bad", "c3"}
    for expression in ['__import__("os").system("id")', "v1.real", "2**100", "v1[0]", "365*v1"]:
        with pytest.raises((ValueError, KeyError)):
            evaluate(expression, {"v1": Decimal(1)})
    with pytest.raises(ArithmeticError):
        evaluate("v1/0", {"v1": Decimal(1)})


def test_duplicate_operands_and_bad_quote_are_not_verified():
    value = {
        "id": "v1",
        "value": "12",
        "citation": "E1",
        "quote": "Absent value 12",
        "unit": "USD_million",
        "label": "Revenue",
    }
    result = execute_worksheet(
        Worksheet(values=[value], calculations=[]), [{"citation": "E1", "text": "Revenue 120"}]
    )
    assert not result["values"] and result["rejected"]
    with pytest.raises(ValueError, match="duplicate"):
        execute_worksheet(Worksheet(values=[value, value], calculations=[]), [])


def test_answer_repair_preserves_evidence_and_remains_bounded():
    data = {
        "inputs": {
            "original_question": "Explain costs",
            "reading_context": "",
            "confirmed_context": None,
            "as_of": "2030-01-01",
        },
        "plan": {"needs": [{"id": "n1", "description": "Costs"}]},
        "runtime_evidence": [{"citation": "E1", "text": "Costs: 120"}],
    }
    response = {
        "sections": [
            {
                "need_id": "n1",
                "status": "partial",
                "answer": "Costs 120[E1]",
                "citations": ["E1"],
                "missing_evidence": [],
            }
        ],
        "limitations": [],
    }

    class Model:
        def __init__(self, fix):
            self.calls = []
            self.fix = fix

        def generate(self, messages, **kwargs):
            self.calls.append((messages, kwargs))
            d = json.loads(json.dumps(response))
            if len(self.calls) == 2 and self.fix:
                d["sections"][0]["missing_evidence"] = ["Prior-period costs"]
            return {"answer": json.dumps(d), "finish_reason": "stop"}

    m = Model(True)
    r = generate_answer(data, m)
    assert len(m.calls) == 2 and len(r["attempts"]) == 2
    assert m.calls[1][1]["purpose"] == "answer_contract_repair"
    assert m.calls[0][0][1] == m.calls[1][0][1]
    assert r["structured_answer"]["sections"][0]["status"] == "partial"
    m = Model(False)
    with pytest.raises(PlanRejected, match="answer_missing_without_explanation"):
        generate_answer(data, m)
    assert len(m.calls) == 2

    class Unavailable:
        calls = 0

        def generate(self, *a, **k):
            self.calls += 1
            raise ProviderFailure("unknown_billing")

    m = Unavailable()
    with pytest.raises(ProviderFailure):
        generate_answer(data, m)
    assert m.calls == 1


def test_timeout_recovery_is_request_wide_and_counts_budget(monkeypatch):
    import finrag.retrieval.store as module

    class Cancel(Exception):
        def __init__(self, message):
            self.diag = SimpleNamespace(message_primary=message)

    monkeypatch.setattr(module.psycopg.errors, "QueryCanceled", Cancel)
    store = object.__new__(LiveStore)
    store.config = SimpleNamespace(pipeline=SimpleNamespace(max_search_calls=3))
    store.begin_query()
    calls = []

    def search(*a, **k):
        calls.append(1)
        if len(calls) == 1:
            raise Cancel("canceling statement due to statement timeout")
        return []

    store._search_once = search
    assert store.search() == [] and store.search_attempts == 2
    assert store.search_diagnostics[0]["retry"]
    store._search_once = lambda: (_ for _ in ()).throw(
        Cancel("canceling statement due to statement timeout")
    )
    with pytest.raises(Cancel):
        store.search()
    assert store.search_attempts == 3 and store.timeout_retries_remaining == 0
    with pytest.raises(Exception, match="search_call_resource_limit"):
        store.search()
    store.begin_query()
    store._search_once = lambda: (_ for _ in ()).throw(
        Cancel("canceling statement due to user request")
    )
    with pytest.raises(Cancel):
        store.search()
    assert store.search_attempts == 1 and store.timeout_retries_remaining == 1
