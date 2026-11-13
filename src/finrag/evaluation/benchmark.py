"""Offline saved-trace diagnostics and anchored behavior review; never execute providers."""

import argparse
import json
import os
from collections import Counter
from datetime import datetime
from pathlib import Path
from statistics import mean
from types import SimpleNamespace

from finrag.core.files import atomic_json, digest
from finrag.core.models import Evidence
from finrag.evaluation.dataset import DISPOSITIONS, indexed, load_dataset, require
from finrag.evaluation.evidence import covers
from finrag.evaluation.rubric import DIMENSIONS


def fraction(numerator, denominator):
    return {
        "value": numerator / denominator if denominator else None,
        "numerator": numerator,
        "denominator": denominator,
    }


def group_recall(groups, rows):
    if not groups:
        return {"value": None, "reason": "no_positive_evidence_labels"}
    if rows is None:
        return {"value": None, "reason": "stage_not_recorded"}
    hits = []
    for row in rows:
        chunk = row.get("chunk", {})
        hits.append(
            SimpleNamespace(
                chunk=SimpleNamespace(document_id=chunk["document_id"], spans=chunk["spans"]),
                expanded_spans=row.get("expanded_spans", []),
            )
        )
    found = [i for i, group in enumerate(groups) if any(covers(Evidence(**e), hits) for e in group)]
    return {
        **fraction(len(found), len(groups)),
        "missing_groups": [i for i in range(len(groups)) if i not in found],
    }


def stage_metrics(case, trace):
    retrieval = trace.get("retrieval", {})
    ranked = retrieval.get("ranked_hits")
    stages = {r["name"]: r for r in trace.get("stages", [])}
    actual_ids = stages.get("rerank", {}).get("inputs", {}).get("candidate_ids")
    actual = None
    if actual_ids is not None and ranked is not None:
        by_id = {r["chunk"]["id"]: r for r in ranked}
        require(set(actual_ids) <= by_id.keys(), "shortlist_missing_recorded_hits")
        actual = [by_id[i] for i in actual_ids]
    evidence = trace.get("runtime_evidence")
    # Only exact actual context spans count; final_hits can include unselected source text.
    context = None
    if evidence is not None and all("source_spans" in e for e in evidence):
        context = [
            {"chunk": {"document_id": e["document_id"], "spans": e["source_spans"]}}
            for e in evidence
        ]
    groups = case["evidence_groups"]
    result = {
        "candidate": group_recall(groups, retrieval.get("candidate_hits")),
        "shortlist": group_recall(groups, actual),
        "context": group_recall(groups, context),
    }
    for k in (10, 20, 80):
        result[f"coarse_top{k}"] = group_recall(groups, ranked[:k] if ranked is not None else None)
    pool, top = result["candidate"], result["coarse_top80"]
    result["coarse_retention"] = (
        fraction(top["numerator"], pool["numerator"])
        if pool.get("value") is not None and top.get("value") is not None
        else {"value": None, "reason": "missing_stage_or_labels"}
    )
    return result


def response_text(trace):
    answer = (trace.get("generation") or {}).get("answer")
    if answer:
        return answer
    plan = trace.get("plan") or {}
    return "\n".join(
        str(s) for key in ("clarification_questions", "limitations") for s in plan.get(key, [])
    )


