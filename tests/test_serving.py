"""Serving contracts: evidence grouping, cache concurrency, API admission and paid adapters."""

import json
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal

import httpx
import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_planning import filing, plan

from finrag.files import atomic_json
from finrag.generation import Budget, ProviderFailure
from finrag.planned_retrieval import prepare_searches
from finrag.planning import Catalog, PipelineConfig, PlanRejected, Task
from finrag.serving.api import Admission, create_app
from finrag.serving.config import ServingConfig
from finrag.serving.lexical import query_terms, terms
from finrag.serving.providers import CrossEncoder, DocumentEmbedder
from finrag.serving.regroup import validate_regroup


def test_concurrent_atomic_cache_write(tmp_path):
    path = tmp_path / "cache.json"
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(lambda i: atomic_json(path, {"value": i, "text": "x" * 10000}), range(50)))
    assert json.loads(path.read_text())["value"] in range(50)
    assert not list(tmp_path.glob("*.tmp"))


def test_regroup_allows_cross_company_but_enforces_scope_needs_and_sql():
    cat = Catalog([filing("ACME"), filing("OTHER")])
    cfg = PipelineConfig(fts_weight=0)
    original = plan(
        ("ACME", "OTHER"),
        tasks=[
            Task(
                id="a",
                need_ids=["n1"],
                tickers=["ACME"],
                dense_queries=["revenue", "risks"],
                keywords=["revenue"],
            ),
            Task(
                id="b",
                need_ids=["n1"],
                tickers=["OTHER"],
                dense_queries=["revenue", "risks"],
                keywords=["revenue"],
            ),
        ],
    )
    shared = [
        Task(
            id="x",
            need_ids=["n1"],
            tickers=["ACME", "OTHER"],
            dense_queries=["statement revenue", "operating risks"],
            keywords=["revenue"],
        )
    ]
    revised = validate_regroup(original, shared, cat, cfg)
    assert (
        len(prepare_searches(original, cat, cfg)) == len(prepare_searches(revised, cat, cfg)) == 4
    )
    for bad in (
        [shared[0].model_copy(update={"tickers": ["ACME"]})],
        [shared[0].model_copy(update={"need_ids": ["unknown"]})],
        [*shared, shared[0].model_copy(update={"id": "extra"})],
    ):
        with pytest.raises(PlanRejected):
            validate_regroup(original, bad, cat, cfg)


def test_crossencoder_validates_ids_and_repeated_query_billing(tmp_path):
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={
                "usage": {"total_tokens": 100},
                "data": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.1},
                ],
            },
        )

    budget = Budget(tmp_path / "budget")
    ce = CrossEncoder("test", budget, tmp_path / "cache", transport=httpx.MockTransport(respond))
    try:
        scores, event = ce.rank("query", ["a", "b"])
        assert scores[1] > scores[0] and not event["cached"]
        assert ce.rank("query", ["a", "b"])[1]["cached"]
        assert len(calls) == 1 and calls[0]["truncation"] is False
        assert Decimal(budget.snapshot()["known_peak_list_cost_usd"]) == Decimal(".000002")
    finally:
        ce.close()
    ce = CrossEncoder(
        "test",
        budget,
        tmp_path / "bad",
        transport=httpx.MockTransport(
            lambda req: httpx.Response(
                200,
                json={
                    "usage": {"total_tokens": 1},
                    "data": [
                        {"index": 0, "relevance_score": 1},
                        {"index": 0, "relevance_score": 1},
                    ],
                },
            )
        ),
    )
    try:
        with pytest.raises(ProviderFailure, match="indices_invalid"):
            ce.rank("q", ["a", "b"])
    finally:
        ce.close()


def test_document_embedding_uses_document_role_and_shared_budget(tmp_path):
    emb = DocumentEmbedder(
        "test", tmp_path / "emb", dimension=2, shared_budget=Budget(tmp_path / "budget")
    )
    emb.client.close()
    calls = []

    def respond(req):
        calls.append(json.loads(req.content))
        return httpx.Response(
            200,
            json={"usage": {"total_tokens": 4}, "data": [{"index": 0, "embedding": [1.0, 0.0]}]},
        )

    emb.client = httpx.Client(
        base_url="https://example.test", transport=httpx.MockTransport(respond)
    )
    emb.paid.client = emb.client
    try:
        assert emb.embed(["text"], input_type="document") == [[1.0, 0.0]]
        assert calls[0]["input_type"] == "document"
    finally:
        emb.close()


