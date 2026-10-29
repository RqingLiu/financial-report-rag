"""Query-only refinement. Scope/tasks/needs/slot counts remain an immutable contract."""

import json
from typing import Literal

from pydantic import Field, ValidationError

from .files import atomic_json, digest
from .planning import Contract, Plan, PlanRejected

VERSION = "focused-evidence-queries-v2-explicit-slots"
PROMPT = """You refine retrieval queries for SEC annual filings. Return json only, never answers.
The supplied original question, reading context, confirmed constraints and existing plan are
the ONLY requirements. Candidate texts, gold labels and reference answers are not supplied.
Keep every task ID and EXACTLY its original number of query slots. Do not change task scope,
needs, report years or cutoff. Return all original task need IDs across that task's queries.
HARD PRIORITY: obey explicit_query_slots from the request. A task with three needs and two
slots MUST return TWO queries, assigning multiple need IDs to a query. NEVER create one slot
per need when this exceeds its quota. Prefer a focused numeric query plus a complementary
query combining the closely related narrative needs. Exact slot count overrides finer splitting.
Rewrite each English query to retrieve one coherent evidence target, rather than concatenating
every requested metric, product, cause, risk and comparability limitation into a long list.
Use precise concepts from the user's question, not invented amounts, known answers or firms.
When a task requests numerical facts AND causal/risk narrative, give its first slot a focused
factual target and its other slot a complementary explanatory target. Closely related metrics
sharing the same statement can remain together; do not demand unrelated documents in one query.
If it only requests narrative, focus its slots on complementary requested narrative evidence.
Remove generic retrieval filler ('disclosures', 'filing date context', 'information not quantified')
when it distracts from the user's actual evidence target. Do not invent generic limitation queries.
Company/report-year filters are enforced separately; keep meaningful product/segment/metric names,
but don't spend query text repeating every company/year, comparing firms or writing an answer.
Do not treat a requested market share, quarterly change or causal attribution as already disclosed.
Keep the user-requested fact vs management explanation vs uncertainty distinctions. All original
task needs must remain represented, but mapping a need is not a claim that evidence exists.
Use compact, independently meaningful English queries, normally 8-30 words; avoid repeated variants.
The reason 'goal' describes the evidence being sought, not an asserted financial conclusion.
Schema (placeholder identifiers only):
{"tasks":[{"id":"t1","queries":[{"text":"A precise evidence query",
"need_ids":["n1"],"source_kind":"table","goal":"Requested metric rows and periods"}]}]}.
source_kind must be table, narrative or both. It is only an intent annotation, NOT a SQL filter.
No extra fields. Preserve the exact number of task/query entries from the input plan.
"""


class FocusQuery(Contract):
    text: str = Field(min_length=1, max_length=700)
    need_ids: list[str] = Field(min_length=1, max_length=16)
    source_kind: Literal["table", "narrative", "both"]
    goal: str = Field(min_length=1, max_length=250)


class FocusTask(Contract):
    id: str
    queries: list[FocusQuery] = Field(min_length=1, max_length=2)


class Refinement(Contract):
    tasks: list[FocusTask] = Field(min_length=1, max_length=4)


def validate_refinement(raw, plan):
    try:
        refinement = Refinement.model_validate_json(raw)
    except ValidationError as exc:
        expected = {t.id: len(t.dense_queries) for t in plan.tasks}
        locations = [".".join(map(str, e["loc"])) + ":" + e["type"] for e in exc.errors()]
        raise PlanRejected("focused_schema_invalid: expected_query_slots=" + json.dumps(expected)
                           + "; invalid_fields=" + ",".join(locations)) from None
    if [t.id for t in refinement.tasks] != [t.id for t in plan.tasks]:
        raise PlanRejected("focused_task_ids_changed")
    for refined, original in zip(refinement.tasks, plan.tasks, strict=True):
        if len(refined.queries) != len(original.dense_queries):
            raise PlanRejected("focused_query_slot_count_changed")
        seen = set()
        for q in refined.queries:
            if not q.text.strip() or q.text.strip().casefold() in seen:
                raise PlanRejected("focused_blank_or_duplicate_query")
            seen.add(q.text.strip().casefold())
            if len(q.need_ids) != len(set(q.need_ids)) or set(q.need_ids) - set(original.need_ids):
                raise PlanRejected("focused_unknown_or_duplicate_need")
        if {n for q in refined.queries for n in q.need_ids} != set(original.need_ids):
            raise PlanRejected("focused_task_need_lost")
    return refinement


def variants(plan, refinement):
    output = {"wide": plan}
    for name in ["focused", "mixed"]:
        data = plan.model_dump(mode="json")
        for target, old, refined in zip(data["tasks"], plan.tasks, refinement.tasks, strict=True):
            focused = [q.text.strip() for q in refined.queries]
            if name == "mixed" and len(focused) == 2:
                second = focused[0] if focused[0].casefold() != old.dense_queries[0].casefold() else focused[1]
                focused = [old.dense_queries[0], second]
            target["dense_queries"] = focused
        output[name] = Plan(**data)
    return output


def refine(inputs, plan, llm, cache, log):
    allowed_inputs = {k: inputs.get(k) for k in
                      ["original_question", "reading_context", "confirmed_context", "as_of"]}
    messages = [
        {"role": "system", "content": PROMPT},
        {"role": "user", "content": json.dumps(
            {"request": allowed_inputs, "plan": plan.model_dump(mode="json"),
             "explicit_query_slots": [{"task_id": t.id, "exact_query_count": len(t.dense_queries),
                                       "all_required_need_ids": t.need_ids} for t in plan.tasks]}, ensure_ascii=False)},
    ]
    key = digest(json.dumps({"version": VERSION, "messages": messages}, sort_keys=True))
    path = cache / f"{key}.json"
    if path.exists():
        record = json.loads(path.read_text())
        value = validate_refinement(record["response"]["answer"], plan)
        atomic_json(log, {**record, "reused_cache": True})
        return value, {"cached": True, "cache_key": key, "new_cost_usd": "0"}
    record = {"version": VERSION, "messages": messages, "attempts": [], "cache_key": key}
    for attempt in range(2):
        response = llm.generate(messages, max_tokens=4096, json_object=True,
                                purpose="focused_query_refinement")
        record["attempts"].append({"response": response})
        atomic_json(log, record)
        try:
            if response["finish_reason"] != "stop":
                raise PlanRejected("focused_output_truncated")
            value = validate_refinement(response["answer"], plan)
            break
        except PlanRejected as exc:
            record["attempts"][-1]["validation_error"] = str(exc)
            atomic_json(log, record)
            if attempt:
                raise
            messages = [*messages, {"role": "assistant", "content": response["answer"]},
                        {"role": "user", "content": f"Invalid json contract: {exc}. Repair only; return all tasks and exact slot counts."}]
    record["response"] = response
    atomic_json(path, record)
    atomic_json(log, record)
    return value, {"cached": False, "cache_key": key, "attempts": len(record["attempts"]),
                   "costs_usd": [a["response"]["peak_list_cost_usd"] for a in record["attempts"]]}


def search_signature(jobs):
    """Ignore query text only; all actual search budgets and source filters must match."""
    return [{k: v for k, v in job.items() if k != "query"} for job in jobs]