def resources(trace):
    spans = trace.get("stages", [])
    llms = [s for s in spans if s["name"] == "llm_call"]
    times = [s for s in spans if s.get("started_at") and s.get("ended_at")]
    elapsed = (
        (
            max(datetime.fromisoformat(s["ended_at"]) for s in times)
            - min(datetime.fromisoformat(s["started_at"]) for s in times)
        ).total_seconds()
        if times
        else None
    )
    usage = (trace.get("agent") or {}).get("usage", {})
    sql = [
        s["outputs"]["search_attempts"]
        for s in spans
        if s["name"].startswith("retrieve.") and "search_attempts" in s.get("outputs", {})
    ]
    return {
        "llm_calls_recorded": len(llms),
        "llm_prompt_tokens": sum(
            s.get("outputs", {}).get("usage", {}).get("prompt_tokens", 0) for s in llms
        ),
        "llm_completion_tokens": sum(
            s.get("outputs", {}).get("usage", {}).get("completion_tokens", 0) for s in llms
        ),
        "known_new_cost_usd": usage.get("paid_known_usd"),
        "unresolved_reserved_usd": usage.get("paid_unresolved_usd"),
        "provider_attempts": usage.get("provider_calls"),
        "provider_attempts_by_purpose": usage.get("provider_attempts_by_purpose"),
        "sql_attempts_policy": usage.get("sql_attempts"),
        "sql_retries": usage.get("sql_retries"),
        "connect_retries": usage.get("connect_retries"),
        "schema_repairs": usage.get("schema_repairs"),
        "request_execution_seconds": trace.get("duration_seconds"),
        "instrumented_span_elapsed_seconds": elapsed,
        "end_to_end_seconds": trace.get("end_to_end_seconds"),
        "timing_note": "request_execution_seconds includes setup/cleanup when instrumented; excludes admission, artifact write and HTTP delivery; legacy span ranges can exclude setup; never sum nested spans",
        "sql_attempts_recorded": sum(len(v) for v in sql) if sql else None,
    }


def scope_diagnostics(case, trace):
    query = trace["inputs"]
    cutoff = query["as_of"]
    confirmed = query.get("confirmed_context") or {}
    required_document = confirmed.get("report_document_id")
    violations = []
    for e in trace.get("runtime_evidence", []):
        if e.get("filed_at") and e["filed_at"] > cutoff:
            violations.append({"reason": "future_evidence", "citation": e.get("citation")})
        if required_document and e["document_id"] != required_document:
            violations.append(
                {"reason": "outside_confirmed_document", "citation": e.get("citation")}
            )
    plan = trace.get("plan") or {}
    if plan.get("as_of") and plan["as_of"] != cutoff:
        violations.append({"reason": "plan_cutoff_changed"})
    expected = case.get("known_scope", {})
    companies = expected.get("companies", [])
    expected_tickers = {x["ticker"] if isinstance(x, dict) else x for x in companies}
    actual_tickers = {r["ticker"] for r in plan.get("companies", [])}
    catalog = next(
        (
            s.get("outputs", {}).get("catalog")
            for s in trace.get("stages", [])
            if s["name"] == "catalog_snapshot"
        ),
        None,
    )
    precondition = case.get("catalog_precondition", {})
    if catalog is not None and precondition:
        published = {r["id"] for company in catalog for r in company.get("reports", [])}
        require(
            not published.intersection(precondition.get("absent_reports", [])),
            "dataset_catalog_precondition_changed",
        )
    return {
        "hard_violations": violations,
        "unexpected_plan_companies": sorted(actual_tickers - expected_tickers)
        if expected_tickers
        else [],
        "intent_and_constraint_semantics": "requires_anchored_review",
    }


def behavior_packet(dataset, case, trace, trace_hash):
    packet = {
        "schema_version": "behavior-review-v1",
        "id": case["id"],
        "dataset_hash": dataset.identity,
        "trace_hash": trace_hash,
        "request": dataset.queries[case["id"]],
        "response": response_text(trace),
        "plan": trace.get("plan"),
        "status": trace["status"],
        "expected_dispositions": case["expected_dispositions"],
        "criteria": case["behavior_criteria"],
    }
    packet["packet_hash"] = digest(json.dumps(packet, ensure_ascii=False, sort_keys=True))
    return packet


