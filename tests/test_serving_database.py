"""Actual DB contracts in disposable namespaces, never fixture data in serving reports."""

import os
from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

import pytest
from psycopg import sql

from finrag.core.config import settings
from finrag.core.models import Block, Chunk, Filing, IndexConfig
from finrag.retrieval.store import LiveStore
from finrag.serving.config import ServingConfig

pytestmark = pytest.mark.skipif(
    os.getenv("FINRAG_INTEGRATION") != "1", reason="opt-in local PostgreSQL"
)


@pytest.fixture
def fixture():
    cfg = ServingConfig(namespace="finrag_live_t" + uuid4().hex, vector_search="exact")
    ix = IndexConfig(name="fixture", chunk_size=128, overlap=0, dimension=4)
    store = LiveStore(settings().database_url.get_secret_value(), cfg, ix)
    store.initialize()
    try:
        yield store
    finally:
        store.connection.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(store.ns))
        store.close()


def record(store, doc="opaque-source", year=2024):
    f = Filing(
        id=doc,
        ticker="NEWCO",
        cik=456,
        fiscal_year=year,
        form="10-K",
        accession=doc + "-accession",
        period_end=f"{year}-01-01",
        filed_at=f"{year}-02-01",
        source_url="https://example.test",
    )
    b = Block(
        id=doc + "-block",
        document_id=doc,
        ordinal=0,
        kind="text",
        section="Item 7",
        text="revenue revenue inventory growth",
        start=0,
        end=32,
        locator={},
    )
    c = Chunk(
        id=doc + "-chunk",
        document_id=doc,
        index_id=store.index_id,
        section="Item 7",
        text=b.text,
        embedding_text=b.text,
        tokens=4,
        spans=[{"block_id": b.id, "start": 0, "end": len(b.text)}],
        block_ids=[b.id],
    )
    return f, b, c


def test_publish_rollback_idempotency_and_reader_isolation(fixture):
    store = fixture
    f, b, c = record(store)
    assert store.publish(f, [b], [c], [[1, 0, 0, 0]])["status"] == "published"
    assert store.publish(f, [b], [c], [[1, 0, 0, 0]])["status"] == "unchanged"
    assert store.catalog().by_id[f.id].ticker == "NEWCO"
    assert store.search(store.index_id, [f.id], "2023-01-01", 10, vector=[1, 0, 0, 0]) == []
    assert store.search(store.index_id, [], "2026-01-01", 10, query="revenue") == []
    assert (
        store.search(store.index_id, [f.id], "2026-01-01", 10, query="revenue")[0].chunk.id == c.id
    )
    with pytest.raises(ValueError, match="immutable_publication"):
        store.publish(f, [b], [c.model_copy(update={"text": "changed"})], [[1, 0, 0, 0]])
    f2, b2, c2 = record(store, "opaque-other", 2025)
    # Inject DB failure after documents/blocks/chunks/postings have been inserted.
    store.connection.execute(
        sql.SQL(
            "ALTER TABLE {} ADD CONSTRAINT reject_new CHECK(document_id <> 'opaque-other')"
        ).format(store.table("publications"))
    )
    from psycopg.errors import CheckViolation

    with pytest.raises(CheckViolation):
        store.publish(f2, [b2], [c2], [[0, 1, 0, 0]])
    assert f2.id not in store.catalog().by_id
    assert (
        store.connection.execute(
            sql.SQL("SELECT n FROM {}").format(store.table("indexes"))
        ).fetchone()["n"]
        == 1
    )
    store.connection.execute(
        sql.SQL("ALTER TABLE {} DROP CONSTRAINT reject_new").format(store.table("publications"))
    )
    reader = LiveStore(settings().database_url.get_secret_value(), store.config, store.index_config)
    try:
        with reader.connection.transaction():
            reader.connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
            assert len(reader.catalog().filings) == 1
            with ThreadPoolExecutor(1) as pool:
                assert (
                    pool.submit(store.publish, f2, [b2], [c2], [[0, 1, 0, 0]]).result()["status"]
                    == "published"
                )
            assert len(reader.catalog().filings) == 1
        assert len(reader.catalog().filings) == 2
    finally:
        reader.close()


@pytest.mark.parametrize("kind", ["hnsw", "ivfflat"])
def test_ann_actual_index_usage_and_filtered_scope(fixture, kind):
    store = fixture
    f, b, c = record(store)
    import random

    rng = random.Random(23)
    chunks = [c.model_copy(update={"id": c.id + str(i)}) for i in range(160)]
    vectors = [[rng.random() for _ in range(4)] for _ in chunks]
    store.publish(f, [b], chunks, vectors)
    expected = store.search(store.index_id, [f.id], "2026-01-01", 10, vector=vectors[0])
    store.build_ann(kind, lists=8)
    store.config = store.config.model_copy(
        update={"vector_search": kind, "ivf_probes": 3, "ivf_max_probes": 8}
    )
    found = store.search(store.index_id, [f.id], "2026-01-01", 10, vector=vectors[0])
    assert len({h.chunk.id for h in found} & {h.chunk.id for h in expected}) >= 9
    explanation = store.search(
        store.index_id, [f.id], "2026-01-01", 10, vector=vectors[0], explain=True
    )
    assert "chunks_" + kind in str(explanation)
    assert store.search(store.index_id, [f.id], "2023-01-01", 10, vector=vectors[0]) == []
    assert store.search(store.index_id, ["wrong"], "2026-01-01", 10, vector=vectors[0]) == []


