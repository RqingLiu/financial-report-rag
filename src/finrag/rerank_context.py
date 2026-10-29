"""Source-only context extraction with evidence AND full serialized-prompt budgets."""

import json
from collections import defaultdict

from .answering import answer_messages
from .chunk import token_count
from .context import assemble, merged, span_overlap
from .files import digest
from .planning import PlanRejected
from .reranking import source_lines


def fetch_blocks(hits, store):
    ids = sorted({bid for hit in hits for bid in hit.chunk.block_ids})
    blocks = {}
    for start in range(0, len(ids), 200):
        blocks.update(store.blocks(ids[start : start + 200]))
    return blocks


def candidates_for_rerank(hits, blocks, filings):
    result = []
    for hit in hits:
        filing = filings[hit.chunk.document_id]
        result.append(
            {
                "chunk_id": hit.chunk.id,
                "source": {
                    "ticker": filing.ticker,
                    "report_fy": filing.fiscal_year,
                    "period_end": filing.period_end,
                    "filed_at": filing.filed_at,
                    "section": hit.chunk.section,
                },
                "lines": [line["text"] for line in source_lines(hit, blocks)],
            }
        )
    return result


def compact_source(hit, grade, blocks, filing):
    lines = source_lines(hit, blocks)
    wanted = sorted({i - 1 for start, end in grade["l"] for i in range(start, end + 1)})
    if not wanted:
        return None
    spans = [lines[i] for i in wanted]
    table_ids = {s["block_id"] for s in spans if s["kind"] == "table"}
    for bid in table_ids:
        block = blocks[bid]
        cursor = block.start
        # Same header heuristic as ingestion, explicitly not a verified column model.
        for text in block.text.splitlines(keepends=True)[:4]:
            spans.append({"block_id": bid, "start": cursor, "end": cursor + len(text)})
            cursor += len(text)
        # Keep existing short context/title/unit slices next to a selected table.
        for line in lines:
            parent = blocks[line["block_id"]]
            if (
                parent.kind != "table"
                and 0 < block.ordinal - parent.ordinal <= 3
                and token_count(parent.text) <= 150
            ):
                spans.append(line)
    by_block = defaultdict(list)
    for span in spans:
        by_block[span["block_id"]].append((span["start"], span["end"]))
    actual_spans, parts = [], []
    for bid in sorted(by_block, key=lambda b: blocks[b].ordinal):
        block = blocks[bid]
        for start, end in merged(by_block[bid]):
            text = block.text[start - block.start : end - block.start]
            if len(text) != end - start:
                raise PlanRejected("compact_source_slice_invalid")
            actual_spans.append({"block_id": bid, "start": start, "end": end})
            parts.append(text)
    prefix = (
        f"Company: {filing.ticker}; report FY: {filing.fiscal_year}; "
        f"period end: {filing.period_end}; filed: {filing.filed_at}; {filing.form}."
    )
    text = prefix + "\n\n" + "\n\n[...]\n\n".join(parts)
    ephemeral_id = hit.chunk.id + ":excerpt:" + digest(json.dumps(actual_spans))[:8]
    chunk = hit.chunk.model_copy(
        update={
            "id": ephemeral_id,
            "text": text,
            "embedding_text": text,
            "tokens": token_count(text),
            "spans": actual_spans,
            "block_ids": list(dict.fromkeys(s["block_id"] for s in actual_spans)),
        }
    )
    return hit.model_copy(update={"chunk": chunk, "expanded_spans": []}), text


def evidence_records(hits, texts, filings):
    result = []
    for i, hit in enumerate(hits, 1):
        filing = filings[hit.chunk.document_id]
        result.append(
            {
                "citation": f"E{i}",
                "document_id": filing.id,
                "ticker": filing.ticker,
                "fiscal_year": filing.fiscal_year,
                "period_end": filing.period_end,
                "filed_at": filing.filed_at,
                "source_url": filing.source_url,
                "chunk_id": hit.chunk.id,
                "source_spans": [*hit.chunk.spans, *hit.expanded_spans],
                "text": texts[hit.chunk.id],
            }
        )
    return result


