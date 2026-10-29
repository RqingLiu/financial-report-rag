"""Check source DOM, canonical evidence spans, persisted chunks, and corpus checksums."""

from collections import Counter

from lxml import html

from .dataset import load_questions, validate_questions
from .files import atomic_json, digest, read_jsonl, write_jsonl
from .models import Chunk, Filing
from .parse import load_blocks, normalize


def source_audit(root):
    blocks = load_blocks(root)
    filings = [Filing(**r) for r in read_jsonl(root / "data/sources.jsonl")]
    questions = load_questions(root, "all")
    validate_questions(questions, blocks)
    checks, review = [], []
    for f in filings:
        raw = (root / f"data/raw/{f.id}.html").read_bytes()
        if digest(raw) != f.sha256:
            raise ValueError(f"Raw checksum mismatch {f.id}")
        # Same DOM cleanup as parser is required for stable XPath; remove hidden records only.
        tree = html.fromstring(raw)
        import re

        for node in list(tree.iter()):
            style = re.sub(r"\s+", "", node.get("style", "").lower())
            if (
                str(node.tag).lower() in ("script", "style", "noscript", "ix:header", "ix:hidden")
                or "display:none" in style
                or "visibility:hidden" in style
            ):
                node.drop_tree()
        source_evidence = [
            e
            for q in questions
            for group in q.evidence_groups
            for e in group
            if e.document_id == f.id
        ]
        for e in source_evidence:
            b = next(b for b in blocks[f.id] if b.id == e.block_id)
            xpath = re.sub(r"/([\w.-]+:[\w.-]+)", r"/*[name()='\1']", b.locator["xpath"])
            nodes = tree.xpath(xpath)
            if len(nodes) != 1:
                raise ValueError(f"Unresolved source XPath {b.id}")
            dom_text = normalize(" ".join(nodes[0].itertext()))
            # Serialized table rows introduce pipes absent in the HTML; verify ordered cell text.
            pieces = [normalize(x) for x in e.quote.replace("\n", " | ").split("|") if normalize(x)]
            cursor = 0
            for part in pieces:
                pos = dom_text.find(part, cursor)
                if pos < 0:
                    raise ValueError(f"Quoted source text missing from DOM: {b.id}: {part[:80]}")
                cursor = pos + len(part)
        checks.append(
            {
                "document_id": f.id,
                "bytes": len(raw),
                "sha256": f.sha256,
                "evidence_quotes_checked": len(source_evidence),
                "raw_images": len(tree.xpath("//img")),
                "parsed_image_records": sum(b.kind == "image" for b in blocks[f.id]),
                "image_limitation": "Table-embedded images remain in raw HTML; no vision/OCR scoring",
            }
        )
    for q in questions:
        review.append(
            {
                "id": q.id,
                "split": q.split,
                "question": q.question,
                "reference": q.reference,
                "review_status": q.review_status,
                "derivation": q.derivation,
                "evidence": [
                    [
                        {
                            "quote": e.quote,
                            "document_id": e.document_id,
                            "source_url": next(
                                f.source_url for f in filings if f.id == e.document_id
                            ),
                            "locator": next(
                                b.locator for b in blocks[e.document_id] if b.id == e.block_id
                            ),
                        }
                        for e in g
                    ]
                    for g in q.evidence_groups
                ],
            }
        )
    chunk_checks = []
    for path in sorted((root / "data/processed").glob("*.chunks.jsonl")):
        chunks = [Chunk(**r) for r in read_jsonl(path)]
        ranges = {}
        for c in chunks:
            for s in c.spans:
                b = next(b for b in blocks[c.document_id] if b.id == s["block_id"])
                quote = b.text[s["start"] - b.start : s["end"] - b.start]
                if not b.start <= s["start"] < s["end"] <= b.end or quote not in c.text:
                    raise ValueError(f"Unfaithful chunk source mapping {c.id}")
                ranges.setdefault(b.id, []).append((s["start"] - b.start, s["end"] - b.start))
        missing = []
        for document in blocks.values():
            for b in document:
                if b.kind == "image":
                    continue
                covered = bytearray(len(b.text))
                for start, end in ranges.get(b.id, []):
                    covered[start:end] = b"\1" * (end - start)
                count = sum(
                    not marked and not char.isspace() for marked, char in zip(covered, b.text)
                )
                if count:
                    missing.append({"block_id": b.id, "non_whitespace_characters": count})
        if missing:
            raise ValueError(f"Index silently dropped source text: {path.stem}: {missing[:5]}")
        chunk_checks.append(
            {
                "index": path.stem,
                "chunks": len(chunks),
                "source_spans_verified": True,
                "non_image_text_fully_covered": True,
                "max_proxy_tokens": max(c.tokens for c in chunks),
            }
        )
    result = {
        "documents": checks,
        "indexes": chunk_checks,
        "questions": len(questions),
        "mandatory_groups": sum(len(q.evidence_groups) for q in questions),
        "all_evidence_resolves_to_raw_dom": True,
        "annotation_review": "Source presence checked mechanically; semantic correctness still needs human review",
        "outcomes": dict(Counter(q.outcome for q in questions)),
    }
    atomic_json(root / "reports/source_audit.json", result)
    write_jsonl(root / "data/evaluation/review_packets.jsonl", review)
    return result
