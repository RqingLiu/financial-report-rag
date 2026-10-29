import pytest
from lxml import html

from finrag.chunk import config_id, make_chunks, split_text, token_count
from finrag.config import ROOT
from finrag.dataset import load_questions, validate_questions
from finrag.evaluation import covers, score
from finrag.files import read_jsonl
from finrag.models import Block, Chunk, Evidence, Filing, Hit, IndexConfig
from finrag.parse import load_blocks, table_data
from finrag.query import domain_query, query_policy
from finrag.retrieval import interleave, resolve_scope, rrf
from finrag.tree import build_source_tree


@pytest.fixture(scope="module")
def filings():
    return [Filing(**r) for r in read_jsonl(ROOT / "data/sources.jsonl")]


def block(ordinal, text, start=0, kind="text"):
    return Block(
        id=f"b{ordinal}",
        document_id="x",
        ordinal=ordinal,
        kind=kind,
        section="Item 8",
        text=text,
        start=start,
        end=start + len(text),
        locator={},
    )


def hit(id, start, end, doc="x", bid="b0", expanded=None):
    return Hit(
        chunk=Chunk(
            id=id,
            document_id=doc,
            index_id="ix",
            section="Item 8",
            text="x",
            embedding_text="x",
            tokens=1,
            spans=[{"block_id": bid, "start": start, "end": end}],
            block_ids=[bid],
        ),
        score=0.5,
        method="dense",
        expanded_spans=expanded or [],
    )


def test_recall_requires_complete_quote_and_correct_document():
    e = Evidence(document_id="x", block_id="b0", quote="0123456789", start=0, end=10)
    assert not covers(e, [hit("a", 0, 8)])
    assert not covers(e, [hit("a", 0, 10, doc="wrong")])
    assert not covers(e, [hit("a", 0, 4), hit("b", 5, 10)])
    assert covers(e, [hit("a", 0, 6), hit("b", 5, 10)])
    assert covers(e, [hit("a", 2, 3, expanded=[{"block_id": "b0", "start": 0, "end": 10}])])


def test_rrf_missing_rank_and_duplicate_are_not_rewarded():
    a, b = hit("a", 0, 1), hit("b", 0, 1)
    merged = rrf([[a, a, b], [b]])
    assert merged[0].chunk.id == "b"
    assert merged[0].score == pytest.approx(1 / 63 + 1 / 61)
    assert merged[1].score == pytest.approx(1 / 61)
    assert [h.chunk.id for h in interleave([[a, b], [a]])] == ["a", "b"]


def test_scope_uses_question_dates_and_additive_amendment(filings):
    ids = resolve_scope("比较 NVIDIA FY2024和FY2026 的供应链", filings, "2026-10-11")
    assert ids == ["NVDA_FY2024", "NVDA_FY2026"]
    assert resolve_scope("NVDA FY2026", filings, "2026-01-01") == []
    ids = resolve_scope("MU FY2024 与 AMD FY2025 的收入", filings, "2026-10-11")
    assert "MU_FY2024" in ids and "MU_FY2025" not in ids
    assert "AMD_FY2025" in ids and any("_A_" in d for d in ids)


def test_source_table_keeps_merged_cells_and_negative_signs():
    raw = '<table><tr><th rowspan="2">Revenue</th><th colspan="2">2025</th></tr><tr><td>$</td><td>(123)</td></tr></table>'
    result = table_data(html.fromstring(raw))
    assert result["rows"] == [["Revenue", "2025", "2025"], ["Revenue", "$", "(123)"]]
    assert result["source_rows"] == [["Revenue", "2025"], ["$", "(123)"]]


def test_recursive_offsets_with_repeated_sentences():
    text = "Repeated phrase. " * 100 + "\n\n" + "Distinct ending. " * 40
    pieces = split_text(text, 80, 15)
    assert len(pieces) > 2
    assert all(text[s:e] == piece and token_count(piece) <= 80 for piece, s, e in pieces)
    assert pieces[0][1] == 0 and pieces[-1][2] == len(text.rstrip())


@pytest.mark.corpus
def test_table_context_is_actual_source_and_does_not_add_qa_labels(filings):
    blocks = load_blocks(ROOT)["NVDA_FY2026"]
    f = next(f for f in filings if f.id == "NVDA_FY2026")
    ix = IndexConfig(name="fixture", chunk_size=512, overlap=64, table_context=True)
    chunks = make_chunks(blocks, f, ix)
    income = next(c for c in chunks if any(s["block_id"] == blocks[706].id for s in c.spans))
    assert "Consolidated Statements of Income" in income.text
    assert "(In millions, except per share data)" in income.text
    assert blocks[705].id in income.block_ids
    assert "参考答案" not in income.embedding_text


def test_config_version_changes_for_enrichment():
    plain = IndexConfig(name="x", chunk_size=512, overlap=64)
    assert config_id(plain) != config_id(plain.model_copy(update={"table_context": True}))


def test_bilingual_glossary_preserves_filing_scope_separation():
    rewritten = domain_query("AMD FY2024 合并收入是多少？")
    assert "consolidated statements" in rewritten and "revenue" in rewritten
    assert "25,785" not in rewritten and "FY2024" not in rewritten
    assert domain_query("AMD HBM 封装具体怎么做") == "AMD HBM 封装具体怎么做"


@pytest.mark.corpus
def test_pageindex_tree_uses_real_source_block_mapping(filings):
    f = filings[0]
    tree = build_source_tree(f, load_blocks(ROOT)[f.id])
    assert tree["structure"][0]["title"] == f.id
    children = tree["structure"][0]["nodes"]
    assert any(n["title"] == "Item 1A" for n in children)
    mapped = [bid for n in tree["source_nodes"] for bid in n["block_ids"]]
    assert len(mapped) == len(set(mapped)) == len(load_blocks(ROOT)[f.id])


@pytest.mark.corpus
def test_frozen_annotations_have_no_family_leakage():
    qs = load_questions(ROOT, "all")
    validate_questions(qs, load_blocks(ROOT))
    assert len(qs) == 60
    assert {q.family for q in qs if q.split == "dev"}.isdisjoint(
        {q.family for q in qs if q.split == "test"}
    )
    assert all(q.review_status == "gpt_source_checked_pending_human" for q in qs)


def test_metric_excludes_boundary_and_requires_each_comparison_source():
    q = load_questions(ROOT, "dev")[9]
    assert len(q.documents) == 3
    e = q.evidence_groups[0][0]
    assert score(q, [hit("a", e.start, e.end, doc=e.document_id, bid=e.block_id)])["recall"] < 1
    boundary = next(q for q in load_questions(ROOT, "dev") if q.outcome != "answer")
    with pytest.raises(ValueError):
        score(boundary, [])


@pytest.mark.parametrize(
    ("question", "outcome"),
    [
        ("请分析最近的表现", "clarify"),
        ("TSM FY2024 收入", "insufficient_evidence"),
        ("NVDA FY2040 收入", "insufficient_evidence"),
        ("NVDA FY2025 的制造模式", "retrieve"),
    ],
)
def test_input_scope_policy(question, outcome, filings):
    assert query_policy(question, filings, "2026-10-11")["outcome"] == outcome


def test_reference_format_uses_ragas_schema():
    from ragas import EvaluationDataset

    data = EvaluationDataset.from_jsonl(str(ROOT / "data/evaluation/ragas_reference.jsonl"))
    assert len(data) == 60
