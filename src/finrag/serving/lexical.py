"""BM25 Okapi k1=1.2 b=.75; English alphanumeric lowercase, no stemming.

Stats/postings are published with chunks. Do not label PostgreSQL ts_rank_cd as BM25.
"""

import re
from collections import Counter

from .errors import ServingError

TOKEN = re.compile(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", re.IGNORECASE)


def terms(text):
    return Counter(t.lower() for t in TOKEN.findall(text) if len(t) <= 80)


def query_terms(text, limit=32):
    found = list(terms(text))
    if len(found) > limit:
        raise ServingError("bm25_query_term_limit")
    return found


def replace_second_variants(jobs, plan):
    """One dense + one lexical replaces two dense calls, preserving scope/k/SQL count."""
    tasks = {t.id: t for t in plan.tasks}
    seen, result = {}, []
    for raw in jobs:
        job = dict(raw)
        key = (job["task_id"], tuple(job["group"]))
        seen[key] = seen.get(key, 0) + 1
        if job["method"] != "dense":
            raise ServingError("hybrid_replace_requires_dense_base_jobs")
        if job["variants"] >= 2:
            job["variants"] = 1
            if seen[key] == 2:
                job.update(method="fts", query=" ".join(tasks[job["task_id"]].keywords))
        result.append(job)
    return result
