import json
from copy import deepcopy

import pytest
from test_need_context import inputs

from finrag.focused_query import refine, search_signature, validate_refinement, variants
from finrag.planning import PlanRejected


def response(plan):
    return {"tasks": [{"id": t.id, "queries": [
        {"text": "Requested specific metric rows " + t.id, "need_ids": t.need_ids,
         "source_kind": "table", "goal": "Requested evidence"}
    ]} for t in plan.tasks]}


def test_focus_preserves_all_scope_needs_and_single_slot_task_contracts():
    _, plan = inputs()
    original = plan.model_dump(mode="json")
    focused = validate_refinement(json.dumps(response(plan)), plan)
    arms = variants(plan, focused)
    for name in ["focused", "mixed"]:
        d = arms[name].model_dump(mode="json")
        for task, source in zip(d["tasks"], original["tasks"], strict=True):
            assert len(task["dense_queries"]) == len(source["dense_queries"])
            task["dense_queries"] = source["dense_queries"]
        assert d == original
    assert plan.model_dump(mode="json") == original
    assert arms["wide"] is plan


def test_refinement_rejects_missing_needs_extra_tasks_and_changed_slot_counts():
    _, plan = inputs()
    data = response(plan)
    data["tasks"][0]["queries"][0]["need_ids"] = ["invented"]
    with pytest.raises(PlanRejected, match="unknown_or_duplicate_need"):
        validate_refinement(json.dumps(data), plan)
    data = response(plan)
    data["tasks"][0]["queries"] *= 2
    with pytest.raises(PlanRejected, match="slot_count_changed"):
        validate_refinement(json.dumps(data), plan)
    data = response(plan)
    data["tasks"].reverse()
    with pytest.raises(PlanRejected, match="task_ids_changed"):
        validate_refinement(json.dumps(data), plan)


def test_query_only_prompt_cache_and_bounded_repair(tmp_path):
    _, plan = inputs()

    class LLM:
        calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            assert "GOLD_CANARY" not in json.dumps(messages)
            return {"finish_reason": "stop", "peak_list_cost_usd": "0.001",
                    "answer": json.dumps(response(plan))}

    llm = LLM()
    request = {"original_question": "Requested metrics", "reading_context": "NEWCO reports",
               "confirmed_context": None, "as_of": "2026-10-11", "reference": "GOLD_CANARY"}
    args = (request, plan, llm, tmp_path / "cache", tmp_path / "log.json")
    assert refine(*args)[1]["cached"] is False
    assert refine(*args)[1]["cached"] is True and llm.calls == 1

    class Bad(LLM):
        def generate(self, messages, **kwargs):
            self.calls += 1
            return {"finish_reason": "stop", "peak_list_cost_usd": "0.001", "answer": "{}"}

    bad = Bad()
    with pytest.raises(PlanRejected, match="schema_invalid"):
        refine(request, plan, bad, tmp_path / "invalid", tmp_path / "bad.json")
    assert bad.calls == 2


def test_search_signature_only_ignores_query_not_scope_or_k():
    wide = [{"task_id": "t", "group": ["NEWCO", 2030], "documents": ["opaque-doc"],
             "query": "wide", "k": 20, "variants": 1, "method": "dense"}]
    focused = deepcopy(wide)
    focused[0]["query"] = "focused"
    assert search_signature(wide) == search_signature(focused)
    focused[0]["k"] = 21
    assert search_signature(wide) != search_signature(focused)


def test_two_slot_mixed_arm_keeps_one_wide_and_one_focused_query():
    _, plan = inputs()
    for t in plan.tasks:
        t.dense_queries = ["Original broad query", "Original second query"]
    data = response(plan)
    for t in data["tasks"]:
        second = deepcopy(t["queries"][0])
        second["text"] = "Complementary management explanation"
        t["queries"].append(second)
    plans = variants(plan, validate_refinement(json.dumps(data), plan))
    for old, focused, mixed in zip(plan.tasks, plans["focused"].tasks, plans["mixed"].tasks, strict=True):
        assert mixed.dense_queries == [old.dense_queries[0], focused.dense_queries[0]]
        assert len(focused.dense_queries) == 2


def test_control_replay_keeps_original_distance_for_shared_candidate():
    from test_need_context import hit

    from finrag.focus_experiment import canonical_hits

    h = hit("shared").model_dump()
    changed = deepcopy(h)
    changed["score"] = 0.123
    result = canonical_hits({"wide": {"candidate_hits": [h]},
                             "focused": {"candidate_hits": [changed]},
                             "mixed": {"candidate_hits": [changed]}})
    assert result["shared"].score == h["score"]
