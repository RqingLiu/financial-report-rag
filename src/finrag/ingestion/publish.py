"""Trusted local HTML publisher. Network acquisition remains the existing SEC workflow."""

from datetime import date

from finrag.core.files import digest
from finrag.ingestion.chunk import make_chunks
from finrag.ingestion.parse import parse_html
from finrag.serving.errors import ServingError


def validate_source_coverage(blocks, chunks):
    """Non-whitespace parsed source text must not silently disappear before embedding."""
    intervals = {}
    for chunk in chunks:
        for span in chunk.spans:
            intervals.setdefault(span["block_id"], []).append((span["start"], span["end"]))
    for block in blocks:
        if block.kind == "image":
            continue
        cursor = block.start
        for start, end in sorted(intervals.get(block.id, [])):
            if block.text[cursor - block.start : max(cursor, start) - block.start].strip():
                raise ServingError("parsed_source_not_covered_by_chunks")
            cursor = max(cursor, end)
        if block.text[cursor - block.start :].strip():
            raise ServingError("parsed_source_not_covered_by_chunks")


def ingest_html(path, filing, store, embedder, company=None):
    limit = store.config.max_raw_bytes
    if path.stat().st_size > limit:
        raise ServingError("raw_file_size_limit")
    raw = path.read_bytes()
    if len(raw) > limit:
        raise ServingError("raw_file_size_limit")
    if filing.sha256 and digest(raw) != filing.sha256:
        raise ServingError("raw_checksum_mismatch")
    for value in (filing.filed_at, filing.period_end):
        date.fromisoformat(value)
    if filing.form not in ("10-K", "10-K/A"):
        raise ServingError("only_sec_10k_html_supported")
    filing = filing.model_copy(update={"sha256": digest(raw)})
    if company and company.get("ticker") != filing.ticker:
        raise ServingError("company_identity_mismatch")
    previous = store.preflight(filing)
    if previous:
        return previous
    blocks = parse_html(raw, filing)
    chunks = make_chunks(blocks, filing, store.index_config)
    if not chunks or len(chunks) > store.config.max_document_chunks:
        raise ServingError("document_chunk_resource_limit")
    validate_source_coverage(blocks, chunks)
    # Cache and API batches are document-local; nothing becomes visible before vectors succeed.
    vectors = embedder.embed([c.embedding_text for c in chunks], input_type="document")
    return store.publish(filing, blocks, chunks, vectors, company)
