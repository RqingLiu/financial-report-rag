import json
from decimal import Decimal

import httpx
import pytest

from finrag.providers.llm import Budget, BudgetExceeded, DeepSeek, ProviderFailure


def test_budget_persists_unknown_and_rejects_overspend(tmp_path):
    b = Budget(tmp_path / "cost.jsonl", stop_usd=".10")
    first = b.reserve(".07", "deepseek", "test")
    with pytest.raises(BudgetExceeded):
        Budget(b.path, ".10").reserve(".03", "deepseek", "test")
    b.settle(first, ".01", {"tokens": 1})
    b.reserve(".07", "deepseek", "test")
    snapshot = Budget(b.path).snapshot()
    assert Decimal(snapshot["known_peak_list_cost_usd"]) == Decimal(".01")
    assert Decimal(snapshot["unresolved_reserved_usd"]) == Decimal(".07")
    with pytest.raises(ValueError):
        b.settle(first, "0", {})
    with pytest.raises(ValueError):
        Budget(b.path, "5.01")


def test_authorized_total_keeps_prior_costs_and_unknown_holds(tmp_path):
    from finrag.serving.config import ServingConfig

    budget = Budget(tmp_path / "cost.jsonl", stop_usd="5.00")
    charged = budget.reserve("3.01", "deepseek", "historical")
    budget.settle(charged, "3.00418038", {})
    budget.reserve("0.0093642", "deepseek", "unknown_usage")
    before = budget.path.read_bytes()
    with pytest.raises(BudgetExceeded):
        Budget(budget.path, "1.60").reserve("0.01", "deepseek", "query")
    assert budget.path.read_bytes() == before
    current = Budget(budget.path, "4.90")
    snapshot = current.snapshot()
    assert snapshot["known_peak_list_cost_usd"] == "3.00418038"
    assert snapshot["unresolved_reserved_usd"] == "0.0093642"
    with pytest.raises(BudgetExceeded):
        current.reserve("1.88645542", "deepseek", "would_reach_stop")
    current.reserve("0.01", "deepseek", "query")
    assert ServingConfig(stop_usd=5).run_policy.max_request_usd == Decimal("0.15")
    with pytest.raises(ValueError):
        ServingConfig(stop_usd=5.01)


def test_provider_uses_bounded_parameters_and_settles_usage(tmp_path):
    seen = []

    def respond(request):
        payload = json.loads(request.content)
        seen.append(payload)
        return httpx.Response(
            200,
            json={
                "id": "response1",
                "model": "deepseek-flash",
                "usage": {"prompt_tokens": 20, "completion_tokens": 5, "total_tokens": 25},
                "choices": [{"message": {"content": "有来源的答案[E1]"}, "finish_reason": "stop"}],
            },
        )

    b = Budget(tmp_path / "cost.jsonl")
    llm = DeepSeek("TEST_SECRET", b, transport=httpx.MockTransport(respond))
    result = llm.generate([{"role": "user", "content": "test"}], max_tokens=100)
    llm.close()
    assert seen[0]["thinking"] == {"type": "disabled"} and seen[0]["max_tokens"] == 100
    assert result["usage"]["total_tokens"] == 25
    assert not b.snapshot()["unresolved_requests"]
    assert "TEST_SECRET" not in b.path.read_text()


@pytest.mark.parametrize("mode", ["timeout", "missing_usage", "http_error"])
def test_unknown_billing_no_retry_and_reservation_survives(tmp_path, mode):
    calls = []

    def respond(request):
        calls.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("could include TEST_SECRET", request=request)
        if mode == "http_error":
            return httpx.Response(401, json={"error": "TEST_SECRET"})
        return httpx.Response(200, json={"choices": []})

    b = Budget(tmp_path / "cost.jsonl")
    llm = DeepSeek("TEST_SECRET", b, transport=httpx.MockTransport(respond))
    with pytest.raises(ProviderFailure) as exc:
        llm.generate([{"role": "user", "content": "test"}])
    llm.close()
    assert len(calls) == 1 and len(b.snapshot()["unresolved_requests"]) == 1
    assert "TEST_SECRET" not in str(exc.value) + b.path.read_text()


def test_unexpected_usage_records_charge_then_halts_new_calls(tmp_path):
    b = Budget(tmp_path / "cost.jsonl")
    request_id = b.reserve(".01", "deepseek", "test")
    with pytest.raises(ProviderFailure, match="usage_exceeded_reservation"):
        b.settle(request_id, ".02", {"unexpected_usage": True})
    assert Decimal(b.snapshot()["known_peak_list_cost_usd"]) == Decimal(".02")
    with pytest.raises(ProviderFailure, match="ledger_halted"):
        b.reserve(".01", "deepseek", "test")
