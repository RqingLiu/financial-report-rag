"""Exact source-span group recall; no model API or historical experiment dependency."""

def covers(evidence, hits):
    intervals = sorted(
        (max(s["start"], evidence.start), min(s["end"], evidence.end))
        for hit in hits
        if hit.chunk.document_id == evidence.document_id
        for s in [*hit.chunk.spans, *hit.expanded_spans]
        if s["block_id"] == evidence.block_id
        and s["start"] < evidence.end
        and s["end"] > evidence.start
    )
    cursor = evidence.start
    for start, end in intervals:
        if start > cursor:
            return False
        cursor = max(cursor, end)
    return cursor >= evidence.end

def score(question, hits):
    if not question.evidence_groups:
        raise ValueError("Boundary questions have no reference evidence; do not score as recall=1")
    found = [
        i for i, group in enumerate(question.evidence_groups) if any(covers(e, hits) for e in group)
    ]
    refs = [f"{question.id}:g{i}" for i in range(len(question.evidence_groups))]
    retrieved = [f"{question.id}:g{i}" for i in found]
    value = len(retrieved) / len(refs)
    return {
        "recall": value,
        "groups_found": len(found),
        "groups_required": len(refs),
        "missing_groups": [i for i in range(len(refs)) if i not in found],
        "complete": len(found) == len(refs),
    }
