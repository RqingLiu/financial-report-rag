import pytest
from lxml import html

from finrag.core.config import ROOT
from finrag.core.files import read_jsonl
from finrag.core.models import Block, Chunk, Evidence, Filing, Hit, IndexConfig
from finrag.evaluation.evidence import covers
from finrag.ingestion.chunk import config_id, make_chunks, split_text, token_count
from finrag.ingestion.parse import load_blocks, table_data


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


def test_reference_format_uses_ragas_schema():
    from ragas import EvaluationDataset

    data = EvaluationDataset.from_jsonl(
        str(ROOT / "data/evaluation/golden_v2/evaluation_dataset.jsonl")
    )
    assert len(data) == 20
