"""Bounded API adapters; fixed shared ledger counts all new baseline API requests."""

import fcntl
import json
import math
import os
from contextlib import contextmanager
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from uuid import uuid4

import httpx

from .embedding import VoyageEmbedder

D = Decimal
PRICE_SOURCES = {
    "checked_at": "2026-10-26",
    "deepseek": "https://api-docs.deepseek.com/quick_start/pricing/",
    "voyage": "https://docs.voyageai.com/docs/pricing",
    "basis": "conservative peak list cost, no cache discounts/free credits; not an invoice",
}


class BudgetExceeded(RuntimeError):
    pass


class ProviderFailure(RuntimeError):
    """Safe error metadata only; no provider body or credentials."""

    def __init__(self, code, status_code=None):
        self.code, self.status_code = code, status_code
        super().__init__(code)


class Budget:
    def __init__(self, path: Path, stop_usd="4.50"):
        self.path = path
        self.stop = D(str(stop_usd))
        if not self.stop.is_finite() or not D("0") < self.stop <= D("4.50"):
            raise ValueError("Stop threshold must be positive and <=4.50 of the authorized $5")
        path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        with self.path.open("a+") as stream:
            os.chmod(self.path, 0o600)
            fcntl.flock(stream, fcntl.LOCK_EX)
            stream.seek(0)
            rows = [json.loads(line) for line in stream if line.strip()]
            try:
                yield rows, stream
            finally:
                fcntl.flock(stream, fcntl.LOCK_UN)

    @staticmethod
    def _state(rows):
        held, spent = {}, D(0)
        for row in rows:
            if row["event"] == "reserve":
                held[row["id"]] = D(row["amount_usd"])
            elif row["event"] == "settle":
                held.pop(row["id"], None)
                spent += D(row["amount_usd"])
        return held, spent

    @staticmethod
    def _append(stream, row):
        stream.seek(0, 2)
        stream.write(json.dumps({**row, "at": datetime.now(UTC).isoformat()}) + "\n")
        stream.flush()
        os.fsync(stream.fileno())

    def reserve(self, amount, provider, purpose):
        amount = D(str(amount))
        if not amount.is_finite() or amount <= 0:
            raise ValueError("Invalid cost reservation")
        with self._locked() as (rows, stream):
            held, spent = self._state(rows)
            if any(r["event"] == "halt" for r in rows):
                raise ProviderFailure("ledger_halted_reconcile_before_new_calls")
            if spent + sum(held.values(), D(0)) + amount >= self.stop:
                raise BudgetExceeded("Shared baseline budget reached; no request submitted")
            request_id = uuid4().hex
            self._append(
                stream,
                {
                    "event": "reserve",
                    "id": request_id,
                    "amount_usd": str(amount),
                    "provider": provider,
                    "purpose": purpose,
                },
            )
        return request_id

    def settle(self, request_id, amount, usage):
        amount = D(str(amount))
        if not amount.is_finite() or amount < 0:
            raise ValueError("Invalid settlement")
        with self._locked() as (rows, stream):
            held, _ = self._state(rows)
            if request_id not in held:
                raise ValueError("Unknown/already settled reservation")
            reserved = held[request_id]
            self._append(
                stream,
                {"event": "settle", "id": request_id, "amount_usd": str(amount), "usage": usage},
            )
            if amount > reserved:
                # Preserve the observed cost, then fail closed on incorrect ceiling assumptions.
                self._append(
                    stream,
                    {"event": "halt", "id": request_id, "reason": "usage_exceeded_reservation"},
                )
                raise ProviderFailure("usage_exceeded_reservation")

    def check_halt(self):
        with self._locked() as (rows, _):
            if any(r["event"] == "halt" for r in rows):
                raise ProviderFailure("ledger_halted_reconcile_before_new_calls")

    def snapshot(self):
        with self._locked() as (rows, _):
            held, spent = self._state(rows)
        return {
            "known_peak_list_cost_usd": str(spent),
            "unresolved_reserved_usd": str(sum(held.values(), D(0))),
            "unresolved_requests": list(held),
            "stop_usd": str(self.stop),
            "authorization_usd": "5.00",
            "basis": PRICE_SOURCES,
            "halted": any(r["event"] == "halt" for r in rows),
        }


def integer_usage(value):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ProviderFailure("invalid_usage")
    return value


