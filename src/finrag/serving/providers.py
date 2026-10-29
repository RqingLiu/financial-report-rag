"""Shared billing for document embedding and dedicated cross-encoder API, no hidden retries."""

import json
import math
from decimal import Decimal as D
from typing import ClassVar

import httpx

from ..files import atomic_json, digest
from ..generation import BudgetedVoyage, PaidClient, ProviderFailure, integer_usage
from .errors import ServingError


class DocumentEmbedder(BudgetedVoyage):
    def _request(self, texts, input_type):
        if input_type not in ("document", "query") or self.model != "voyage-4-lite":
            raise ServingError("unconfigured_embedding_model_or_input_type")
        # Base adapter validates response/cost and uses same input_type in payload and cache key.
        # Reuse implementation with explicit supported modes (baseline class stays query-only).
        ceiling = D(sum(len(t.encode()) for t in texts) + 1024) * D(".02") / D(1000000)
        data, rid = self.paid.post(
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
            input_type + "_embedding",
        )
        try:
            tokens = integer_usage(data["usage"]["total_tokens"])
            cost = D(tokens) * D(".02") / D(1000000)
            self.shared_budget.settle(rid, cost, {"total_tokens": tokens})
            rows = data["data"]
            if sorted(r["index"] for r in rows) != list(range(len(texts))):
                raise ProviderFailure("embedding_indices_invalid")
            vectors = [r["embedding"] for r in sorted(rows, key=lambda r: r["index"])]
            if any(
                len(v) != self.dimension or not all(math.isfinite(x) for x in v) or not any(v)
                for v in vectors
            ):
                raise ProviderFailure("embedding_values_invalid")
        except (KeyError, TypeError, ValueError):
            raise ProviderFailure("embedding_response_invalid") from None
        self.events.append(
            {
                "model": self.model,
                "input_type": input_type,
                "tokens": tokens,
                "peak_list_cost_usd": str(cost),
                "reservation_id": rid,
            }
        )
        return vectors


class CrossEncoder:
    PRICES: ClassVar[dict] = {"rerank-3-lite": D(".02"), "rerank-3": D(".05")}

    def __init__(self, key, budget, cache, model="rerank-3-lite", transport=None):
        self.model, self.budget, self.cache = model, budget, cache
        self.http = httpx.Client(
            base_url="https://api.voyageai.com/v1",
            timeout=60,
            transport=transport,
            headers={"Authorization": f"Bearer {key}"},
        )
        self.paid = PaidClient(self.http, budget)
        if model not in self.PRICES:
            raise ServingError("unconfigured_reranker_price")

    def close(self):
        self.http.close()

    def rank(self, query, documents):
        if not documents:
            return {}, {"cached": False, "documents": 0}
        if len(documents) > 80:
            raise ServingError("crossencoder_top80_limit")
        # Byte-based ceiling bounds tokens (including the repeated query), avoiding truncation.
        upper = (
            len(query.encode()) * len(documents) + sum(len(t.encode()) for t in documents) + 8192
        )
        if (
            len(query.encode()) > 8000
            or any(len((query + t).encode()) > 32000 for t in documents)
            or upper > 600000
        ):
            raise ServingError("crossencoder_input_limit")
        payload = {
            "model": self.model,
            "query": query,
            "documents": documents,
            "top_k": len(documents),
            "return_documents": False,
            "truncation": False,
        }
        key = digest(json.dumps(payload, sort_keys=True, ensure_ascii=False))
        path = self.cache / f"{key}.json"
        cached = path.exists()
        if cached:
            result = json.loads(path.read_text())
        else:
            data, rid = self.paid.post(
                "/rerank",
                payload,
                D(upper) * self.PRICES[self.model] / D(1000000),
                "voyage",
                "crossencoder_rerank",
            )
            try:
                tokens = integer_usage(data["usage"]["total_tokens"])
            except (KeyError, TypeError):
                raise ProviderFailure("reranker_missing_usage_billing_unknown") from None
            cost = D(tokens) * self.PRICES[self.model] / D(1000000)
            self.budget.settle(rid, cost, {"total_tokens": tokens})
            result = {"response": data, "peak_list_cost_usd": str(cost), "reservation_id": rid}
            atomic_json(path, result)
        try:
            rows = result["response"]["data"]
            if sorted(r["index"] for r in rows) != list(range(len(documents))):
                raise ProviderFailure("reranker_indices_invalid")
            scores = {r["index"]: float(r["relevance_score"]) for r in rows}
            if not all(math.isfinite(v) for v in scores.values()):
                raise ProviderFailure("reranker_scores_invalid")
        except (KeyError, TypeError, ValueError):
            raise ProviderFailure("reranker_response_invalid") from None
        return scores, {
            "cached": cached,
            "model": self.model,
            "cache_key": key,
            "documents": len(documents),
            "peak_list_cost_usd": result["peak_list_cost_usd"],
        }