@pytest.mark.corpus
def test_full_html_new_metadata_ingestion_and_retry(fixture):
    from finrag.core.config import ROOT
    from finrag.ingestion.publish import ingest_html

    class FakeEmbedding:
        def embed(self, texts, input_type):
            assert input_type == "document"
            return [[1.0, 0.0, 0.0, 0.0] for _ in texts]

    # Synthetic issuer used only in disposable namespace: tests plumbing, not source quality.
    store = fixture
    filing, _, _ = record(store, "independent-opaque-new-report")
    result = ingest_html(ROOT / "data/raw/NVDA_FY2026.html", filing, store, FakeEmbedding())
    assert result["status"] == "published" and result["chunks"] > 100
    assert store.catalog().by_id[filing.id].ticker == "NEWCO"
    assert (
        ingest_html(ROOT / "data/raw/NVDA_FY2026.html", filing, store, FakeEmbedding())["status"]
        == "unchanged"
    )
    missing = filing.model_copy(update={"id": "bad", "accession": "bad", "sha256": "bad"})
    with pytest.raises(ValueError, match="checksum"):
        ingest_html(ROOT / "data/raw/NVDA_FY2026.html", missing, store, FakeEmbedding())
    assert "bad" not in store.catalog().by_id


@pytest.mark.corpus
def test_preflight_rejects_conflict_and_aliases_are_metadata(fixture):
    from finrag.ingestion.publish import ingest_html

    class NoCalls:
        def embed(self, *args, **kwargs):
            raise AssertionError("preflight must finish before embedding")

    store = fixture
    f, b, c = record(store)
    store.publish(f, [b], [c], [[1, 0, 0, 0]])
    assert store.preflight(f)["status"] == "unchanged"
    assert store.register_aliases("NEWCO", ["新公司"])["documents"] == 1
    assert store.catalog().mentions("新公司收入") == {"NEWCO"}
    from finrag.core.config import ROOT

    # Same document ID but different source metadata/hash must fail without a provider call.
    with pytest.raises(ValueError, match="immutable_source_conflict"):
        ingest_html(ROOT / "data/raw/NVDA_FY2026.html", f, store, NoCalls())


def test_real_timeout_rolls_back_before_one_recovery(fixture):
    store = fixture
    f, b, c = record(store)
    store.publish(f, [b], [c], [[1, 0, 0, 0]])
    original = store._search_once
    attempts = []

    def transient(*args, **kwargs):
        attempts.append(1)
        if len(attempts) == 1:
            with store.connection.transaction():
                store.connection.execute("SET LOCAL statement_timeout='1ms'")
                store.connection.execute("SELECT pg_sleep(0.02)")
        return original(*args, **kwargs)

    store._search_once = transient
    hits = store.search(store.index_id, [f.id], "2026-10-11", 1, vector=[1, 0, 0, 0])
    assert len(attempts) == 2 and hits[0].chunk.id == c.id
    assert store.search_diagnostics[0]["status"] == "statement_timeout"
    assert store.search_diagnostics[1]["status"] == "ok"
    assert store.timeout_retries_remaining == 0


def test_langgraph_matches_reference_with_real_sql_and_context(fixture, tmp_path, monkeypatch):
    """Actual SQL/source assembly with fixed model receipts, not a financial-quality score."""
    import json
    from types import SimpleNamespace

    from finrag.agent import nodes, reference
    from finrag.agent.planner import Request
    from finrag.agent.runner import execute

    f, b, c = record(fixture)
    fixture.publish(f, [b], [c], [[1, 0, 0, 0]])
    cfg = fixture.config.model_copy(update={"reranker": "none"})
    request = Request(question="NEWCO FY2024 revenue", as_of="2026-11-08")
    plan = {
        "action": "retrieve",
        "as_of": "2026-11-08",
        "companies": [{"ticker": "NEWCO", "source_mention": "NEWCO", "report_years": [2024]}],
        "period_basis": "report_fy",
        "period_interpretation": "report FY",
        "needs": [{"id": "n1", "description": "revenue", "source_quote": "revenue"}],
        "tasks": [
            {
                "id": "t1",
                "need_ids": ["n1"],
                "tickers": ["NEWCO"],
                "dense_queries": ["revenue"],
                "keywords": ["revenue"],
            }
        ],
    }

    class Model:
        def __init__(self):
            self.messages = []

        def generate(self, messages, **kwargs):
            self.messages.append(messages)
            value = (
                plan
                if kwargs.get("purpose") == "query_planning"
                else {
                    "sections": [
                        {
                            "need_id": "n1",
                            "status": "supported",
                            "answer": "Revenue [E1]",
                            "citations": ["E1"],
                            "missing_evidence": [],
                        }
                    ],
                    "limitations": [],
                }
            )
            return {"answer": json.dumps(value), "finish_reason": "stop"}

    embedder = SimpleNamespace(
        embed=lambda texts, **_: [[1, 0, 0, 0] for _ in texts],
        events=[],
        model=fixture.index_config.embedding_model,
        dimension=fixture.index_config.dimension,
    )
    old_model, new_model = Model(), Model()
    monkeypatch.setattr(reference, "ROOT", tmp_path / "reference")
    monkeypatch.setattr(nodes, "ROOT", tmp_path / "graph")
    old = execute(
        request, cfg.model_copy(update={"engine": "sequential"}), fixture, old_model, embedder
    )
    new = execute(request, cfg, fixture, new_model, embedder)
    assert old["status"] == new["status"] == "generated", (
        old.get("error"),
        new.get("error"),
        [(s["name"], s["status"]) for s in new["stages"]],
    )
    assert old_model.messages == new_model.messages
    for key in ("plan", "runtime_evidence", "generation"):
        assert old[key] == new[key]
    assert old["retrieval"]["final_hits"] == new["retrieval"]["final_hits"]