def score_behavior(packet, verdict):
    if verdict is None:
        return {"outcome": "unjudged"}
    require(
        verdict["id"] == packet["id"] and verdict["packet_hash"] == packet["packet_hash"],
        "stale_behavior_verdict",
    )
    require(
        isinstance(verdict.get("judge_method"), str) and verdict["judge_method"].strip(),
        "behavior_judge_provenance_required",
    )
    require(verdict["disposition"] in DISPOSITIONS, "invalid_observed_disposition")
    require(type(verdict.get("asked_clarification")) is bool, "clarification_observation_required")
    criteria = indexed(verdict["criteria"])
    require(criteria.keys() == indexed(packet["criteria"]).keys(), "incomplete_behavior_verdict")
    for row in criteria.values():
        require(row["status"] in {"pass", "fail", "uncertain"}, "invalid_behavior_judgment")
        require(
            isinstance(row.get("reason"), str) and row["reason"].strip(), "missing_behavior_reason"
        )
        quote = row.get("quote", "")
        require(
            isinstance(quote, str) and quote in packet["response"], "unverifiable_behavior_quote"
        )
        if row["status"] == "pass":
            require(bool(quote.strip()), "passing_behavior_requires_response_anchor")
    failed = verdict["disposition"] not in packet["expected_dispositions"] or any(
        r["status"] == "fail" for r in criteria.values()
    )
    return {
        "outcome": "fail"
        if failed
        else "review"
        if any(r["status"] == "uncertain" for r in criteria.values())
        else "pass",
        "disposition": verdict["disposition"],
        "asked_clarification": verdict["asked_clarification"],
        "judge_method": verdict["judge_method"],
        "criteria": list(criteria.values()),
        "anchor_check_only": True,
    }


def summarize(rows):
    attempted = [r for r in rows if r["execution"] != "not_run"]
    passed = sum(r["task_result"] == "pass" for r in rows)
    stage_names = (
        "candidate",
        "coarse_top10",
        "coarse_top20",
        "coarse_top80",
        "shortlist",
        "context",
    )
    stages = {}
    for name in stage_names:
        values = [
            r["stages"][name]["value"] for r in attempted if r["stages"][name]["value"] is not None
        ]
        stages[name] = {"macro_recall": mean(values) if values else None, "n": len(values)}
    reviewed = [r for r in attempted if r["behavior"]["outcome"] != "unjudged"]
    asked = [r for r in reviewed if r["behavior"].get("asked_clarification")]
    expected_ask = [r for r in reviewed if r["requires_clarification"]]
    correct_ask = sum(
        r["requires_clarification"] and r["behavior"]["outcome"] == "pass" for r in asked
    )
    sufficient = [r for r in reviewed if not r["requires_clarification"]]
    facts = sum(r["requirements"]["facts"] for r in rows)
    numbers = sum(r["requirements"]["numbers"] for r in rows)
    fact_points = sum(
        r.get("answer", {}).get("fact_points", 0) if r.get("answer") else 0 for r in rows
    )
    numeric_passes = sum(
        n["status"] in {"correct", "correct_rounded", "minor_precision"}
        for r in rows
        if r.get("answer")
        for n in r["answer"]["numbers"]
    )
    quality = {}
    for dimension in DIMENSIONS:
        values = [
            v["score"]
            for r in rows
            for v in (r.get("quality") or {}).get("dimensions", [])
            if v["id"] == dimension and v["score"] is not None
        ]
        quality[dimension] = {"mean": mean(values) if values else None, "n": len(values)}
    return {
        "selected": len(rows),
        "attempted": len(attempted),
        "execution_coverage": fraction(len(attempted), len(rows)),
        "known_task_success_lower_bound": fraction(passed, len(rows)),
        "attempted_task_success_lower_bound": fraction(passed, len(attempted)),
        "task_outcomes": dict(Counter(r["task_result"] for r in rows)),
        "stage_metrics": stages,
        "unjudged_are_not_passes": True,
        "behavior_review_coverage": fraction(len(reviewed), len(attempted)),
        "reviewed_behavior_accuracy": fraction(
            sum(r["behavior"]["outcome"] == "pass" for r in reviewed), len(reviewed)
        ),
        "clarification_precision_reviewed": fraction(correct_ask, len(asked)),
        "clarification_recall_reviewed": fraction(correct_ask, len(expected_ask)),
        "unnecessary_clarification_reviewed": fraction(
            sum(r["behavior"].get("asked_clarification", False) for r in sufficient),
            len(sufficient),
        ),
        "fact_coverage_known_lower_bound": fraction(fact_points, facts),
        "numeric_coverage_known_lower_bound": fraction(numeric_passes, numbers),
        "answer_reviews_present": sum(bool(r.get("answer")) for r in rows),
        "whole_answer_dimensions": quality,
        "complete_batch": len(attempted) == len(rows),
    }


