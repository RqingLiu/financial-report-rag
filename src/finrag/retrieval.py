"""Retrieval service: explicit scope, RRF, group coverage, and bounded source expansion."""

import json
import re
from pathlib import Path

from .chunk import config_id, token_count
from .files import atomic_json, read_jsonl
from .models import Filing, Hit, IndexConfig, RetrievalConfig
from .parse import load_blocks
from .query import domain_query
from .ranking import interleave  # re-export for legacy callers
from .tree import export_trees

ALIASES = {
    "NVDA": r"\bNVDA\b|\bNVIDIA\b|英伟达",
    "MU": r"\bMU\b|\bMicron\b|美光",
    "AMD": r"\bAMD\b|超微",
}


def resolve_scope(question: str, filings: list[Filing], as_of: str) -> list[str]:
    """Derive filters solely from question text. Never consume golden document/evidence IDs."""
    mentions = sorted(
        (m.start(), m.end(), ticker)
        for ticker, pattern in ALIASES.items()
        for m in re.finditer(pattern, question, flags=re.IGNORECASE)
    )
    years = {int(y) for y in re.findall(r"(?<!\d)20\d{2}(?!\d)", question)}
    wanted = set()
    for i, (start, end, ticker) in enumerate(mentions):
        next_start = mentions[i + 1][0] if i + 1 < len(mentions) else len(question)
        local = {int(y) for y in re.findall(r"(?<!\d)20\d{2}(?!\d)", question[end:next_start])}
        for f in filings:
            if f.ticker == ticker and (not (local or years) or f.fiscal_year in (local or years)):
                wanted.add(f.id)
    if not mentions:
        wanted = {f.id for f in filings if not years or f.fiscal_year in years}
    wanted = {f.id for f in filings if f.id in wanted and f.filed_at <= as_of}
    # An amendment is additive evidence, never a replacement for the entire original filing.
    wanted.update(f.id for f in filings if f.amends_document_id in wanted and f.filed_at <= as_of)
    return sorted(wanted)


def rrf(rankings: list[list[Hit]], c: int = 60) -> list[Hit]:
    scores, hits = {}, {}
    for ranking in rankings:
        seen = set()
        for rank, hit in enumerate(ranking, 1):
            key = hit.chunk.id
            if key in seen:
                continue
            seen.add(key)
            scores[key] = scores.get(key, 0) + 1 / (c + rank)
            hits[key] = hit
    return [
        hits[key].model_copy(update={"score": scores[key], "method": "rrf"})
        for key in sorted(hits, key=lambda k: (-scores[k], k))
    ]




