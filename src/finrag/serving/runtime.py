"""Stable CLI/API adapter; LangGraph owns query control flow."""

from finrag.agent.runner import execute
from finrag.core.config import ROOT
from finrag.core.files import atomic_json
from finrag.serving.resources import (
    index_config,
    load_config,
    resources,
    safe_failure,
    shared_budget,
)

__all__ = [
    "execute",
    "index_config",
    "load_config",
    "query",
    "resources",
    "safe_failure",
    "shared_budget",
]


def query(request, config, *, do_generate=True, query_id=None, on_event=None):
    with resources(config) as (store, llm, embedder, ce):
        data = execute(
            request,
            config,
            store,
            llm,
            embedder,
            ce,
            do_generate=do_generate,
            query_id=query_id,
            on_event=on_event,
        )
    path = ROOT / "logs/serving" / f"{data['query_id']}.json"
    atomic_json(path, data)
    return data
