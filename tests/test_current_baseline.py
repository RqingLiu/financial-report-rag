"""Benchmark recovery must not silently rebill attempts or expose evaluation scope to models."""

from contextlib import contextmanager
from types import SimpleNamespace

import pytest

from finrag.core.files import atomic_json
from finrag.evaluation import run as module


def test_resume_and_stop_on_unknown_billing(tmp_path, monkeypatch):
    query = {
        "id": "U01",
        "question": "Revenue?",
        "reading_context": "",
        "confirmed_context": None,
        "as_of": "2026-10-11",
        "corpus_scope": {"TEST": [2025]},
    }
    atomic_json(tmp_path / "data/evaluation/golden_v2/retrieval_queries.jsonl", "{}", raw=True)
    monkeypatch.setattr(module, "ROOT", tmp_path)
    monkeypatch.setattr(module, "read_jsonl", lambda _: [query, {**query, "id": "U02"}])
    budget = SimpleNamespace(
        snapshot=lambda: {"known_peak_list_cost_usd": "0", "unresolved_requests": ["private-id"]}
    )
    monkeypatch.setattr(module, "shared_budget", lambda _: budget)
    store = SimpleNamespace(catalog=lambda: SimpleNamespace(metadata=lambda _: []))

    @contextmanager
    def resources(_):
        yield store, object(), SimpleNamespace(events=[]), None

    monkeypatch.setattr(module, "resources", resources)
    calls = []

    def execute(request, *_, **kwargs):
        calls.append(kwargs["query_id"])
        assert kwargs["do_generate"] is False
        assert "GOLD SENTINEL" not in request.model_dump_json()
        assert "corpus_scope" not in request.model_dump()
        return {"status": "error", "inputs": {}, "error": {"type": "ProviderFailure"}}

    monkeypatch.setattr(module, "execute", execute)
    module.run(tmp_path / "out", retrieve_only=True)
    module.run(tmp_path / "out", retrieve_only=True)
    assert calls == ["U01"]
    assert "private-id" not in (tmp_path / "out/progress.json").read_text()
    query["as_of"] = "2025-10-11"
    (tmp_path / "data/evaluation/golden_v2/retrieval_queries.jsonl").write_text("changed")
    with pytest.raises(ValueError, match="resume_identity_changed"):
        module.run(tmp_path / "out", retrieve_only=True)


def test_query_source_rejects_gold_and_unsafe_ids_before_resources(tmp_path, monkeypatch):
    from finrag.core.files import write_jsonl

    q = {
        "id": "U01.01",
        "question": "Revenue?",
        "reading_context": "",
        "confirmed_context": None,
        "as_of": "2026-10-11",
        "corpus_scope": {"ACME": [2025]},
    }
    path = tmp_path / "queries.jsonl"
    write_jsonl(path, [{**q, "reference": "GOLD SENTINEL"}])

    def forbidden(*_, **__):
        raise AssertionError("resources must not open")

    monkeypatch.setattr(module, "resources", forbidden)
    with pytest.raises(ValueError, match="query_only"):
        module.run(tmp_path / "out", queries_path=path)
    write_jsonl(path, [{**q, "id": "../escape"}])
    with pytest.raises(ValueError, match="unsafe"):
        module.run(tmp_path / "out", queries_path=path)
