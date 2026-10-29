"""Voyage HTTP adapter with persistent caching, retries, and a conservative cost ceiling."""

import json
import time
from pathlib import Path
from typing import ClassVar

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from .files import atomic_json, digest


class TransientEmbeddingError(Exception):
    pass


class VoyageEmbedder:
    PRICE_PER_MILLION: ClassVar[dict[str, float]] = {"voyage-4-lite": 0.02}

    def __init__(
        self, api_key: str, cache_dir: Path, model="voyage-4-lite", dimension=1024, budget_usd=1.0
    ):
        self.model, self.dimension = model, dimension
        self.cache_dir = cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)
        self.ledger_path = cache_dir / "usage.jsonl"
        self.budget_usd = budget_usd
        self.client = httpx.Client(
            base_url="https://api.voyageai.com/v1",
            timeout=90,
            headers={"Authorization": f"Bearer {api_key}"},
        )
        if model not in self.PRICE_PER_MILLION:
            raise ValueError("Configure an explicit price before enabling another embedding model")

    def close(self):
        self.client.close()

    def _key(self, text, input_type):
        return digest(json.dumps([self.model, self.dimension, input_type, text]))

    def _spent(self):
        if not self.ledger_path.exists():
            return 0.0
        return sum(
            json.loads(s)["estimated_list_cost_usd"]
            for s in self.ledger_path.read_text().splitlines()
            if s
        )

    @retry(
        retry=retry_if_exception_type((TransientEmbeddingError, httpx.TransportError)),
        wait=wait_random_exponential(min=2, max=30),
        stop=stop_after_attempt(5),
        reraise=True,
    )
    def _request(self, texts, input_type):
        # UTF-8 byte count is a conservative request-token upper bound; actual usage recorded later.
        ceiling = sum(len(t.encode()) for t in texts) * self.PRICE_PER_MILLION[self.model] / 1e6
        if self._spent() + ceiling > self.budget_usd:
            raise RuntimeError("Embedding budget ceiling reached; no request submitted")
        response = self.client.post(
            "/embeddings",
            json={
                "input": texts,
                "model": self.model,
                "input_type": input_type,
                "output_dimension": self.dimension,
                "truncation": False,
            },
        )
        if response.status_code in (429, 500, 502, 503, 504):
            raise TransientEmbeddingError(f"Voyage temporary status {response.status_code}")
        if response.status_code != 200:
            # Never include request headers, credentials, or untrusted response bodies in logs.
            raise RuntimeError(f"Voyage status {response.status_code}; check model access/billing")
        data = response.json()
        embeddings = [r["embedding"] for r in sorted(data["data"], key=lambda x: x["index"])]
        if len(embeddings) != len(texts) or any(len(e) != self.dimension for e in embeddings):
            raise ValueError("Embedding response length/dimension mismatch")
        tokens = data["usage"]["total_tokens"]
        record = {
            "time": time.time(),
            "model": self.model,
            "dimension": self.dimension,
            "input_type": input_type,
            "inputs": len(texts),
            "tokens": tokens,
            "estimated_list_cost_usd": tokens * self.PRICE_PER_MILLION[self.model] / 1e6,
            "free_credits_applied": "unknown; list-cost estimate, not actual invoice",
        }
        with self.ledger_path.open("a") as stream:
            stream.write(json.dumps(record) + "\n")
        return embeddings

    def embed(self, texts: list[str], input_type="document") -> list[list[float]]:
        keys = [self._key(t, input_type) for t in texts]
        missing = list(
            dict.fromkeys(k for k in keys if not (self.cache_dir / f"{k}.json").exists())
        )
        by_key = dict(zip(keys, texts))
        for offset in range(0, len(missing), 32):
            batch = missing[offset : offset + 32]
            vectors = self._request([by_key[k] for k in batch], input_type)
            for key, vector in zip(batch, vectors):
                atomic_json(self.cache_dir / f"{key}.json", vector)
            print(
                f"embedded {min(offset + 32, len(missing))}/{len(missing)} uncached "
                f"{input_type} inputs",
                flush=True,
            )
            time.sleep(0.15)
        return [json.loads((self.cache_dir / f"{key}.json").read_text()) for key in keys]