def stage_observations(metrics, answer):
    notes = []
    candidate, shortlist, context = (metrics[k] for k in ("candidate", "shortlist", "context"))
    if candidate.get("value") is not None and candidate["value"] < 1:
        notes.append(
            {
                "stage": "candidate",
                "missing_groups": candidate["missing_groups"],
                "check": "catalog, source parsing, scope/filters, queries and index; not proof of an embedding fault",
            }
        )
    if (
        candidate.get("value") is not None
        and shortlist.get("value") is not None
        and shortlist["value"] < candidate["value"]
    ):
        notes.append({"stage": "coarse_shortlist", "check": "ranking and task allocation"})
    if (
        shortlist.get("value") is not None
        and context.get("value") is not None
        and context["value"] < shortlist["value"]
    ):
        notes.append(
            {
                "stage": "context",
                "check": "rerank, compaction, table headers and shared context budget",
            }
        )
    if context.get("value") == 1 and answer and answer["outcome"] != "pass":
        notes.append(
            {
                "stage": "generation_or_interpretation",
                "check": "source spans are available; inspect metric/column interpretation and generation, not a proven root cause",
            }
        )
    return notes


def diagnose(dataset, traces, *, ids=None, verdicts=None, answer_scores=None):
    selected = dataset.select(ids)
    behavior = indexed(verdicts or [])
    answer_rows = indexed((answer_scores or {}).get("questions", []))
    require(
        set(behavior) <= set(selected) and set(answer_rows) <= set(selected),
        "unexpected_verdict_case",
    )
    whole = (answer_scores or {}).get("whole_answer", {}).get("by_question", {})
    require(set(whole) <= set(selected), "unexpected_quality_case")
    rows, packets = [], []
    for qid in selected:
        case, query = dataset.cases[qid], dataset.queries[qid]
        requirements = {
            "facts": len(dataset.rubrics[qid]["mandatory_facts"]),
            "numbers": len(dataset.rubrics[qid]["numeric_check_ids"]),
        }
        requires_clarification = (
            "clarify" in case["expected_dispositions"] or case["kind"] == "mixed_ambiguous"
        )
        path = Path(traces) / f"{qid}.json"
        if not path.exists():
            require(qid not in behavior and qid not in answer_rows, "verdict_without_trace")
            rows.append(
                {
                    "id": qid,
                    "family": case["family"],
                    "execution": "not_run",
                    "task_result": "not_run",
                    "requirements": requirements,
                }
            )
            continue
        require(
            not path.is_symlink() and path.stat().st_size <= 32 * 1024 * 1024,
            "unsafe_or_oversize_trace",
        )
        raw = path.read_bytes()
        trace = json.loads(raw)
        require(trace["query_id"] == qid, "wrong_trace_id")
        for key in ("question", "reading_context", "confirmed_context", "as_of", "corpus_scope"):
            field = "original_question" if key == "question" else key
            require(trace["inputs"].get(field) == query[key], f"trace_request_changed:{key}")
        packet = behavior_packet(dataset, case, trace, digest(raw))
        packets.append(packet)
        judged = score_behavior(packet, behavior.get(qid))
        a = answer_rows.get(qid)
        if a is not None:
            # Recreate the existing answer packet identity, not a new quality scoring system.
            from finrag.evaluation.answers import prepare

            original = prepare(Path(traces), dataset.path, [qid])[0]
            require(
                a["trace_hash"] == original["trace_hash"]
                and a["packet_hash"] == original["packet_hash"],
                "stale_answer_scores",
            )
            require(
                a["fact_count"] == len(dataset.rubrics[qid]["mandatory_facts"])
                and a["numeric_count"] == len(dataset.rubrics[qid]["numeric_check_ids"]),
                "answer_score_denominator_changed",
            )
        quality = whole.get(qid)
        if quality is not None:
            require(
                a is not None and quality["packet_hash"] == a["packet_hash"], "stale_quality_scores"
            )
            require(
                {v["id"] for v in quality["dimensions"]} == set(DIMENSIONS),
                "quality_dimensions_missing",
            )
            require(
                all(
                    v["score"] is None or (type(v["score"]) is int and 1 <= v["score"] <= 5)
                    for v in quality["dimensions"]
                ),
                "invalid_quality_score",
            )
        operational_error = trace["status"] == "error" or bool(trace.get("error"))
        scope = scope_diagnostics(case, trace)
        needs_answer = bool(dataset.rubrics[qid]["mandatory_facts"])
        task = (
            "execution_failure"
            if operational_error
            else "fail"
            if scope["hard_violations"]
            or judged["outcome"] == "fail"
            or (a and a["outcome"] == "fail")
            else "needs_review"
            if judged["outcome"] != "pass" or (needs_answer and (not a or a["outcome"] != "pass"))
            else "pass"
        )
        metrics = stage_metrics(case, trace)
        rows.append(
            {
                "id": qid,
                "family": case["family"],
                "execution": "error" if operational_error else "completed",
                "trace_hash": digest(raw),
                "run_id": trace.get("run_id"),
                "task_result": task,
                "behavior": judged,
                "answer": a,
                "quality": quality,
                "requirements": requirements,
                "requires_clarification": requires_clarification,
                "terminal_outcome": trace.get("agent", {}).get("outcome", trace["status"]),
                "runtime_identity": {
                    "config": trace.get("config"),
                    "index_id": trace.get("index_id"),
                    "models": [
                        {
                            k: span.get("outputs", {}).get(k)
                            for k in ("requested_model", "response_model", "parameters")
                        }
                        for span in trace.get("stages", [])
                        if span["name"] == "llm_call"
                    ],
                    "answer_prompt_version": trace.get("generation", {}).get("prompt_version"),
                    "catalog_fingerprint": next(
                        (
                            span.get("outputs", {}).get("fingerprint")
                            for span in trace.get("stages", [])
                            if span["name"] == "catalog_snapshot"
                        ),
                        None,
                    ),
                    "source_spans": [
                        s.get("source") for s in trace.get("stages", []) if s.get("source")
                    ],
                },
                "stages": metrics,
                "diagnostic_observations": stage_observations(metrics, a),
                "continuation_of": case.get("continuation_of"),
                "scope": scope,
                "resources": resources(trace),
                "failed_spans": [
                    {k: s.get(k) for k in ("id", "parent_id", "name", "source", "error_type")}
                    for s in trace.get("stages", [])
                    if s.get("status") == "error"
                ],
                "trace_file": f"{qid}.json",
            }
        )
    return {
        "version": "offline-pilot-diagnostics-v1",
        "dataset_hash": dataset.identity,
        "selected_ids": selected,
        "trace_directory": str(Path(traces).resolve()),
        "summary": summarize(rows),
        "cases": rows,
    }, packets


