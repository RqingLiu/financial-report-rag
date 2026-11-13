"""Temporal policy contract tests: scripted model receipts, never paid/semantic model claims."""

import json
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from test_agent_graph import setup_receipts
from test_planning import filing, plan

from finrag.agent.planner import (
    Catalog,
    PipelineConfig,
    PlanRejected,
    Request,
    TemporalScope,
    plan_request,
    validate_plan,
)
from finrag.agent.runner import execute
from finrag.answering.generation import generate_answer
from finrag.serving.api import create_app
from finrag.serving.config import ServingConfig
from finrag.serving.explorer import trace_view


def annotated(*, source="catalog_default", quote="", analysis="Report coverage", **updates):
    return plan(
        temporal_scope={
            "analysis_period": analysis,
            "source": source,
            "source_quote": quote,
            "rationale": "No period specified; use the eligible in-corpus report coverage"
            if source == "catalog_default"
            else "Preserve the supplied period or clarify its meaning",
        },
        **updates,
    )


def check(p, req, catalog):
    return validate_plan(p, req, catalog, PipelineConfig(), require_temporal_scope=True)


def test_omitted_period_uses_all_eligible_reports_not_external_latest():
    catalog = Catalog(
        [
            filing(year=2024),
            filing(year=2025, day="2025-02-20"),
            filing(year=2026, day="2026-02-20"),
        ]
    )
    req = Request(question="ACME的核心产品和收入趋势", as_of="2025-12-31")
    p = annotated(as_of=req.as_of)
    with pytest.raises(PlanRejected, match="coverage_omitted"):
        check(p, req, catalog)
    p.companies[0].report_years = [2024, 2025]
    assert check(p, req, catalog).action == "retrieve"
    assert catalog.documents(p.companies[0], p.as_of) == ["ACME_FY2024", "ACME_FY2025"]


def test_explicit_earlier_facts_can_use_later_reports_under_today_cutoff():
    catalog = Catalog([filing(year=2025, day="2025-02-20")])
    req = Request(question="ACME FY2024收入", as_of="2026-10-11")
    p = annotated(
        source="user_question", quote="FY2024", analysis="FY2024 facts", period_basis="fact_fy"
    )
    p.companies[0].report_years = [2025]
    assert check(p, req, catalog).temporal_scope.analysis_period == "FY2024 facts"
    assert catalog.documents(p.companies[0], p.as_of) == ["ACME_FY2025"]
    p.temporal_scope = TemporalScope(**annotated().temporal_scope.model_dump())
    with pytest.raises(PlanRejected, match="explicit_period_cannot"):
        check(p, req, catalog)


@pytest.mark.parametrize(
    "source,quote,background,confirmed",
    [
        ("reading_context", "FY2024", "仅分析FY2024", None),
        ("confirmed_context", "2024", "", {"ticker": "ACME", "report_years": [2024]}),
    ],
)
def test_background_and_confirmed_scope_provenance(source, quote, background, confirmed):
    req = Request(
        question="ACME收入",
        reading_context=background,
        confirmed_context=confirmed,
        as_of="2026-10-11",
    )
    p = annotated(source=source, quote=quote, analysis="FY2024")
    assert check(p, req, Catalog([filing()]))
    p.temporal_scope.source_quote = "invented user period"
    with pytest.raises(PlanRejected, match="quote_not_in_source"):
        check(p, req, Catalog([filing()]))


def test_confirmed_period_cannot_be_overridden_by_catalog_default():
    req = Request(
        question="ACME收入", as_of="2026-10-11", confirmed_context={"report_years": [2024]}
    )
    with pytest.raises(PlanRejected, match="confirmed_period_cannot"):
        check(annotated(), req, Catalog([filing()]))