class Retriever:
    def __init__(self, root: Path, repository, embedder):
        self.root, self.repository, self.embedder = root, repository, embedder
        self.filings = [Filing(**r) for r in read_jsonl(root / "data/sources.jsonl")]
        self.blocks = load_blocks(root)
        self.by_block = {b.id: b for blocks in self.blocks.values() for b in blocks}
        self.indexes = {
            c.name: c
            for c in (
                IndexConfig(**r) for r in json.loads((root / "configs/indexes.json").read_text())
            )
        }
        self.trees = {t["document_id"]: t for t in export_trees(root, self.filings, self.blocks)}

    def _search(self, query, vector, config, documents, as_of):
        ix = config_id(self.indexes[config.index_name])
        methods = []
        if config.method in ("dense", "hybrid", "tree"):
            methods.append(
                self.repository.search(ix, documents, as_of, config.dense_k, vector=vector)
            )
        if config.method in ("fts", "hybrid"):
            methods.append(self.repository.search(ix, documents, as_of, config.fts_k, query=query))
        if config.method == "tree":
            # Upstream Markdown tree construction; this router is our own vector-assisted baseline.
            candidates = self.repository.search(
                ix, documents, as_of, max(120, config.dense_k), vector=vector
            )
            ranks = {}
            membership = {}
            for doc in documents:
                for node in self.trees[doc]["source_nodes"]:
                    key = (doc, node["node_id"])
                    for bid in node["block_ids"]:
                        membership[bid] = key
            for rank, hit in enumerate(candidates, 1):
                for key in {membership[b] for b in hit.chunk.block_ids if b in membership}:
                    ranks[key] = ranks.get(key, 0) + 1 / (30 + rank)
            selected = sorted(ranks, key=lambda s: (-ranks[s], s))[: config.tree_sections]
            return [
                hit
                for hit in candidates
                if any(membership.get(b) in selected for b in hit.chunk.block_ids)
            ][: config.dense_k]
        return rrf(methods, config.rrf_c) if config.method == "hybrid" else methods[0]

    def retrieve(
        self, question: str, config: RetrievalConfig, k=20, question_en=None, as_of="2026-10-11"
    ):
        query = question_en if config.query_language == "english" else question
        if not query:
            raise ValueError("English-rewrite experiment requires explicit question_en")
        if config.domain_query:
            query = domain_query(query)
        documents = resolve_scope(question, self.filings, as_of)
        if not documents:
            return [], {"scope": [], "reason": "requested_period_not_in_corpus"}
        vector = (
            self.embedder.embed([query], input_type="query")[0] if config.method != "fts" else None
        )
        grouped = {}
        for f in self.filings:
            if f.id in documents:
                grouped.setdefault((f.ticker, f.fiscal_year), []).append(f.id)
        groups = list(grouped.values()) if config.grouped else [documents]
        rankings = [self._search(query, vector, config, group, as_of) for group in groups]
        hits = interleave(rankings) if config.grouped else rankings[0]
        result, used, expanded = [], 0, set()
        for hit in hits:
            if len(result) >= k:
                break
            cost = hit.chunk.tokens
            expansion = []
            if config.expand_parent:
                # Expand touched source paragraphs/tables only; never the entire Item/annual report.
                for bid in hit.chunk.block_ids:
                    block = self.by_block[bid]
                    if block.kind == "table" or token_count(block.text) <= 1200:
                        expansion.append({"block_id": bid, "start": block.start, "end": block.end})
                    if block.kind == "table":
                        previous = self.blocks[block.document_id][
                            max(0, block.ordinal - 3) : block.ordinal
                        ]
                        for prior in previous:
                            if prior.kind != "table" and token_count(prior.text) <= 150:
                                expansion.append(
                                    {"block_id": prior.id, "start": prior.start, "end": prior.end}
                                )
                        # Some issuers put the unit basis at the start of all financial notes.
                        if "in millions" not in block.text.lower():
                            basis = next(
                                (
                                    b
                                    for b in self.blocks[block.document_id][: block.ordinal]
                                    if "all tabular amounts in millions" in b.text.lower()
                                    and token_count(b.text) <= 100
                                ),
                                None,
                            )
                            if basis:
                                expansion.append(
                                    {"block_id": basis.id, "start": basis.start, "end": basis.end}
                                )
                expansion = list({s["block_id"]: s for s in expansion}.values())
                expansion = [s for s in expansion if s["block_id"] not in expanded]
                candidate = hit.model_copy(update={"expanded_spans": expansion})
                cost = token_count(self.context_text(candidate))
            if used + cost > config.context_budget_tokens:
                continue
            used += cost
            result.append(hit.model_copy(update={"expanded_spans": expansion}))
            expanded.update(s["block_id"] for s in expansion)
        return result, {
            "scope": documents,
            "query": query,
            "context_proxy_tokens": used,
            "candidate_count": len(hits),
            "returned": len(result),
        }

    def context_text(self, hit: Hit):
        return "\n\n".join(
            [
                hit.chunk.embedding_text,
                *[self.by_block[s["block_id"]].text for s in hit.expanded_spans],
            ]
        )

    def export_tree(self):
        trees = []
        for filing in self.filings:
            nodes = []
            for block in self.blocks[filing.id]:
                if not nodes or nodes[-1]["title"] != block.section:
                    nodes.append(
                        {
                            "title": block.section,
                            "start": block.start,
                            "end": block.end,
                            "block_ids": [],
                        }
                    )
                nodes[-1]["end"] = block.end
                nodes[-1]["block_ids"].append(block.id)
            trees.append({"document_id": filing.id, "nodes": nodes})
        atomic_json(self.root / "data/processed/section_trees.json", trees)