def prompt_tokens(data, evidence):
    return token_count(
        json.dumps(answer_messages({**data, "runtime_evidence": evidence}), ensure_ascii=False)
    )


def select_reranked(
    hits,
    grades,
    blocks,
    store,
    filings,
    config,
    data,
    evidence_cap,
    prompt_cap,
    *,
    compact=False,
    balanced=False,
    priority_scores=None,
    max_items=30,
):
    original_order = {h.chunk.id: i for i, h in enumerate(hits)}
    remaining = [h for h in hits if priority_scores is not None or grades[h.chunk.id]["s"] > 0]
    selected, texts, decisions, sources = [], {}, [], {}
    used, need_counts, prepared = 0, defaultdict(int), {}
    while remaining and len(selected) < max_items:

        def utility(hit):
            if priority_scores is not None:
                return (-priority_scores[hit.chunk.id], 0, original_order[hit.chunk.id])
            grade = grades[hit.chunk.id]
            novelty = (
                sum(1 / (1 + need_counts[n]) for n in grade["n"]) if balanced else len(grade["n"])
            )
            return (-grade["s"], -novelty, original_order[hit.chunk.id])

        remaining.sort(key=utility)
        parent = remaining.pop(0)
        grade = grades[parent.chunk.id]
        if parent.chunk.id not in prepared:
            prepared[parent.chunk.id] = (
                compact_source(parent, grade, blocks, filings[parent.chunk.document_id])
                if compact
                else assemble(parent, store, filings[parent.chunk.document_id], config)
            )
        option = prepared[parent.chunk.id]
        if option is None:
            decisions.append({"parent_chunk_id": parent.chunk.id, "decision": "no_selected_lines"})
            continue
        hit, text = option
        spans = [*hit.chunk.spans, *hit.expanded_spans]
        if span_overlap(spans, sources) >= config.overlap_threshold:
            decisions.append({"parent_chunk_id": parent.chunk.id, "decision": "source_overlap"})
            continue
        cost = token_count(text)
        if used + cost > evidence_cap and hit.expanded_spans:
            hit, text = parent, parent.chunk.embedding_text
            spans, cost = hit.chunk.spans, token_count(text)
        if used + cost > evidence_cap:
            decisions.append({"parent_chunk_id": parent.chunk.id, "decision": "evidence_budget"})
            continue
        trial = evidence_records([*selected, hit], {**texts, hit.chunk.id: text}, filings)
        input_tokens = prompt_tokens(data, trial)
        if input_tokens > prompt_cap:
            decisions.append({"parent_chunk_id": parent.chunk.id, "decision": "full_prompt_budget"})
            continue
        selected.append(hit)
        texts[hit.chunk.id] = text
        used += cost
        for n in grade["n"]:
            need_counts[n] += 1
        for span in spans:
            sources.setdefault(span["block_id"], []).append((span["start"], span["end"]))
        decisions.append(
            {
                "parent_chunk_id": parent.chunk.id,
                "context_chunk_id": hit.chunk.id,
                "decision": "selected",
                **(
                    {"priority_score": priority_scores[parent.chunk.id]}
                    if priority_scores is not None
                    else {"grade": grade}
                ),
                "tokens": cost,
            }
        )
    decisions.extend(
        {"parent_chunk_id": h.chunk.id, "decision": "item_safety_cap"} for h in remaining
    )
    evidence = evidence_records(selected, texts, filings)
    return (
        selected,
        texts,
        evidence,
        {
            "evidence_tokens": used,
            "evidence_token_cap": evidence_cap,
            "full_prompt_proxy_tokens": prompt_tokens(data, evidence),
            "full_prompt_cap": prompt_cap,
            "selected_items": len(selected),
            "decisions": decisions,
            "semantic_need_judgments_are": (
                "not provided by crossencoder"
                if priority_scores is not None
                else "model predictions, not verified support"
            ),
        },
    )
