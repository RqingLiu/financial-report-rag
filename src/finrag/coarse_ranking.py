"""Bounded shortlist experiments using runtime candidates only; no labels/model grades."""

import math
import re
from collections import Counter, defaultdict

from .context import span_overlap

VARIANTS = (
    "current", "global_rrf", "current_dedup", "global_rrf_dedup",
    "quota_rrf_dedup", "lexical_rrf_dedup", "quota_lexical_rrf_dedup", "cosine_dedup",
)


def terms(text):
    return re.findall(r"[^\W_]+", text.casefold())


def bm25_scores(texts, query):
    """Candidate-local BM25, not corpus-wide lexical retrieval. Fixed k1=1.2, b=.75."""
    docs = [Counter(terms(text)) for text in texts]
    lengths = [sum(d.values()) for d in docs]
    average = sum(lengths) / len(docs) if docs else 0
    if not average:
        return [0.0] * len(docs)
    dfs = Counter(word for doc in docs for word in doc)
    wanted = set(terms(query))
    values = []
    for doc, length in zip(docs, lengths, strict=True):
        value = 0.0
        for word in wanted & doc.keys():
            frequency = doc[word]
            idf = math.log(1 + (len(docs) - dfs[word] + .5) / (dfs[word] + .5))
            value += idf * frequency * 2.2 / (frequency + 1.2 * (.25 + .75 * length / average))
        values.append(value)
    return values


def prepare(records, tasks, current_ids):
    hits, distances, scores, groups = {}, {}, defaultdict(float), defaultdict(set)
    for record in records:
        if record["method"] != "dense":
            continue
        group = (record["task_id"], *record["group"])
        for rank, hit in enumerate(record["hits"], 1):
            cid = hit["chunk"]["id"]
            hits[cid] = hit
            distance = float(hit["score"])
            if not math.isfinite(distance):
                raise ValueError("non_finite_dense_distance")
            distances[cid] = min(distances.get(cid, math.inf), distance)
            scores[cid] += 1 / record["variants"] / (60 + rank)
            groups[group].add(cid)
    if len(set(current_ids)) != len(current_ids) or set(current_ids) - hits.keys():
        raise ValueError("invalid_current_order")
    current = [*current_ids, *[cid for cid in hits if cid not in set(current_ids)]]
    lexical = scores.copy()
    task_by_id = {task["id"]: task for task in tasks}
    for group, ids in groups.items():
        ids = sorted(ids)
        task = task_by_id[group[0]]
        query = " ".join([*task["dense_queries"], *task["keywords"]])
        values = bm25_scores([hits[cid]["chunk"]["text"] for cid in ids], query)
        ranking = sorted(zip(ids, values, strict=True), key=lambda pair: (-pair[1], pair[0]))
        for rank, (cid, value) in enumerate(ranking, 1):
            if value > 0:
                lexical[cid] += 1 / (60 + rank)
    return hits, current, distances, scores, lexical, groups


def shortlist(records, tasks, current_ids, variant, limit=80):
    if variant not in VARIANTS or not 1 <= limit <= 80:
        raise ValueError("invalid_shortlist_contract")
    hits, current, distances, rrf, lexical, groups = prepare(records, tasks, current_ids)
    values = lexical if "lexical" in variant else rrf
    if variant.startswith("current"):
        order = current
    elif variant == "cosine_dedup":
        order = sorted(hits, key=lambda cid: (distances[cid], cid))
    else:
        order = sorted(hits, key=lambda cid: (-values[cid], cid))
    selected, decisions, spans, covered_groups = [], [], {}, set()
    membership = defaultdict(set)
    for group, ids in groups.items():
        for cid in ids:
            membership[cid].add(group)

    def take(cid, reason):
        if cid in selected:
            return False
        sources = hits[cid]["chunk"]["spans"]
        if variant.endswith("dedup") and span_overlap(sources, spans) >= .9:
            decisions.append({"chunk_id": cid, "decision": "source_overlap", "phase": reason})
            return False
        selected.append(cid)
        covered_groups.update(membership[cid])
        for span in sources:
            spans.setdefault(span["block_id"], []).append((span["start"], span["end"]))
        decisions.append({"chunk_id": cid, "decision": "selected", "phase": reason})
        return True

    if variant.startswith("quota"):
        if len(groups) > limit:
            raise ValueError("shortlist_group_capacity_exceeded")
        for group in sorted(groups):
            if group not in covered_groups:
                for cid in order:
                    if cid in groups[group] and take(cid, "group_seed"):
                        break
    for cid in order:
        if len(selected) >= limit:
            break
        take(cid, "relevance_fill")
    return selected, {
        "variant": variant, "candidate_count": len(hits), "selected_count": len(selected),
        "decisions": decisions,
        "groups": [{"key": list(g), "represented": g in covered_groups} for g in sorted(groups)],
        "group_representation_is": "retrieval provenance only, not verified need support",
        "scores": {cid: {"dense_distance": distances[cid], "rrf": rrf[cid],
                         "lexical_fused_rrf": lexical[cid]} for cid in hits},
    }
