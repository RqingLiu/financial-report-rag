"""Token-bounded recursive and structure-aware chunking with source character spans."""

import json
import re
from functools import lru_cache
from itertools import pairwise

import tiktoken

from .files import digest
from .models import Block, Chunk, Filing, IndexConfig


@lru_cache
def tokenizer():
    return tiktoken.get_encoding("cl100k_base")


def token_count(text: str) -> int:
    # Explicit proxy tokenizer: not asserted to be Voyage's billing tokenizer.
    return len(tokenizer().encode(text, disallowed_special=()))


def config_id(config: IndexConfig) -> str:
    data = config.model_dump()
    # Preserve existing v2 identifiers when the optional enrichment is disabled.
    if not data["table_context"]:
        data.pop("table_context")
    return digest(json.dumps(data, separators=(",", ":")))[:16]


def split_text(text: str, size: int, overlap: int) -> list[tuple[str, int, int]]:
    """Recursive-character splitting carrying offsets throughout, never recovering via str.find.

    This explicit implementation follows separator recursion + overlapping merging, measuring
    the actual merged string with the proxy tokenizer. Repeated substrings remain unambiguous.
    """
    if not 0 <= overlap < size:
        raise ValueError("Invalid token overlap")
    result = []

    def emit(start, end):
        while start < end and text[start].isspace():
            start += 1
        while end > start and text[end - 1].isspace():
            end -= 1
        if start < end:
            result.append((text[start:end], start, end))

    def merge(parts):
        current = []
        for start, end in parts:
            if current and token_count(text[current[0][0] : end]) > size:
                emit(current[0][0], current[-1][1])
                while current and (
                    token_count(text[current[0][0] : current[-1][1]]) > overlap
                    or token_count(text[current[0][0] : end]) > size
                ):
                    current.pop(0)
            current.append((start, end))
        if current:
            emit(current[0][0], current[-1][1])

    def recurse(start, end, separators):
        if token_count(text[start:end]) <= size:
            emit(start, end)
            return
        chosen = next(i for i, sep in enumerate(separators) if not sep or sep in text[start:end])
        sep = separators[chosen]
        if sep:
            boundaries = sorted(
                {
                    start,
                    end,
                    *[start + m.start() for m in re.finditer(re.escape(sep), text[start:end])],
                }
            )
        else:
            boundaries = list(range(start, end + 1))
        pending = []
        for left, right in pairwise(boundaries):
            if token_count(text[left:right]) <= size:
                pending.append((left, right))
            else:
                merge(pending)
                pending = []
                recurse(left, right, separators[chosen + 1 :])
        merge(pending)

    recurse(0, len(text), ["\n\n", "\n", ". ", "; ", ", ", " ", ""])
    return result


def make_chunks(blocks: list[Block], filing: Filing, config: IndexConfig) -> list[Chunk]:
    canonical = "\n\n".join(b.text for b in blocks)
    ix = config_id(config)
    chunks = []

    def add(text: str, start: int, end: int, section: str, extra_spans=None):
        touching = [b for b in blocks if b.start < end and b.end > start]
        spans = [
            {"block_id": b.id, "start": max(start, b.start), "end": min(end, b.end)}
            for b in touching
        ]
        spans.extend(extra_spans or [])
        context = []
        if config.table_context:
            for block in touching:
                if block.kind != "table":
                    continue
                previous = blocks[max(0, block.ordinal - 3) : block.ordinal]
                context.extend(
                    b for b in previous if b.kind != "table" and token_count(b.text) <= 150
                )
                if "in millions" not in block.text.lower():
                    context.extend(
                        b
                        for b in blocks[: block.ordinal]
                        if "all tabular amounts in millions" in b.text.lower()
                        and token_count(b.text) <= 100
                    )
            context = list({b.id: b for b in context}.values())
            spans.extend({"block_id": b.id, "start": b.start, "end": b.end} for b in context)
            text = "\n".join([*[b.text for b in context], text])
        prefix = (
            f"Company: {filing.ticker}; fiscal year: {filing.fiscal_year}; "
            f"period end: {filing.period_end}; {section}; {filing.form}.\n"
        )
        embedded = prefix + text if config.contextual else text
        chunks.append(
            Chunk(
                id=f"{ix}:{filing.id}:c{len(chunks):04d}:{digest(text)[:8]}",
                document_id=filing.id,
                index_id=ix,
                section=section,
                text=text,
                embedding_text=embedded,
                tokens=token_count(embedded),
                spans=spans,
                block_ids=list(dict.fromkeys(s["block_id"] for s in spans)),
            )
        )

    if config.strategy == "recursive":
        for text, start, end in split_text(canonical, config.chunk_size, config.overlap):
            section = next(b.section for b in blocks if b.end > start)
            add(text, start, end, section)
        return chunks

    pending = []

    def flush():
        if not pending:
            return
        first, last = pending[0], pending[-1]
        text = canonical[first.start : last.end]
        for piece, start, end in split_text(text, config.chunk_size, config.overlap):
            add(piece, first.start + start, first.start + end, first.section)
        pending.clear()

    for block in blocks:
        if block.kind == "image":
            flush()
            continue
        if block.kind == "table":
            flush()
            if token_count(block.text) <= config.chunk_size:
                add(block.text, block.start, block.end, block.section)
                continue
            # Each source row is indivisible; repeat source header rows.
            lines = block.text.splitlines(keepends=True)
            header_lines = min(4, len(lines))
            header = "".join(lines[:header_lines])
            header_end = block.start + len(header)
            header_spans = [{"block_id": block.id, "start": block.start, "end": header_end}]
            cursor = header_end
            group, group_start = [], cursor
            for line in lines[header_lines:]:
                if group and token_count(header + "".join(group) + line) > config.chunk_size:
                    add(header + "".join(group), group_start, cursor, block.section, header_spans)
                    group, group_start = [], cursor
                group.append(line)
                cursor += len(line)
            if group:
                add(header + "".join(group), group_start, block.end, block.section, header_spans)
            else:
                # A short/fat table can consist entirely of the header heuristic.
                # Always retain it, even when preceding paragraphs already emitted chunks.
                add(block.text, block.start, block.end, block.section)
            continue
        if pending and (pending[-1].section != block.section or block.kind == "heading"):
            flush()
        pending.append(block)
    flush()
    return chunks
