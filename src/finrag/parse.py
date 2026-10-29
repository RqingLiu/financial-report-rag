"""SEC HTML to stable source blocks, keeping financial tables and DOM locators."""

import re
from collections import Counter
from pathlib import Path

from lxml import etree, html

from .files import atomic_json, digest, read_jsonl, write_jsonl
from .models import Block, Filing

BLOCK_TAGS = {"div", "p", "li", "table", "h1", "h2", "h3", "h4", "h5", "h6"}
ITEM = re.compile(r"^Item\s+(\d{1,2}[A-C]?)\s*[.:]?\s*(.*)$", re.IGNORECASE)
WHITESPACE = re.compile(r"\s+")


def normalize(text: str) -> str:
    return WHITESPACE.sub(" ", text.replace("\xa0", " ")).strip()


def text_content(element) -> str:
    return normalize(" ".join(element.itertext()))


def table_data(element) -> dict:
    """Expand merged cells, preserving labels, blanks, signs, and raw cell strings."""
    grid, source_rows = [], []
    occupied = {}
    rows = [r for r in element.iter("tr") if next(r.iterancestors("table"), None) is element]
    for ri, row in enumerate(rows):
        values, ci, originals = [], 0, []
        for cell in row:
            if cell.tag not in ("td", "th"):
                continue
            while (ri, ci) in occupied:
                values.append(occupied[(ri, ci)])
                ci += 1
            value = text_content(cell)
            originals.append(value)
            cols = max(1, min(int(cell.get("colspan", "1")), 100))
            spans = max(1, min(int(cell.get("rowspan", "1")), 100))
            for offset in range(cols):
                values.append(value)
                for rr in range(ri + 1, ri + spans):
                    occupied[(rr, ci + offset)] = value
            ci += cols
        while (ri, ci) in occupied:
            values.append(occupied[(ri, ci)])
            ci += 1
        if any(values):
            grid.append(values)
            source_rows.append(originals)
    return {
        "rows": grid,
        "raw_html": etree.tostring(element, encoding="unicode"),
        "source_rows": source_rows,
        "header_rows": grid[: min(4, len(grid))],
    }


def parse_html(raw: bytes, filing: Filing) -> list[Block]:
    root = html.fromstring(raw)
    for node in list(root.iter()):
        tag = str(node.tag).lower()
        style = re.sub(r"\s+", "", node.get("style", "").lower())
        if tag in ("script", "style", "noscript", "ix:header", "ix:hidden") or (
            "display:none" in style or "visibility:hidden" in style
        ):
            node.drop_tree()
    body = root.find("body")
    if body is None:
        body = root
    tree = root.getroottree()
    outputs = []

    def emit(element, text: str, kind: str, structured=None):
        text = normalize(text) if kind != "table" else text.strip()
        if not text or (kind != "table" and re.fullmatch(r"\d{1,3}", text)):
            return
        anchor = next(
            (n.get("id") for n in [element, *element.iterancestors()] if n.get("id")), None
        )
        outputs.append(
            (text, kind, {"xpath": tree.getpath(element), "anchor": anchor}, structured or {})
        )

    def walk(element):
        if not isinstance(element.tag, str):
            return
        if element.tag == "table":
            structure = table_data(element)
            # The structured grid expands merged cells; readable text must not repeat them.
            rendered = "\n".join(" | ".join(r) for r in structure["source_rows"])
            if rendered:
                emit(element, rendered, "table", structure)
            return
        if element.tag == "img":
            emit(
                element,
                element.get("alt") or f"[Image: {element.get('src', '')}]",
                "image",
                {
                    "src": element.get("src"),
                    "alt": element.get("alt"),
                    "warning": "image_not_ocr_verified",
                },
            )
            return
        descendants = [n for n in element.iterdescendants() if n.tag in BLOCK_TAGS]
        if element.tag in BLOCK_TAGS and not descendants:
            emit(element, text_content(element), "text")
            for image in element.iter("img"):
                walk(image)
            return
        inline = [element.text or ""]
        for child in element:
            if (
                child.tag in BLOCK_TAGS
                or child.tag == "img"
                or any(n.tag in BLOCK_TAGS for n in child.iterdescendants())
            ):
                emit(element, " ".join(inline), "text")
                inline = []
                walk(child)
            else:
                inline.append(text_content(child))
            inline.append(child.tail or "")
        emit(element, " ".join(inline), "text")

    walk(body)
    blocks, cursor, section = [], 0, "Cover"
    for text, kind, locator, structured in outputs:
        match = ITEM.match(text) if len(text) < 280 and kind != "table" else None
        if match:
            section = f"Item {match.group(1).upper()}"
            kind = "heading"
        ordinal = len(blocks)
        block = Block(
            id=f"{filing.id}:b{ordinal:04d}:{digest(text)[:10]}",
            document_id=filing.id,
            ordinal=ordinal,
            kind=kind,
            section=section,
            text=text,
            start=cursor,
            end=cursor + len(text),
            locator=locator,
            structured=structured,
        )
        blocks.append(block)
        cursor = block.end + 2
    if cursor < 10000:
        raise ValueError(f"{filing.id}: unexpectedly short extraction: {cursor} chars")
    return blocks


def parse_all(root: Path):
    summaries = []
    for row in read_jsonl(root / "data/sources.jsonl"):
        filing = Filing(**row)
        raw_path = root / f"data/raw/{filing.id}.html"
        raw = raw_path.read_bytes()
        if filing.sha256 and filing.sha256 != digest(raw):
            raise ValueError(f"Raw file checksum mismatch: {filing.id}")
        blocks = parse_html(raw, filing)
        write_jsonl(
            root / f"data/processed/{filing.id}.blocks.jsonl", [b.model_dump() for b in blocks]
        )
        text = "\n\n".join(b.text for b in blocks)
        (root / f"data/processed/{filing.id}.txt").write_text(text)
        sections = Counter(b.section for b in blocks)
        summaries.append(
            {
                "document_id": filing.id,
                "characters": len(text),
                "blocks": len(blocks),
                "kinds": dict(Counter(b.kind for b in blocks)),
                "sections": dict(sections),
                "raw_sha256": digest(raw),
                "warnings": ["Images retained as source records; OCR not performed"],
                "parser": "sec-html-v2",
            }
        )
        print(f"parsed {filing.id}: {len(blocks)} blocks, {len(text):,} chars", flush=True)
    atomic_json(root / "reports/parse_audit.json", summaries)


def load_blocks(root: Path) -> dict[str, list[Block]]:
    return {
        r["id"]: [Block(**b) for b in read_jsonl(root / f"data/processed/{r['id']}.blocks.jsonl")]
        for r in read_jsonl(root / "data/sources.jsonl")
    }