class PaidClient:
    def __init__(self, client, budget):
        self.client, self.budget = client, budget

    def post(self, endpoint, payload, ceiling, provider, purpose):
        self.budget.check_halt()
        reservation = self.budget.reserve(ceiling, provider, purpose)
        try:
            response = self.client.post(endpoint, json=payload)
        except (httpx.ConnectError, httpx.ConnectTimeout) as exc:
            # Connection was never established; no provider completion was submitted.
            self.budget.settle(reservation, "0", {"not_submitted": type(exc).__name__})
            raise ProviderFailure("connection_not_established") from None
        except httpx.TransportError:
            # Unknown billing: leave reservation held, no automatic retries.
            raise ProviderFailure("transport_failure_billing_unknown") from None
        if response.status_code != 200:
            # Conservative: leave reservation held pending reconciliation.
            raise ProviderFailure("provider_http_error", response.status_code)
        try:
            data = response.json()
        except ValueError:
            raise ProviderFailure("invalid_response_billing_unknown") from None
        return data, reservation


class DeepSeek:
    def __init__(self, api_key, budget, transport=None):
        self.http = httpx.Client(
            base_url="https://api.deepseek.com",
            timeout=60,
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        self.paid = PaidClient(self.http, budget)
        self.budget = budget

    def close(self):
        self.http.close()

    def generate(self, messages, max_tokens=4096, *, json_object=False, purpose="baseline_answer"):
        if not 1 <= max_tokens <= 4096:
            raise ValueError("Baseline max_tokens must be 1..4096")
        payload = {
            "model": "deepseek-flash",
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": 0,
            "thinking": {"type": "disabled"},
            "stream": False,
        }
        if json_object:
            payload["response_format"] = {"type": "json_object"}
        # Serialized bytes plus a deliberately large framing allowance, not tokenizer estimates.
        upper_in = len(json.dumps(messages, ensure_ascii=False).encode()) + 8192
        ceiling = (D(upper_in) * D("0.30") + D(max_tokens) * D("1.20")) / D(1000000)
        data, reservation = self.paid.post(
            "/chat/completions", payload, ceiling, "deepseek", purpose
        )
        try:
            usage = data["usage"]
            prompt = integer_usage(usage["prompt_tokens"])
            completion = integer_usage(usage["completion_tokens"])
            if integer_usage(usage["total_tokens"]) != prompt + completion:
                raise ProviderFailure("invalid_usage_sum")
        except (KeyError, TypeError):
            raise ProviderFailure("missing_usage_billing_unknown") from None
        cost = (D(prompt) * D("0.30") + D(completion) * D("1.20")) / D(1000000)
        self.budget.settle(reservation, cost, usage)
        try:
            choice = data["choices"][0]
            answer = choice["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ProviderFailure("empty_answer")
        except (KeyError, IndexError, TypeError):
            raise ProviderFailure("invalid_completion") from None
        return {
            "answer": answer,
            "provider_response_id": data.get("id"),
            "response_model": data.get("model"),
            "requested_model": payload["model"],
            "documented_version": "DeepSeek-V4.1-Flash-1017 (docs, not response verification)",
            "usage": usage,
            "peak_list_cost_usd": str(cost),
            "finish_reason": choice.get("finish_reason"),
            "parameters": {k: v for k, v in payload.items() if k != "messages"},
            "reservation_id": reservation,
        }


class BudgetedVoyage(VoyageEmbedder):
    """Reuse existing cache keys/vectors; use shared reservations instead of legacy retries."""

    def __init__(self, *args, shared_budget, **kwargs):
        super().__init__(*args, **kwargs)
        self.shared_budget = shared_budget
        self.paid = PaidClient(self.client, shared_budget)
        self.events = []

    def _request(self, texts, input_type):
        if self.model != "voyage-4-lite" or input_type != "query":
            raise ValueError("Baseline only permits voyage-4-lite query embeddings")
        upper = sum(len(t.encode()) for t in texts) + 1024
        ceiling = D(upper) * D("0.02") / D(1000000)
        data, reservation = self.paid.post(
            "/embeddings",
            {
                "input": texts,
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dimension,
                "truncation": False,
            },
            ceiling,
            "voyage",
            "baseline_query_embedding",
        )
        try:
            tokens = integer_usage(data["usage"]["total_tokens"])
        except (KeyError, TypeError):
            raise ProviderFailure("embedding_missing_usage_billing_unknown") from None
        cost = D(tokens) * D("0.02") / D(1000000)
        self.shared_budget.settle(reservation, cost, {"total_tokens": tokens})
        vectors = [r["embedding"] for r in sorted(data["data"], key=lambda r: r["index"])]
        if len(vectors) != len(texts) or any(len(v) != self.dimension for v in vectors):
            raise ProviderFailure("embedding_dimension_mismatch")
        if any(not math.isfinite(x) for v in vectors for x in v):
            raise ProviderFailure("embedding_nonfinite")
        record = {
            "model": self.model,
            "input_type": input_type,
            "tokens": tokens,
            "peak_list_cost_usd": str(cost),
            "reservation_id": reservation,
        }
        self.events.append(record)
        return vectors
