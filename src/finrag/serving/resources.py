"""One bounded pipeline for real queries and the optional HTTP API; no gold imports."""

import json
import os
from contextlib import ExitStack, contextmanager

from dotenv import dotenv_values

from finrag.agent.planner import PlanRejected
from finrag.core.config import ROOT, settings
from finrag.core.models import IndexConfig
from finrag.providers.llm import Budget, DeepSeek
from finrag.providers.voyage import CrossEncoder, DocumentEmbedder
from finrag.retrieval.store import LiveStore
from finrag.serving.config import ServingConfig


def load_config(path=None):
    return ServingConfig(**json.loads((path or ROOT / "configs/serving.json").read_text()))


def index_config(config):
    rows = json.loads((ROOT / "configs/indexes.json").read_text())
    return next(IndexConfig(**r) for r in rows if r["name"] == config.pipeline.index_name)


def shared_budget(config):
    return Budget(ROOT / "data/cache/baseline/budget.jsonl", stop_usd=config.stop_usd)


def safe_failure(exc):
    # Never render exception text from psycopg/httpx/Pydantic (can contain inputs/credentials).
    return {
        "type": type(exc).__name__,
        "code": str(exc)
        if isinstance(exc, PlanRejected)
        else getattr(exc, "code", "operation_failed_see_stage_and_exception_type"),
    }


@contextmanager
def resources(config, *, models=True):
    s = settings()
    with ExitStack() as stack:
        store = LiveStore(s.database_url.get_secret_value(), config, index_config(config))
        stack.callback(store.close)
        if not models:
            yield store, None, None, None
            return
        key = os.environ.get("DEEPSEEK_API_KEY") or dotenv_values(ROOT / ".env").get(
            "DEEPSEEK_API_KEY"
        )
        if not key:
            raise ValueError("generation_key_missing")
        budget = shared_budget(config)
        llm = DeepSeek(key, budget)
        stack.callback(llm.close)
        embedder = DocumentEmbedder(
            s.voyage_api_key.get_secret_value(),
            ROOT / "data/cache/embeddings",
            model=store.index_config.embedding_model,
            dimension=store.index_config.dimension,
            shared_budget=budget,
        )
        stack.callback(embedder.close)
        ce = None
        if config.reranker == "crossencoder":
            ce = CrossEncoder(
                s.voyage_api_key.get_secret_value(),
                budget,
                ROOT / "data/cache/crossencoder",
                model=config.crossencoder_model,
            )
            stack.callback(ce.close)
        yield store, llm, embedder, ce
