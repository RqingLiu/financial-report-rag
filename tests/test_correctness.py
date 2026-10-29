"""Scope/table/publication regressions from the project readiness review."""

import json

import pytest
from pydantic import ValidationError
from test_planning import filing, plan

from finrag.chunk import make_chunks
from finrag.config import ROOT
from finrag.files import read_jsonl
from finrag.models import Block, IndexConfig
from finrag.planning import (
    Catalog,
    PipelineConfig,
    PlanRejected,
    Request,
    plan_request,
    validate_plan,
)
from finrag.serving.errors import ServingError
from finrag.serving.ingestion import validate_source_coverage


def catalog():
    return Catalog([filing(t, y) for t in ("ACME", "OTHER") for y in (2024, 2025)])


def test_extra_company_and_borrowed_alias_cannot_expand_scope():
    p = plan(("ACME", "OTHER"))
    p.companies[1].source_mention = "ACME"
    with pytest.raises(PlanRejected, match="unrequested_company"):
        validate_plan(
            p, Request(question="ACME收入", as_of="2026-10-11"), catalog(), PipelineConfig()
        )
    p.companies[0].source_mention = "OTHER"
    with pytest.raises(PlanRejected, match="alias_mismatch"):
        validate_plan(
            p, Request(question="ACME和OTHER收入", as_of="2026-10-11"), catalog(), PipelineConfig()
        )


@pytest.mark.parametrize(
    "question",
    [
        "比较ACME FY2024和OTHER FY2025的收入",
        "比较FY2024的ACME和FY2025的OTHER收入",
    ],
)
def test_cross_company_years_are_validated_individually(question):
    p = plan(("ACME", "OTHER"))
    req = Request(question=question, as_of="2026-10-11")
    with pytest.raises(PlanRejected, match="report_year_lost"):
        validate_plan(p, req, catalog(), PipelineConfig())
    p.companies[1].report_years = [2025]
    assert validate_plan(p, req, catalog(), PipelineConfig())


def test_shared_years_and_report_constraints_cannot_be_bypassed_by_fact_flag():
    p = plan(("ACME", "OTHER"))
    req = Request(question="比较ACME和OTHER的FY2024–2025收入", as_of="2026-10-11")
    with pytest.raises(PlanRejected, match="report_year_lost"):
        validate_plan(p, req, catalog(), PipelineConfig())
    for c in p.companies:
        c.report_years = [2024, 2025]
    assert validate_plan(p, req, catalog(), PipelineConfig())
    p = plan(("ACME", "OTHER"), period_basis="fact_fy")
    req = Request(question="比较ACME FY2024年报和OTHER FY2025年报收入", as_of="2026-10-11")
    with pytest.raises(PlanRejected, match="report_year_lost"):
        validate_plan(p, req, catalog(), PipelineConfig())


def test_confirmed_context_is_typed_and_keeps_per_company_scope():
    req = Request(
        question="ACME和OTHER收入",
        as_of="2026-10-11",
        confirmed_context={
            "companies": [
                {"ticker": "ACME", "report_years": [2024]},
                {"ticker": "OTHER", "report_years": [2025]},
            ],
        },
    )
    p = plan(("ACME", "OTHER"))
    with pytest.raises(PlanRejected, match="confirmed_report_year_changed"):
        validate_plan(p, req, catalog(), PipelineConfig())
    p.companies[1].report_years = [2025]
    assert validate_plan(p, req, catalog(), PipelineConfig())
    with pytest.raises(ValidationError):
        Request(question="ACME收入", as_of="2026-10-11", confirmed_context={"sql": "arbitrary"})
    with pytest.raises(ValidationError):
        Request(question=" ", as_of="2026-10-11")


def test_planner_missing_field_repair_receives_schema_and_field_path(tmp_path):
    class Model:
        calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            if self.calls == 1:
                assert "response_contract" in messages[1]["content"]
                bad = plan().model_dump(mode="json")
                del bad["period_interpretation"]
                return {"answer": json.dumps(bad), "finish_reason": "stop"}
            assert self.calls == 2 and "period_interpretation" in messages[-1]["content"]
            return {"answer": plan().model_dump_json(), "finish_reason": "stop"}

    model = Model()
    fixed, event = plan_request(
        Request(question="ACME收入", as_of="2026-10-11"),
        catalog(),
        PipelineConfig(),
        model,
        tmp_path,
    )
    assert fixed.action == "retrieve" and event["repairs"] == 1


@pytest.mark.parametrize("row_count", [1, 2, 4])
def test_long_short_row_table_is_not_dropped_after_paragraph(row_count):
    text = "Revenue " + "100 " * 300
    table = "\n".join([text] * row_count)
    blocks = []
    cursor = 0
    for i, (kind, content) in enumerate([("text", "Introduction"), ("table", table)]):
        blocks.append(
            Block(
                id=f"b{i}",
                document_id=filing().id,
                ordinal=i,
                kind=kind,
                section="Item 8",
                text=content,
                start=cursor,
                end=cursor + len(content),
                locator={},
            )
        )
        cursor += len(content) + 2
    ix = IndexConfig(name="test", chunk_size=512, overlap=64)
    chunks = make_chunks(blocks, filing(), ix)
    validate_source_coverage(blocks, chunks)
    assert any("b1" in c.block_ids for c in chunks)
    with pytest.raises(ServingError, match="source_not_covered"):
        validate_source_coverage(blocks, [c for c in chunks if "b1" not in c.block_ids])


@pytest.mark.corpus
def test_existing_selected_corpus_reproduces_exact_chunk_payloads():
    from finrag.models import Filing

    rows = json.loads((ROOT / "configs/indexes.json").read_text())
    ix = IndexConfig(**next(r for r in rows if r["name"] == "structure_512_table_context"))
    expected = {
        r["id"]: r
        for r in read_jsonl(ROOT / "data/processed/structure_512_table_context.chunks.jsonl")
    }
    actual = {}
    for row in read_jsonl(ROOT / "data/sources.jsonl"):
        f = Filing(**row)
        blocks = [Block(**b) for b in read_jsonl(ROOT / f"data/processed/{f.id}.blocks.jsonl")]
        chunks = make_chunks(blocks, f, ix)
        validate_source_coverage(blocks, chunks)
        actual.update({c.id: c.model_dump() for c in chunks})
    assert actual == expected
