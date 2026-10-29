"""Source-bound context construction; table expansion is retrieval-time, not new embeddings."""

from collections import OrderedDict

from .chunk import token_count
from .models import Block


class EvidenceStore:
    def __init__(self, repository, max_blocks=1000, max_characters=2000000):
        self.repository = repository
        self.cache = OrderedDict()
        self.max_blocks, self.max_characters = max_blocks, max_characters
        self.characters = 0

    def blocks(self, ids):
        requested = {key: self.cache[key] for key in ids if key in self.cache}
        for key in requested:
            self.cache.move_to_end(key)
        missing = list(set(ids) - requested.keys())
        if missing:
            if len(missing) > 1200:
                raise ValueError("source_block_batch_limit")
            # Context needs source text/spans, not large raw_html/grid copies.
            if hasattr(self.repository, "block_payloads"):
                rows = self.repository.block_payloads(missing)
            else:
                rows = self.repository.connection.execute(
                    "SELECT payload - 'structured' AS payload FROM finrag.blocks WHERE id=ANY(%s)",
                    (missing,),
                ).fetchall()
            for row in rows:
                block = Block(**row["payload"])
                requested[block.id] = block
                self.cache[block.id] = block
                self.characters += len(block.text)
                while self.cache and (
                    len(self.cache) > self.max_blocks or self.characters > self.max_characters
                ):
                    _, removed = self.cache.popitem(last=False)
                    self.characters -= len(removed.text)
            if set(ids) - requested.keys():
                raise ValueError("source_block_missing")
        return {key: requested[key] for key in ids}


def merged(intervals):
    out = []
    for start, end in sorted(intervals):
        if out and start <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], end))
        else:
            out.append((start, end))
    return out


def span_overlap(spans, already):
    size, overlap = 0, 0
    by_block = {}
    for s in spans:
        by_block.setdefault(s["block_id"], []).append((s["start"], s["end"]))
    for bid, intervals in by_block.items():
        for start, end in merged(intervals):
            size += end - start
            overlap += sum(
                max(0, min(end, b) - max(start, a)) for a, b in merged(already.get(bid, []))
            )
    return overlap / size if size else 0


def assemble(hit, store, filing, config):
    if not config.expand_tables:
        return hit, hit.chunk.embedding_text
    blocks = store.blocks(hit.chunk.block_ids)
    expandable = {
        bid
        for bid, b in blocks.items()
        if b.kind == "table" and token_count(b.text) <= config.max_table_tokens
    }
    if not expandable:
        return hit, hit.chunk.embedding_text
    prefix = (
        f"Company: {filing.ticker}; report FY: {filing.fiscal_year}; "
        f"period end: {filing.period_end}; filed: {filing.filed_at}; {filing.form}."
    )
    parts, added = [prefix], []
    for bid in dict.fromkeys(s["block_id"] for s in hit.chunk.spans):
        b = blocks[bid]
        if bid in expandable:
            parts.append(b.text)
            added.append({"block_id": bid, "start": b.start, "end": b.end})
        else:
            intervals = merged(
                (s["start"], s["end"]) for s in hit.chunk.spans if s["block_id"] == bid
            )
            parts.extend(b.text[start - b.start : end - b.start] for start, end in intervals)
    return hit.model_copy(update={"expanded_spans": added}), "\n\n".join(parts)


def build_context(ranked, provenance, store, filings, config, *, plan=None, search_records=None):
    if config.context_strategy == "need_budget":
        from .need_context import build_need_context

        return build_need_context(ranked, store, filings, config, plan, search_records)
    by_id = {f.id: f for f in filings}
    pool = ranked[: config.context_candidate_limit]
    # Fetch only the candidate blocks considered by this context build, never the whole corpus.
    if config.expand_tables:
        store.blocks(list({bid for h in pool for bid in h.chunk.block_ids}))
    contexts = {}
    selected, texts, decisions = [], {}, []
    used, covered_tasks, covered_docs, covered_spans = 0, set(), set(), {}
    remaining = list(pool)
    while remaining and len(selected) < config.context_k:

        def utility(hit):
            records = provenance[hit.chunk.id]
            rank = min(p["task_rank"] for p in records)
            new_tasks = {
                p["task_id"] for p in records if p["task_rank"] <= config.coverage_rank_depth
            } - covered_tasks
            new_doc = hit.chunk.document_id not in covered_docs
            coverage = (
                (
                    config.task_coverage_bonus * len(new_tasks)
                    + config.period_coverage_bonus * new_doc
                )
                if config.context_strategy == "coverage"
                else 0
            )
            return 1 / (5 + rank) + coverage

        if config.context_strategy == "coverage":
            remaining.sort(key=lambda h: (-utility(h), h.chunk.id))
        hit = remaining.pop(0)
        if span_overlap(hit.chunk.spans, covered_spans) >= config.overlap_threshold:
            decisions.append({"chunk_id": hit.chunk.id, "decision": "source_overlap"})
            continue
        if hit.chunk.id not in contexts:
            contexts[hit.chunk.id] = assemble(hit, store, by_id[hit.chunk.document_id], config)
        expanded, text = contexts[hit.chunk.id]
        cost = token_count(text)
        expansion_applied = bool(expanded.expanded_spans)
        if used + cost > config.context_tokens and expansion_applied:
            expanded, text = hit, hit.chunk.embedding_text
            cost, expansion_applied = token_count(text), False
        if used + cost > config.context_tokens:
            decisions.append(
                {"chunk_id": hit.chunk.id, "decision": "context_budget", "tokens": cost}
            )
            continue
        selected.append(expanded)
        texts[hit.chunk.id] = text
        used += cost
        covered_tasks.update(
            p["task_id"]
            for p in provenance[hit.chunk.id]
            if p["task_rank"] <= config.coverage_rank_depth
        )
        covered_docs.add(hit.chunk.document_id)
        for s in [*expanded.chunk.spans, *expanded.expanded_spans]:
            covered_spans.setdefault(s["block_id"], []).append((s["start"], s["end"]))
        decisions.append(
            {
                "chunk_id": hit.chunk.id,
                "decision": "selected",
                "tokens": cost,
                "expanded_table": expansion_applied,
            }
        )
    decisions.extend(
        {"chunk_id": h.chunk.id, "decision": "top_k_or_candidate_window"} for h in remaining
    )
    return (
        selected,
        texts,
        {
            "context_proxy_tokens": used,
            "decisions": decisions,
            "considered_candidates": len(pool),
            "covered_task_ids": sorted(covered_tasks),
        },
    )
