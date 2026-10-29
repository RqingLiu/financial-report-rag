import json
from decimal import Decimal

import pytest

from finrag.answering import generate_answer
from finrag.context import assemble, build_context
from finrag.models import Block, Chunk, Filing, Hit
from finrag.planned_retrieval import prepare_searches
from finrag.planning import (
    Catalog,
    PipelineConfig,
    Plan,
    PlanRejected,
    Request,
    plan_request,
    validate_plan,
)


def filing(ticker="ACME", year=2024, day="2024-02-20"):
    return Filing(
        id=f"{ticker}_FY{year}",
        ticker=ticker,
        cik=123,
        fiscal_year=year,
        form="10-K",
        accession=f"{ticker}{year}",
        period_end=f"{year}-01-28",
        filed_at=day,
        source_url="https://example.test/filing",
    )


def plan(tickers=("ACME",), **updates):
    data = {
        "action": "retrieve",
        "as_of": "2026-10-11",
        "companies": [{"ticker": t, "source_mention": t, "report_years": [2024]} for t in tickers],
        "excluded_tickers": [],
        "period_basis": "report_fy",
        "needs": [{"id": "n1", "description": "Revenue trend", "source_quote": "收入"}],
        "tasks": [
            {
                "id": "t1",
                "need_ids": ["n1"],
                "tickers": list(tickers),
                "dense_queries": ["Revenue and management explanation"],
                "keywords": ["revenue", "growth"],
                "depends_on": [],
                "route": "retrieve",
            }
        ],
        "clarification_questions": [],
        "unavailable_entities": [],
        "limitations": [],
        "period_interpretation": "User report FY",
    }
    data.update(updates)
    return Plan(**data)


def test_new_company_metadata_and_chinese_boundaries():
    catalog = Catalog([filing("ACME"), filing("OTHER")])
    assert catalog.mentions("比较ACME和OTHER的收入") == {"ACME", "OTHER"}
    assert not catalog.mentions("ACMEX没有这些数据")
    request = Request(question="比较ACME和OTHER的收入", as_of="2026-10-11")
    assert validate_plan(plan(("ACME", "OTHER")), request, catalog, PipelineConfig())
    with pytest.raises(PlanRejected, match="explicit_company_lost"):
        validate_plan(plan(), request, catalog, PipelineConfig())


def test_exclusions_and_confirmed_scope_cannot_be_lost():
    catalog = Catalog([filing(), filing("OTHER")])
    request = Request(question="ACME收入，不要OTHER", as_of="2026-10-11")
    with pytest.raises(PlanRejected, match="explicit_exclusion_lost"):
        validate_plan(plan(("ACME", "OTHER")), request, catalog, PipelineConfig())
    assert validate_plan(plan(excluded_tickers=["OTHER"]), request, catalog, PipelineConfig())
    request = Request(
        question="ACME收入",
        as_of="2024-02-20",
        confirmed_context={"report_document_id": "ACME_FY2024", "as_of": "2024-02-20"},
    )
    with pytest.raises(PlanRejected, match="cutoff_changed"):
        validate_plan(plan(), request, catalog, PipelineConfig())
    assert validate_plan(plan(as_of="2024-02-20"), request, catalog, PipelineConfig())


def test_explicit_period_unknown_scope_and_need_dependencies():
    catalog = Catalog([filing(), filing(year=2025)])
    request = Request(question="ACME FY2024收入", as_of="2026-10-11")
    wrong = plan()
    wrong.companies[0].report_years = [2025]
    with pytest.raises(PlanRejected, match="explicit_report_year_lost"):
        validate_plan(wrong, request, catalog, PipelineConfig())
    wrong = plan(("UNKNOWN",))
    with pytest.raises(PlanRejected, match="unknown_company_selected"):
        validate_plan(wrong, request, catalog, PipelineConfig())
    wrong = plan()
    wrong.tasks[0].depends_on = ["t1"]
    with pytest.raises(PlanRejected, match="invalid_dependencies"):
        validate_plan(wrong, request, catalog, PipelineConfig())
    wrong = plan()
    wrong.needs[0].source_quote = "NOT_IN_REQUEST"
    with pytest.raises(PlanRejected, match="need_quote"):
        validate_plan(wrong, request, catalog, PipelineConfig())