def render_report(result, out=None):
    s = result["summary"]
    lines = [
        "# 离线评测诊断",
        "",
        "只读取保存的实际trace和导入判定，不调用模型。未运行、未记录与待判不自动计为通过。",
        "",
        f"选定{s['selected']}；已执行{s['attempted']}；状态：{s['task_outcomes']}。",
        "",
        "| 案例 | 执行 | 任务结果 | 候选Recall | Context Recall |",
        "| --- | --- | --- | --- | --- |",
    ]
    for r in result["cases"]:

        def display(stage, row=r):
            v = row.get("stages", {}).get(stage, {}).get("value")
            return f"{v:.2%}" if v is not None else "N/A"

        lines.append(
            f"| {r['id']} | {r['execution']} | {r['task_result']} | {display('candidate')} | {display('context')} |"
        )
    lines += ["", "## 五维整答评分", "", "未导入判定时为N/A，阶段Recall不能替代这些分数。", ""]
    for name, metric in s["whole_answer_dimensions"].items():
        lines.append(f"- {name}: {metric['mean']} (n={metric['n']})")
    lines += ["", "## Bad cases / 待复核", ""]
    for r in result["cases"]:
        if r["task_result"] in {"pass", "not_run"}:
            continue
        target = Path(result["trace_directory"]) / r["trace_file"]
        target = os.path.relpath(target, out) if out is not None else str(target)
        lines += [
            f"### {r['id']} · {r['task_result']}",
            "",
            f"[Trace](<{target}>)；run：`{r.get('run_id')}`。",
            f"范围检查：{r['scope']}；失败span：{r['failed_spans']}。",
            f"阶段观察：{r['diagnostic_observations']}。",
            "待填写：首个偏差、根因假设、相关证据/代码、验证与回归结果。低Recall不是根因结论。",
            "",
        ]
    return "\n".join(lines) + "\n"