def test_material_ambiguity_routes_to_clarification_without_retrieval(monkeypatch, tmp_path):
    req, store, model = setup_receipts(monkeypatch, tmp_path)
    req = req.model_copy(update={"question": "ACME 2024年的收入是多少？"})
    p = annotated(
        source="clarification",
        analysis="2024 calendar year or company fiscal year unresolved",
        action="clarify",
        tasks=[],
        companies=[],
        needs=[],
        clarification_questions=["你指自然年2024，还是公司的FY2024？"],
        as_of=req.as_of,
    )
    check(p, req, store.catalog())
    monkeypatch.setattr("finrag.agent.nodes.plan_request", lambda *a: (p, {"cached": True}))
    monkeypatch.setattr(
        "finrag.agent.nodes.PlannedRetriever",
        lambda *a: pytest.fail("must clarify before retrieval"),
    )
    result = execute(req, ServingConfig(), store, model(), None)
    assert result["agent"]["outcome"] == "clarification_required"
    assert "generation" not in result
    assert [t["node"] for t in result["agent"]["transitions"]] == ["catalog", "plan"]
    visible = trace_view(result)
    scope = visible["agent"]["transitions"][-1]["state_after"]["plan"]["temporal_scope"]
    assert scope["source"] == "clarification" and scope["rationale"]


def test_temporal_annotations_required_only_for_new_live_plans(tmp_path):
    req = Request(question="ACME收入", as_of="2026-10-11")
    catalog = Catalog([filing()])
    assert validate_plan(plan(), req, catalog, PipelineConfig())  # Legacy compatibility.
    with pytest.raises(PlanRejected, match="missing_temporal_scope"):
        check(plan(), req, catalog)
    valid = annotated()

    class Model:
        calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            assert "temporal_scope" in messages[0]["content"]
            return {"answer": valid.model_dump_json(), "finish_reason": "stop"}

    model = Model()
    p, event = plan_request(req, catalog, PipelineConfig(), model, tmp_path)
    assert not event["cached"] and p.temporal_scope.source == "catalog_default"
    assert plan_request(req, catalog, PipelineConfig(), model, tmp_path)[1]["cached"]
    assert model.calls == 1
    valid.temporal_scope.source = "clarification"
    with pytest.raises(PlanRejected, match="unresolved_temporal_scope"):
        check(valid, req, catalog)


def test_new_graph_records_default_scope_in_state_and_answer(monkeypatch, tmp_path):
    from finrag.agent import nodes

    req, store, model = setup_receipts(monkeypatch, tmp_path)
    p, event = nodes.plan_request()
    req = req.model_copy(update={"question": "ACME revenue"})
    p.temporal_scope = TemporalScope(
        analysis_period="Available FY2025 report coverage",
        source="catalog_default",
        rationale="No requested period; one eligible FY2025 report",
    )
    check(p, req, store.catalog())
    monkeypatch.setattr(nodes, "plan_request", lambda *a: (p, event))
    result = execute(req, ServingConfig(), store, model(), None)
    visible = trace_view(result)
    transition = next(t for t in visible["agent"]["transitions"] if t["node"] == "plan")
    assert transition["state_after"]["plan"]["temporal_scope"]["source"] == "catalog_default"
    assert visible["plan"]["temporal_scope"]["rationale"]
    assert visible["generation"]["answer"].startswith("资料范围：ACME: FY2025")


def test_inferred_scope_is_always_disclosed_even_if_model_omits_it():
    p = annotated().model_dump(mode="json")
    payload = {
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
    model = SimpleNamespace(
        generate=lambda *a, **kw: {"answer": json.dumps(payload), "finish_reason": "stop"}
    )
    data = {
        "plan": p,
        "inputs": {
            "original_question": "ACME收入",
            "reading_context": "",
            "confirmed_context": None,
            "as_of": p["as_of"],
        },
        "runtime_evidence": [{"citation": "E1", "text": "Revenue 100"}],
    }
    result = generate_answer(data, model)
    assert result["answer"].startswith("资料范围：ACME: FY2024")
    assert "不代表完整历史或库外最新资料" in result["answer"]
    assert result["structured_answer"]["limitations"][0].startswith("资料范围：")
    p["temporal_scope"] = None  # Legacy output is not retroactively assigned inferred scope.
    assert not generate_answer(data, model)["answer"].startswith("资料范围：")


def test_browser_advanced_cutoff_retains_id_and_no_paid_calls(monkeypatch):
    monkeypatch.setattr("finrag.serving.api.query", lambda *a: pytest.fail("paid query"))
    with TestClient(create_app(ServingConfig())) as client:
        html = client.get("/").text
    advanced = html.split('<details id="advanced-options">', 1)[1].split("</details>", 1)[0]
    assert 'id="as-of"' in advanced and "信息截至日期" in advanced
    assert "不是分析年份" in advanced
    assert '<details id="advanced-options" open' not in html
