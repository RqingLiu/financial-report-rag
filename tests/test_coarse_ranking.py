from copy import deepcopy

import pytest
from test_need_context import hit

from finrag.coarse_ranking import VARIANTS, bm25_scores, shortlist


def fixtures():
    a, b, c = [hit(x).model_dump() for x in ["a", "b", "c"]]
    # Two chunks carry the same source; a third contains genuinely new source text.
    b["chunk"]["spans"] = deepcopy(a["chunk"]["spans"])
    b["chunk"]["block_ids"] = ["a"]
    c["chunk"]["document_id"] = "new-year-document"
    records = [
        {"method": "dense", "task_id": "t", "group": ["UNSEEN", 2030],
         "variants": 1, "hits": [a, b]},
        {"method": "dense", "task_id": "t", "group": ["UNSEEN", 2031],
         "variants": 1, "hits": [c]},
    ]
    tasks = [{"id": "t", "dense_queries": ["requested fact"], "keywords": ["metric"]}]
    return records, tasks


def test_shortlist_scope_dedup_and_new_issuer_are_independent_of_labels():
    records, tasks = fixtures()
    before = deepcopy(records)
    for variant in VARIANTS:
        ids, details = shortlist(records, tasks, ["a", "b", "c"], variant, limit=2)
        assert len(ids) <= 2 and len(set(ids)) == len(ids)
        assert set(ids) <= {"a", "b", "c"}
        if variant.endswith("dedup"):
            assert "c" in ids and not {"a", "b"} <= set(ids)
        if variant.startswith("quota"):
            assert all(g["represented"] for g in details["groups"])
    assert records == before
    assert shortlist(records, tasks, ["b", "a", "c"], "current", limit=2)[0] == ["b", "a"]


def test_local_bm25_distinguishes_missing_terms_and_long_repetition():
    values = bm25_scores(["unrelated content", "requested metric", "requested " * 100],
                         "requested metric")
    assert values[0] == 0 and values[1] > values[2] > 0
    assert bm25_scores(["", ""], "fact") == [0, 0]


def test_resource_limits_and_invalid_runtime_order_fail_explicitly():
    records, tasks = fixtures()
    with pytest.raises(ValueError, match="group_capacity"):
        shortlist(records, tasks, ["a", "b", "c"], "quota_rrf_dedup", limit=1)
    with pytest.raises(ValueError, match="invalid_current_order"):
        shortlist(records, tasks, ["outside-pool"], "current")
    with pytest.raises(ValueError, match="invalid_shortlist_contract"):
        shortlist(records, tasks, ["a"], "current", limit=81)
    records[0]["hits"][0]["score"] = float("nan")
    with pytest.raises(ValueError, match="non_finite"):
        shortlist(records, tasks, ["a"], "current")
