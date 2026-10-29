import json
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest

from finrag.baseline import (
    ObservedRetriever,
    messages_for,
    retrieve_one,
    runtime_input,
    score_trace,
)
from finrag.config import ROOT
from finrag.files import read_jsonl
from finrag.generation import Budget, BudgetExceeded, DeepSeek, ProviderFailure
from finrag.models import Chunk, Filing, Hit, Question, RetrievalConfig
from finrag.retrieval import Retriever


def query(qid):
    return next(
        r
        for r in read_jsonl(ROOT / "data/evaluation/golden_v2/retrieval_queries.jsonl")
        if r["id"] == qid
    )


def make_hit(key, tokens=5):
    return Hit(
        chunk=Chunk(
            id=key,
            document_id="NVDA_FY2024",
            index_id="ix",
            section="Item 7",
            text="source",
            embedding_text="source",
            tokens=tokens,
            spans=[{"block_id": key, "start": 0, "end": 6}],
            block_ids=[key],
        ),
        score=0.1,
        method="dense",
    )


def test_query_only_and_confirmed_cutoff():
    r = query("U14")
    inputs = runtime_input(r)
    assert "NVDA FY2024" in inputs["effective_question"]
    assert inputs["as_of"] == "2024-02-21"
    with pytest.raises(ValueError):
        runtime_input({**r, "reference": "do not leak"})
    with pytest.raises(ValueError):
        runtime_input({**r, "as_of": "2026-10-11"})
    assert "FY2023" in runtime_input(query("U12"))["effective_question"]


def test_generation_never_serializes_offline_labels():
    t = {
        "inputs": runtime_input(query("U03")),
        "runtime_evidence": [],
        "reference": "GOLD_CANARY",
        "scores": {"secret": "GOLD_CANARY"},
    }
    assert "GOLD_CANARY" not in json.dumps(messages_for(t))
    assert t["inputs"]["original_question"] in messages_for(t)[1]["content"]


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


def test_observation_preserves_real_retriever_decisions_and_reveals_budget_loss():
    filing = Filing(
        id="NVDA_FY2024",
        ticker="NVDA",
        cik=1,
        fiscal_year=2024,
        form="10-K",
        accession="1",
        period_end="2024-01-28",
        filed_at="2024-02-21",
        source_url="https://example.test/filing",
    )
    a, b = make_hit("a", 8), make_hit("b", 5)

    class Repo:
        def search(self, *args, **kwargs):
            return [a, b]

    class Embed:
        model, dimension, events = "voyage-4-lite", 2, []

        def embed(self, texts, input_type):
            return [[0.0, 1.0]]

    def initialize(cls):
        obj = cls.__new__(cls)
        obj.filings, obj.repository, obj.embedder = [filing], Repo(), Embed()
        obj.indexes = {"fixture": SimpleNamespace(model_dump=dict)}
        return obj

    # config_id requires a real IndexConfig, but constructor is bypassed to avoid DB/files.
    from finrag.models import IndexConfig

    old, observed = initialize(Retriever), initialize(ObservedRetriever)
    for obj in [old, observed]:
        obj.indexes = {"fixture": IndexConfig(name="fixture", chunk_size=512, overlap=64)}
    cfg = RetrievalConfig(
        name="test", index_name="fixture", method="hybrid", grouped=True, context_budget_tokens=10
    )
    row = {
        "id": "test",
        "question": "NVDA FY2024收入",
        "reading_context": "NVDA FY2024",
        "confirmed_context": None,
        "as_of": "2024-02-21",
        "corpus_scope": {"NVDA": [2024]},
    }
    original, _ = old.retrieve(
        runtime_input(row)["effective_question"], cfg, k=10, as_of="2024-02-21"
    )
    t = retrieve_one(row, observed, cfg)
    assert t["status"] == "retrieved"
    assert [h.chunk.id for h in original] == [
        h["chunk"]["id"] for h in t["retrieval"]["final_hits"]
    ]
    stages = {s["name"]: s for s in t["stages"]}
    assert stages["retrieve.dense"]["parent_id"] == stages["fuse_group"]["id"]
    assert stages["context_build"]["outputs"]["decisions"][1]["decision"] == "context_budget"
    q = Question(
        id="test",
        question="q",
        question_en="",
        category="table",
        family="x",
        split="dev",
        documents=[filing.id],
        reference="not runtime",
        evidence_groups=[
            [{"document_id": filing.id, "block_id": "b", "quote": "source", "start": 0, "end": 6}]
        ],
    )
    scores = score_trace(t, q)
    assert scores["candidate_union"]["recall"] == 1
    assert scores["final_context"]["recall"] == 0
    assert scores["missing_group_stage"] == {"0": "context_budget_drop"}
    assert all(v == "pending_human" for v in scores["semantic_review"].values())


def test_unexpected_usage_records_charge_then_halts_new_calls(tmp_path):
    b = Budget(tmp_path / "cost.jsonl")
    request_id = b.reserve(".01", "deepseek", "test")
    with pytest.raises(ProviderFailure, match="usage_exceeded_reservation"):
        b.settle(request_id, ".02", {"unexpected_usage": True})
    assert Decimal(b.snapshot()["known_peak_list_cost_usd"]) == Decimal(".02")
    with pytest.raises(ProviderFailure, match="ledger_halted"):
        b.reserve(".01", "deepseek", "test")


def test_empty_context_does_not_call_generation():
    from finrag.baseline import generate_one

    filings = [Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl")]
    retriever = SimpleNamespace(filings=filings, observed=lambda *args: ([], [], [], {}))
    config = RetrievalConfig(name="test", index_name="fixture")
    data = retrieve_one(query("U03"), retriever, config)
    assert data["status"] == "insufficient_evidence"

    class NoCalls:
        def generate(self, *_):
            pytest.fail("Empty evidence must not trigger a paid generation")

    assert generate_one(data, NoCalls())["status"] == "insufficient_evidence"
