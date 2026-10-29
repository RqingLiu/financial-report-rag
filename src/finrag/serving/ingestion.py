"""Trusted local HTML publisher. Network acquisition remains the existing SEC workflow."""

import json
from datetime import date

from ..chunk import config_id, make_chunks
from ..files import digest
from ..models import Filing
from ..parse import parse_html
from .errors import ServingError


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


def bootstrap_legacy(store, legacy, companies):
    """Copy one existing version, document at a time. No model calls, no frozen writes."""
    ix = config_id(store.index_config)
    rows = legacy.connection.execute(
        "SELECT d.metadata FROM finrag.documents d WHERE EXISTS "
        "(SELECT 1 FROM finrag.chunks c WHERE c.document_id=d.id AND c.index_id=%s) "
        "ORDER BY d.id",
        (ix,),
    ).fetchall()
    results = []
    registry = {r["ticker"]: r for r in companies}
    for row in rows:
        f = Filing(**row["metadata"])
        chunks = legacy.connection.execute(
            "SELECT payload,embedding::text AS vector "
            "FROM finrag.chunks WHERE document_id=%s AND index_id=%s ORDER BY id",
            (f.id, ix),
        ).fetchall()
        # Legacy source table can contain superseded parser block IDs. Only bootstrap
        # the current source generation, and verify it produces the copied chunk payloads.
        from ..config import ROOT

        raw = (ROOT / "data/raw" / (f.id + ".html")).read_bytes()
        if f.sha256 and digest(raw) != f.sha256:
            raise ServingError("bootstrap_source_checksum_mismatch")
        current_blocks = parse_html(raw, f)
        current_chunks = make_chunks(current_blocks, f, store.index_config)
        if {c.id: c.model_dump() for c in current_chunks} != {
            r["payload"]["id"]: r["payload"] for r in chunks
        }:
            raise ServingError("bootstrap_parser_differs_from_frozen_chunks")
        from ..models import Chunk

        result = store.publish(
            f,
            current_blocks,
            [Chunk(**r["payload"]) for r in chunks],
            [json.loads(r["vector"]) for r in chunks],
            registry.get(f.ticker),
        )
        results.append(result)
        print(json.dumps(result), flush=True)
    return results
