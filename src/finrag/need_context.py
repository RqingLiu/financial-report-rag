"""Need-aware budget selection. Rank/source proxies are NOT proof of semantic support."""

from collections import defaultdict
from math import log1p, sqrt

from .chunk import token_count
from .context import assemble, span_overlap
from .planning import Plan, PlanRejected

SELECTOR_VERSION = "need-budget-v1"


def need_proxies(plan, records, config):
    """Share need weight across source documents; duplicate queries do not add weight."""
    if plan is None or records is None:
        raise PlanRejected("need_budget_requires_plan_and_search_records")
    if not isinstance(plan, Plan):
        plan = Plan(**plan)
    tasks = {t.id: t for t in plan.tasks}
    needs = {n.id for n in plan.needs}
    scopes, support = defaultdict(set), defaultdict(dict)
    for record in records:
        method = record["method"]
        weight = config.dense_weight if method == "dense" else config.fts_weight
        if weight <= 0:
            continue
        task = tasks.get(record["task_id"])
        if task is None:
            raise PlanRejected("search_record_task_not_in_plan")
        for need in task.need_ids:
            if need not in needs:
                raise PlanRejected("search_record_need_not_in_plan")
            scopes[need].update(record["documents"])
        for rank, raw in enumerate(record["hits"], 1):
            chunk = raw["chunk"]
            if chunk["document_id"] not in record["documents"]:
                raise PlanRejected("candidate_outside_search_scope")
            # Reciprocal-root rank is a relevance proxy, not calibrated probability.
            quality = weight / sqrt(rank)
            for need in task.need_ids:
                key = (need, chunk["document_id"])
                support[chunk["id"]][key] = max(quality, support[chunk["id"]].get(key, 0))
    weights = {(need, doc): 1 / len(docs) for need, docs in scopes.items() for doc in docs}
    return plan, support, weights


def build_need_context(ranked, store, filings, config, plan, records):
    plan, support, weights = need_proxies(plan, records, config)
    by_id = {f.id: f for f in filings}
    pool = ranked[: config.context_candidate_limit]
    if config.expand_tables:
        store.blocks(list({bid for h in pool for bid in h.chunk.block_ids}))
    # Each alternative keeps real text and its own cost; an expansion that does not fit
    # can fall back to the original chunk, never claiming spans for omitted text.
    options = {}
    for hit in pool:
        expanded, text = assemble(hit, store, by_id[hit.chunk.document_id], config)
        options[hit.chunk.id] = [(expanded, text, token_count(text))]
        if expanded.expanded_spans:
            original = hit.chunk.embedding_text
            options[hit.chunk.id].append((hit, original, token_count(original)))
    selected, texts, decisions = [], {}, []
    covered_spans, accumulated = {}, defaultdict(float)
    remaining, used = list(pool), 0
    while remaining and len(selected) < config.context_k:
        choices = []
        unavailable = {}
        for position, hit in enumerate(remaining):
            if not support.get(hit.chunk.id):
                unavailable[hit.chunk.id] = "no_active_need_proxy"
                continue
            for expanded, text, cost in options[hit.chunk.id]:
                if used + cost > config.context_tokens:
                    unavailable[hit.chunk.id] = "context_budget"
                    continue
                spans = [*expanded.chunk.spans, *expanded.expanded_spans]
                overlap = span_overlap(spans, covered_spans)
                if overlap >= config.overlap_threshold:
                    unavailable[hit.chunk.id] = "source_overlap"
                    continue
                values = {
                    key: quality * (1 - overlap) for key, quality in support[hit.chunk.id].items()
                }
                gain = sum(
                    weights[key] * (log1p(accumulated[key] + quality) - log1p(accumulated[key]))
                    for key, quality in values.items()
                )
                utility = gain / max(cost, 1) ** config.need_cost_exponent
                # Original order is a deterministic tie-break; no question IDs or gold.
                choices.append((utility, -position, expanded, text, cost, gain, values))
                # Prefer complete table when it fits; fallback only when it cannot fit
                # or all its source is already represented.
                break
        if not choices:
            decisions.extend(
                {"chunk_id": h.chunk.id, "decision": unavailable.get(h.chunk.id, "no_gain")}
                for h in remaining
            )
            remaining = []
            break
        _, _, chosen, text, cost, gain, values = max(choices, key=lambda c: c[:2])
        selected.append(chosen)
        texts[chosen.chunk.id] = text
        used += cost
        for key, value in values.items():
            accumulated[key] += value
        for span in [*chosen.chunk.spans, *chosen.expanded_spans]:
            covered_spans.setdefault(span["block_id"], []).append((span["start"], span["end"]))
        decisions.append(
            {
                "chunk_id": chosen.chunk.id,
                "decision": "selected",
                "tokens": cost,
                "expanded_table": bool(chosen.expanded_spans),
                "proxy_marginal_gain": gain,
                "proxy_need_ids": sorted({key[0] for key in values}),
                "proxy_need_sources": [
                    {"need_id": need, "document_id": doc, "contribution": value}
                    for (need, doc), value in sorted(values.items())
                ],
            }
        )
        remaining = [h for h in remaining if h.chunk.id != chosen.chunk.id]
    decisions.extend({"chunk_id": h.chunk.id, "decision": "item_safety_cap"} for h in remaining)
    represented = sorted({need for (need, _), value in accumulated.items() if value > 0})
    return (
        selected,
        texts,
        {
            "selector_version": SELECTOR_VERSION,
            "context_proxy_tokens": used,
            "considered_candidates": len(pool),
            "decisions": decisions,
            "proxy_represented_need_ids": represented,
            "proxy_unrepresented_need_ids": sorted({n.id for n in plan.needs} - set(represented)),
            "coverage_note": "Task/source rank proxies only; not semantic need satisfaction or actual fact-period coverage",
        },
    )