def test_scope_resource_preflight_and_historical_exclusion():
    catalog = Catalog([filing(), filing(year=2025)])
    p = plan(as_of="2024-02-20")
    assert {d for j in prepare_searches(p, catalog, PipelineConfig()) for d in j["documents"]} == {
        "ACME_FY2024"
    }
    with pytest.raises(PlanRejected, match="search_call_resource_limit"):
        prepare_searches(p, catalog, PipelineConfig(max_search_calls=1))


def test_planner_cache_schema_and_no_label_input(tmp_path):
    catalog = Catalog([filing()])
    request = Request(question="ACME收入", as_of="2026-10-11")

    class LLM:
        calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            assert "golden" not in json.dumps(messages)
            assert kwargs["json_object"] is True
            return {"answer": plan().model_dump_json(), "finish_reason": "stop"}

    llm = LLM()
    assert plan_request(request, catalog, PipelineConfig(), llm, tmp_path)[1]["cached"] is False
    assert plan_request(request, catalog, PipelineConfig(), llm, tmp_path)[1]["cached"] is True
    assert llm.calls == 1

    class Bad:
        def generate(self, *args, **kwargs):
            return {"answer": '{"sql":"DROP TABLE"}', "finish_reason": "stop"}

    with pytest.raises(PlanRejected, match="schema_invalid"):
        plan_request(request, catalog, PipelineConfig(), Bad(), tmp_path / "new")


def test_same_source_table_expansion_is_budgeted_and_maps_real_spans():
    text = "Metric | 2024 | 2023\nRevenue | 100 | 80\nMargin | 20 | 10"
    b = Block(
        id="b",
        document_id="ACME_FY2024",
        ordinal=0,
        kind="table",
        section="Item 8",
        text=text,
        start=100,
        end=100 + len(text),
        locator={},
    )
    h = Hit(
        chunk=Chunk(
            id="c",
            document_id=b.document_id,
            index_id="ix",
            section="Item 8",
            text="Revenue | 100 | 80",
            embedding_text="Revenue | 100 | 80",
            tokens=8,
            spans=[{"block_id": "b", "start": 120, "end": 139}],
            block_ids=["b"],
        ),
        score=0.1,
        method="dense",
    )

    class Store:
        def blocks(self, ids):
            return {"b": b}

    cfg = PipelineConfig()
    expanded, rendered = assemble(h, Store(), filing(), cfg)
    assert text in rendered and expanded.expanded_spans == [
        {"block_id": "b", "start": 100, "end": 100 + len(text)}
    ]
    selected, texts, meta = build_context(
        [h], {"c": [{"task_id": "t1", "task_rank": 1}]}, Store(), [filing()], cfg
    )
    assert selected[0].expanded_spans and "Margin" in texts["c"]
    assert meta["context_proxy_tokens"] <= cfg.context_tokens
    plain, _ = assemble(h, Store(), filing(), cfg.model_copy(update={"expand_tables": False}))
    assert plain.expanded_spans == []


def test_answer_validates_all_needs_and_citation_ids_without_gold():
    data = {
        "plan": plan().model_dump(mode="json"),
        "inputs": {
            "original_question": "ACME收入",
            "reading_context": "",
            "confirmed_context": None,
            "as_of": "2026-10-11",
        },
        "runtime_evidence": [{"citation": "E1", "text": "Revenue 100"}],
        "reference": "GOLD_CANARY",
    }

    class LLM:
        def generate(self, messages, **kwargs):
            assert "GOLD_CANARY" not in json.dumps(messages)
            return {
                "answer": json.dumps(
                    {
                        "sections": [
                            {
                                "need_id": "n1",
                                "status": "supported",
                                "answer": "收入100[E1]",
                                "citations": ["E1"],
                                "missing_evidence": [],
                            }
                        ],
                        "limitations": [],
                    }
                ),
                "finish_reason": "stop",
                "peak_list_cost_usd": str(Decimal(".001")),
            }

    assert generate_answer(data, LLM())["structured_answer"]["sections"][0]["need_id"] == "n1"

    class Bad(LLM):
        def generate(self, *args, **kwargs):
            result = super().generate(*args, **kwargs)
            result["answer"] = result["answer"].replace("E1", "E99")
            return result

    with pytest.raises(PlanRejected, match="invalid_citation"):
        generate_answer(data, Bad())