def paired(before, after):
    require(
        before["dataset_hash"] == after["dataset_hash"]
        and before["selected_ids"] == after["selected_ids"],
        "unpaired_datasets_or_selection",
    )
    old = indexed(before["cases"])
    changes = []
    for r in after["cases"]:
        prev = old[r["id"]]
        deltas = {}
        for name in ("candidate", "coarse_top80", "context"):
            a = prev.get("stages", {}).get(name, {}).get("value")
            b = r.get("stages", {}).get(name, {}).get("value")
            deltas[name] = b - a if a is not None and b is not None else None
        quality_delta = {}
        for name in DIMENSIONS:
            left = {
                v["id"]: v["score"] for v in (prev.get("quality") or {}).get("dimensions", [])
            }.get(name)
            right = {
                v["id"]: v["score"] for v in (r.get("quality") or {}).get("dimensions", [])
            }.get(name)
            quality_delta[name] = right - left if right is not None and left is not None else None
        numeric_counts = {}
        for label, row in (("before", prev), ("after", r)):
            a = row.get("answer")
            numeric_counts[label] = (
                fraction(
                    sum(
                        n["status"] in {"correct", "correct_rounded", "minor_precision"}
                        for n in a["numbers"]
                    ),
                    row["requirements"]["numbers"],
                )
                if a
                else None
            )
        changes.append(
            {
                "id": r["id"],
                "before": prev["task_result"],
                "after": r["task_result"],
                "regression": prev["task_result"] == "pass"
                and r["task_result"] in {"fail", "execution_failure"},
                "quality_comparison_pending": r["task_result"] in {"needs_review", "not_run"},
                "runtime_identity_changed": prev.get("runtime_identity")
                != r.get("runtime_identity"),
                "stage_delta": deltas,
                "quality_delta": quality_delta,
                "required_numeric_coverage": numeric_counts,
            }
        )
    return {
        "dataset_hash": before["dataset_hash"],
        "cases": changes,
        "regressions": [r["id"] for r in changes if r["regression"]],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    v = sub.add_parser("validate-set")
    v.add_argument("--dataset", type=Path, required=True)
    p = sub.add_parser("diagnose")
    p.add_argument("--dataset", type=Path, required=True)
    p.add_argument("--traces", type=Path, required=True)
    p.add_argument("--ids", nargs="+")
    p.add_argument("--behavior-verdicts", type=Path)
    p.add_argument("--answer-scores", type=Path)
    p.add_argument("--out", type=Path, required=True)
    c = sub.add_parser("compare")
    c.add_argument("--before", type=Path, required=True)
    c.add_argument("--after", type=Path, required=True)
    c.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "validate-set":
        d = load_dataset(args.dataset)
        print(
            json.dumps(
                {
                    "dataset_hash": d.identity,
                    "cases": len(d.cases),
                    "kinds": dict(Counter(c["kind"] for c in d.cases.values())),
                    "provider_calls": 0,
                }
            )
        )
        return
    if args.command == "compare":
        result = paired(json.loads(args.before.read_text()), json.loads(args.after.read_text()))
        atomic_json(args.out, result)
        return
    dataset = load_dataset(args.dataset)
    require(not args.out.resolve().is_relative_to(dataset.path), "outputs_cannot_overwrite_dataset")
    read = lambda p: json.loads(p.read_text()) if p else None
    result, packets = diagnose(
        dataset,
        args.traces,
        ids=args.ids,
        verdicts=read(args.behavior_verdicts),
        answer_scores=read(args.answer_scores),
    )
    atomic_json(args.out / "diagnostics.json", result)
    atomic_json(args.out / "behavior-packets.json", packets)
    atomic_json(args.out / "report.md", render_report(result, args.out), raw=True)


if __name__ == "__main__":
    main()
