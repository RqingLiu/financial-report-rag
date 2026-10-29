from copy import deepcopy

import pytest

from finrag.chunk import token_count
from finrag.context import build_context
from finrag.models import Block, Chunk, Filing, Hit
from finrag.need_context import need_proxies
from finrag.planning import PipelineConfig, Plan, PlanRejected


def inputs():
    filing = Filing(
        id="opaque-doc",
        ticker="NEWCO",
        cik=999,
        fiscal_year=2025,
        form="10-K",
        accession="x",
        period_end="2025-12-31",
        filed_at="2026-02-01",
        source_url="https://example.test/report",
    )
    plan = Plan(
        action="retrieve",
        as_of="2026-10-11",
        companies=[{"ticker": "NEWCO", "source_mention": "NEWCO", "report_years": [2025]}],
        period_basis="report_fy",
        needs=[{"id": n, "description": n, "source_quote": n} for n in ("n1", "n2")],
        tasks=[
            {
                "id": t,
                "need_ids": [n],
                "tickers": ["NEWCO"],
                "dense_queries": [n],
                "keywords": [n],
            }
            for t, n in (("t1", "n1"), ("t2", "n2"))
        ],
        period_interpretation="Report scope only",
    )
    return filing, plan


def hit(identifier, text="Revenue 100 and cost 50. " * 8):
    return Hit(
        chunk=Chunk(
            id=identifier,
            document_id="opaque-doc",
            index_id="ix",
            section="Item 7",
            text=text,
            embedding_text=text,
            tokens=token_count(text),
            block_ids=[identifier],
            spans=[{"block_id": identifier, "start": 0, "end": len(text)}],
        ),
        score=0.5,
        method="dense",
    )


def records(task, hits):
    return {
        "task_id": task,
        "method": "dense",
        "documents": ["opaque-doc"],
        "variants": 1,
        "hits": [h.model_dump() for h in hits],
    }


class NoStore:
    def blocks(self, _):
        raise AssertionError("No source fetch necessary when expansion disabled")


def test_diminishing_returns_selects_unrepresented_need_and_shared_evidence_once():
    filing, plan = inputs()
    a, duplicate_topic, b = hit("a"), hit("duplicate-topic"), hit("b")
    config = PipelineConfig(context_strategy="need_budget", context_k=2, expand_tables=False)
    source = [records("t1", [a, duplicate_topic]), records("t2", [b])]
    selected, _, metadata = build_context(
        [a, duplicate_topic, b],
        {},
        NoStore(),
        [filing],
        config,
        plan=plan,
        search_records=source,
    )
    assert [h.chunk.id for h in selected] == ["a", "b"]
    assert metadata["proxy_represented_need_ids"] == ["n1", "n2"]
    # A source shared by two tasks/needs remains one evidence item/one token charge.
    source = [records("t1", [a]), records("t2", [a])]
    selected, texts, metadata = build_context(
        [a],
        {},
        NoStore(),
        [filing],
        config,
        plan=plan,
        search_records=source,
    )
    assert len(selected) == 1
    assert metadata["context_proxy_tokens"] == token_count(texts["a"])
    assert metadata["proxy_represented_need_ids"] == ["n1", "n2"]


def test_duplicate_variants_do_not_inflate_need_proxy_and_scope_is_guarded():
    _, plan = inputs()
    a = hit("a")
    config = PipelineConfig(context_strategy="need_budget")
    source = [records("t1", [a]), records("t2", [a])]
    assert need_proxies(plan, source, config)[1:] == need_proxies(plan, source * 2, config)[1:]
    corrupted = deepcopy(source)
    corrupted[0]["hits"][0]["chunk"]["document_id"] = "unrequested-doc"
    with pytest.raises(PlanRejected, match="outside_search_scope"):
        need_proxies(plan, corrupted, config)
    with pytest.raises(PlanRejected, match="requires_plan"):
        need_proxies(None, source, config)


def test_budget_fallback_never_claims_an_omitted_table_and_deduplicates_sources():
    filing, plan = inputs()
    short = "Revenue | 100 | 80"
    table = short + "\n" + "Other metric | 10 | 20\n" * 150
    block = Block(
        id="a",
        document_id=filing.id,
        ordinal=1,
        kind="table",
        section="Item 8",
        text=table,
        start=0,
        end=len(table),
        locator={},
    )

    class Store:
        def blocks(self, _):
            return {"a": block}

    a = hit("a", short)
    duplicate = a.model_copy(update={"chunk": a.chunk.model_copy(update={"id": "dup"})})
    config = PipelineConfig(
        context_strategy="need_budget",
        context_tokens=1000,
        max_table_tokens=3000,
    )
    assert 1000 < token_count(table) <= 3000
    selected, texts, metadata = build_context(
        [a, duplicate],
        {},
        Store(),
        [filing],
        config,
        plan=plan,
        search_records=[records("t1", [a, duplicate])],
    )
    assert len(selected) == 1
    assert not selected[0].expanded_spans
    assert list(texts.values()) == [short]
    assert metadata["context_proxy_tokens"] == token_count(short) <= 1000
    assert metadata["proxy_unrepresented_need_ids"] == ["n2"]