def test_opaque_document_id_and_explicit_year_exclusion():
    from finrag.pipeline import inputs_from_query

    row = {
        "id": "mock",
        "question": "ACME收入",
        "reading_context": "FY2024",
        "confirmed_context": {"report_document_id": "opaque-key:abc", "as_of": "2026-10-11"},
        "as_of": "2026-10-11",
        "corpus_scope": {"ACME": [2024]},
    }
    assert inputs_from_query(row)["confirmed_context"]["report_document_id"] == "opaque-key:abc"
    with pytest.raises(PlanRejected, match="extra_fields"):
        inputs_from_query({**row, "reference": "LABEL_MUST_NOT_ENTER"})
    catalog = Catalog([filing(), filing(year=2025)])
    request = Request(question="ACME FY2025收入，不要FY2024", as_of="2026-10-11")
    p = plan()
    p.companies[0].report_years = [2025]
    assert validate_plan(p, request, catalog, PipelineConfig())
    p.companies[0].report_years = [2024, 2025]
    with pytest.raises(PlanRejected, match="year_exclusion_lost"):
        validate_plan(p, request, catalog, PipelineConfig())


def test_unavailable_company_is_a_valid_nonretrieval_outcome():
    request = Request(question="UNKNOWN收入", as_of="2026-10-11")
    p = plan(
        ("UNKNOWN",), action="insufficient_evidence", tasks=[], unavailable_entities=["UNKNOWN"]
    )
    assert (
        validate_plan(p, request, Catalog([filing()]), PipelineConfig()).action
        == "insufficient_evidence"
    )


def test_dense_default_does_not_spend_fts_queries():
    p = plan()
    catalog = Catalog([filing()])
    jobs = prepare_searches(p, catalog, PipelineConfig(fts_weight=0))
    assert all(j["method"] == "dense" for j in jobs)
    jobs = prepare_searches(p, catalog, PipelineConfig(fts_weight=0, collect_fts_for_ablation=True))
    assert any(j["method"] == "fts" for j in jobs)


def test_embedding_index_contract_and_unindexed_document_fail_before_embedding():
    from types import SimpleNamespace

    from finrag.models import IndexConfig
    from finrag.planned_retrieval import PlannedRetriever
    from finrag.tracing import Trace

    class Conn:
        def execute(self, *args):
            return SimpleNamespace(fetchall=lambda: [{"document_id": "OTHER_FY2024", "n": 1}])

    repo = SimpleNamespace(connection=Conn())
    embedder = SimpleNamespace(model="wrong-model", dimension=1024)
    ix = IndexConfig(name="test", chunk_size=512, overlap=64)
    with pytest.raises(ValueError, match="embedding_does_not_match"):
        PlannedRetriever(repo, embedder, Catalog([filing()]), ix)
    embedder.model = "voyage-4-lite"
    retriever = PlannedRetriever(repo, embedder, Catalog([filing()]), ix)
    with pytest.raises(PlanRejected, match="document_not_indexed"):
        retriever.search(plan(), PipelineConfig(), Trace("mock", {}))


def test_source_cache_is_bounded_and_eviction_does_not_truncate_requested_sources():
    from types import SimpleNamespace

    from finrag.context import EvidenceStore

    def block(key):
        return Block(
            id=key,
            document_id="doc",
            ordinal=0,
            kind="text",
            section="Item 1",
            text="0123456789",
            start=0,
            end=10,
            locator={},
        ).model_dump()

    class Conn:
        def execute(self, sql, args):
            assert "- 'structured'" in sql
            return SimpleNamespace(fetchall=lambda: [{"payload": block(k)} for k in args[0]])

    store = EvidenceStore(SimpleNamespace(connection=Conn()), max_blocks=1, max_characters=12)
    result = store.blocks(["a", "b"])
    assert set(result) == {"a", "b"} and all(b.text == "0123456789" for b in result.values())
    assert len(store.cache) <= 1 and store.characters <= 12


def test_startup_failure_is_explicit_and_never_prints_secret_body(tmp_path, monkeypatch, capsys):
    from finrag import pipeline

    def fail():
        raise RuntimeError("SECRET_VALUE_MUST_NOT_BE_PRINTED")

    monkeypatch.setattr(pipeline, "_main", fail)
    monkeypatch.setattr(pipeline, "ROOT", tmp_path)
    with pytest.raises(SystemExit) as err:
        pipeline.main()
    assert err.value.code == 1
    assert "startup_or_io_error" in capsys.readouterr().out
    rows = list((tmp_path / "logs/pipeline_errors").glob("*.json"))
    assert len(rows) == 1 and "SECRET_VALUE" not in rows[0].read_text()