def test_api_input_admission_and_safe_errors(monkeypatch):
    cfg = ServingConfig(max_inflight=1)
    gate = Admission(1)
    with gate.enter(), pytest.raises(HTTPException) as caught, gate.enter():
        pass
    assert caught.value.status_code == 429
    with gate.enter():
        pass
    monkeypatch.setattr(
        "finrag.serving.api.query",
        lambda *args: {
            "query_id": "q",
            "status": "clarify",
            "plan": {"clarification_questions": ["Which company?"]},
            "runtime_evidence": [],
        },
    )
    client = TestClient(create_app(cfg))
    assert client.post("/query", json={"question": "hi", "as_of": "2025-01-01"}).status_code == 200
    assert client.post("/query", json={"question": "hi"}).status_code == 422
    assert client.post("/query", content=b"x" * 100001).status_code == 413
    monkeypatch.setattr(
        "finrag.serving.api.query",
        lambda *args: (_ for _ in ()).throw(ValueError("password secret")),
    )
    response = client.post("/query", json={"question": "hi", "as_of": "2025-01-01"})
    assert response.status_code == 503 and "secret" not in response.text


def test_bm25_tokenization_is_explicit_and_bounded():
    assert terms("Revenue REVENUE HBM3E") == {"revenue": 2, "hbm3e": 1}
    assert query_terms("Revenue revenue") == ["revenue"]
    with pytest.raises(ValueError, match="term_limit"):
        query_terms(" ".join("t" + str(i) for i in range(33)))
    with pytest.raises(ValueError):
        ServingConfig(namespace="finrag;DROP")


def test_api_rejects_excess_queries_before_worker_queue(monkeypatch):
    from threading import Event

    started, release = Event(), Event()

    def slow(*args):
        started.set()
        assert release.wait(5)
        return {"query_id": "q", "status": "clarify", "plan": {}, "runtime_evidence": []}

    monkeypatch.setattr("finrag.serving.api.query", slow)
    client = TestClient(create_app(ServingConfig(max_inflight=1)))
    payload = {"question": "hi", "as_of": "2025-01-01"}
    with ThreadPoolExecutor(2) as pool:
        future = pool.submit(client.post, "/query", json=payload)
        assert started.wait(3)
        try:
            assert client.post("/query", json=payload).status_code == 429
        finally:
            release.set()
        assert future.result().status_code == 200


def test_reranker_diagnostic_length_does_not_invalidate_evidence():
    from finrag.reranking import validate_grades

    text = json.dumps({"scores": [{"i": 0, "s": 4, "n": ["n1"], "l": [[1, 1]], "r": "x" * 1000}]})
    result = validate_grades(text, [{"chunk_id": "a", "lines": ["fact"]}], {"n1"})
    assert result["a"]["s"] == 4 and result["a"]["l"] == [(1, 1)] and len(result["a"]["r"]) == 120
    with pytest.raises(PlanRejected):
        validate_grades(text, [{"chunk_id": "a", "lines": []}], {"n1"})


def test_hybrid_replaces_variant_preserves_jobs_scope_and_k():
    from finrag.serving.lexical import replace_second_variants

    cat = Catalog([filing()])
    cfg = PipelineConfig(fts_weight=0)
    base = plan(
        tasks=[
            Task(
                id="a",
                need_ids=["n1"],
                tickers=["ACME"],
                dense_queries=["sales", "income"],
                keywords=["revenue"],
            )
        ]
    )
    jobs = prepare_searches(base, cat, cfg)
    hybrid = replace_second_variants(jobs, base)
    assert len(jobs) == len(hybrid) == 2
    assert [j["method"] for j in hybrid] == ["dense", "fts"]
    assert hybrid[1]["query"] == "revenue"
    assert [(j["documents"], j["k"]) for j in jobs] == [(j["documents"], j["k"]) for j in hybrid]
    assert jobs[1]["method"] == "dense"  # no mutation of the frozen control


def test_objective_compiler_allocates_alternatives_without_exceeding_sql():
    from finrag.serving.regroup import ObjectiveTask, compile_tasks

    cat = Catalog([filing("ACME"), filing("OTHER")])
    cfg = PipelineConfig(fts_weight=0)
    original = plan(
        ("ACME", "OTHER"),
        tasks=[
            Task(
                id="old",
                need_ids=["n1"],
                tickers=["ACME", "OTHER"],
                dense_queries=["sales", "income"],
                keywords=["revenue"],
            )
        ],
    )
    objective = ObjectiveTask(
        id="x",
        evidence_objective="annual income statement revenue",
        need_ids=["n1"],
        tickers=["ACME", "OTHER"],
        query="net sales statement",
        alternative_query="total revenue row",
        keywords=["revenue"],
    )
    revised = compile_tasks([objective], original, cat, cfg)
    assert (
        len(prepare_searches(revised, cat, cfg)) == len(prepare_searches(original, cat, cfg)) == 4
    )
    assert revised.tasks[0].dense_queries == ["net sales statement", "total revenue row"]
