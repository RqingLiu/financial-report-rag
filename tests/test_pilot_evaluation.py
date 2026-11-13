"""Provider-free accepted-data, exact-context and behavior regression contracts."""

import copy
import json

import pytest

from finrag.core.config import ROOT
from finrag.core.files import atomic_json, digest
from finrag.evaluation.answers import evaluate, prepare
from finrag.evaluation.benchmark import (
    diagnose,
    paired,
    resources,
    score_behavior,
    stage_metrics,
)
from finrag.evaluation.dataset import load_dataset

PILOT = ROOT / "data/evaluation/pilot"


@pytest.fixture(scope="module")
def data():
    return load_dataset(PILOT)


def saved_trace(data, tmp_path, qid, *, status="clarify", response="请明确想比较哪几个财年。"):
    q = data.queries[qid]
    trace = {
        "query_id": qid,
        "run_id": "receipt-" + qid,
        "inputs": {
            "original_question": q["question"],
            **{k: v for k, v in q.items() if k not in {"id", "question"}},
        },
        "status": status,
        "plan": {"action": status, "as_of": q["as_of"], "clarification_questions": [response]},
        "stages": [],
        "runtime_evidence": [],
    }
    atomic_json(tmp_path / f"{qid}.json", trace)
    return trace


def verdict(packet, *, disposition="clarify", asked=True):
    return {
        "id": packet["id"],
        "packet_hash": packet["packet_hash"],
        "judge_method": "deterministic test fixture, not a financial model result",
        "disposition": disposition,
        "asked_clarification": asked,
        "criteria": [
            {
                "id": c["id"],
                "status": "pass",
                "reason": "fixture matches the labelled scope",
                "quote": packet["response"],
            }
            for c in packet["criteria"]
        ],
    }


def test_accepted_export_preserves_lineage_and_review_boundaries(data):
    assert len(data.cases) == 33
    assert data.manifest["required_numeric_checks"] == 38
    assert data.manifest["support_only_numeric_checks"] == 2
    for name, expected in data.manifest["original_sources_sha256"].items():
        assert digest((ROOT / name).read_bytes()) == expected
    for qid in ("R08", "R09", "R10"):
        assert data.queries[qid]["reading_context"] == ""
        assert data.queries[qid]["confirmed_context"] is None
        assert not data.cases[qid]["evidence_groups"]
    assert data.cases["F02"]["continuation_of"] == "R09"
    assert "用户明确补充" in data.queries["F02"]["reading_context"]
    assert data.cases["F02"]["family"] == data.cases["R09"]["family"]
    assert len(data.cases["C04"]["evidence_groups"][0]) == 2
    assert len(data.cases["C09"]["evidence_groups"]) == 4
    assert "Data Center收入" in data.queries["C08"]["question"]
    assert data.numbers["P_GAP_2026_2025"]["expected"] == "21.55"
    assert "NVDA26.729" not in (PILOT / "reference_answers.md").read_text()


def test_manifest_tampering_and_query_label_leakage_fail_before_execution(tmp_path):
    import shutil

    target = tmp_path / "copy"
    shutil.copytree(PILOT, target)
    p = target / "retrieval_queries.jsonl"
    rows = [json.loads(s) for s in p.read_text().splitlines()]
    rows[0]["reference"] = "GOLD MUST NOT REACH REQUEST"
    p.write_text("\n".join(json.dumps(r) for r in rows))
    with pytest.raises(ValueError, match="hash_mismatch"):
        load_dataset(target)
    manifest = json.loads((target / "manifest.json").read_text())
    manifest["outputs_sha256"][p.name] = digest(p.read_bytes())
    atomic_json(target / "manifest.json", manifest)
    with pytest.raises(ValueError, match="query_only"):
        load_dataset(target)


def test_context_coverage_uses_selected_spans_not_original_chunk(data):
    case = data.cases["C01"]
    ref = case["evidence_groups"][0][0]
    hit = {"chunk": {"id": "full", "document_id": ref["document_id"], "spans": [ref]}}
    short_span = {**ref, "end": ref["end"] - 1}
    trace = {
        "retrieval": {"candidate_hits": [hit], "ranked_hits": [hit]},
        "runtime_evidence": [{"document_id": ref["document_id"], "source_spans": [short_span]}],
        "stages": [{"name": "rerank", "inputs": {"candidate_ids": ["full"]}}],
    }
    scores = stage_metrics(case, trace)
    assert scores["candidate"]["value"] == 1 / len(case["evidence_groups"])
    assert scores["shortlist"]["value"] == scores["candidate"]["value"]
    assert scores["context"]["value"] == 0
    absent = stage_metrics(case, {})
    assert absent["candidate"]["value"] is None and absent["context"]["value"] is None
    assert stage_metrics(data.cases["C10"], trace)["candidate"]["value"] is None


def test_unrun_and_unjudged_cases_never_become_passes(data, tmp_path):
    result, packets = diagnose(data, tmp_path, ids=["R09", "C03"])
    assert packets == [] and result["summary"]["attempted"] == 0
    assert result["summary"]["known_task_success_lower_bound"]["numerator"] == 0
    assert result["summary"]["numeric_coverage_known_lower_bound"]["denominator"] == 6
    saved_trace(data, tmp_path, "R09")
    result, packets = diagnose(data, tmp_path, ids=["R09", "C03"])
    assert result["cases"][0]["task_result"] == "needs_review"
    assert result["summary"]["execution_coverage"]["value"] == 0.5
    judged, _ = diagnose(data, tmp_path, ids=["R09", "C03"], verdicts=[verdict(packets[0])])
    assert judged["cases"][0]["task_result"] == "pass"
    assert judged["summary"]["clarification_recall_reviewed"]["value"] == 1
    assert not judged["summary"]["complete_batch"]
    assert judged["summary"]["whole_answer_dimensions"]["truthfulness"]["mean"] is None


def test_stale_verdict_and_fabricated_review_excerpts_are_rejected(data, tmp_path):
    saved_trace(data, tmp_path, "R09")
    _, packets = diagnose(data, tmp_path, ids=["R09"])
    v = verdict(packets[0])
    v["packet_hash"] = "stale"
    with pytest.raises(ValueError, match="stale_behavior"):
        score_behavior(packets[0], v)
    v = verdict(packets[0])
    v["criteria"][0]["quote"] = "NOT IN THE OBSERVED RESPONSE"
    with pytest.raises(ValueError, match="unverifiable"):
        score_behavior(packets[0], v)
    trace = json.loads((tmp_path / "R09.json").read_text())
    trace["inputs"]["as_of"] = "2030-01-01"
    atomic_json(tmp_path / "R09.json", trace)
    with pytest.raises(ValueError, match="request_changed"):
        diagnose(data, tmp_path, ids=["R09"])


def test_failure_and_future_evidence_cannot_pass_behavior_review(data, tmp_path):
    t = saved_trace(data, tmp_path, "R09", status="error")
    _, packets = diagnose(data, tmp_path, ids=["R09"])
    result, _ = diagnose(data, tmp_path, ids=["R09"], verdicts=[verdict(packets[0])])
    assert result["cases"][0]["task_result"] == "execution_failure"
    t["status"] = "clarify"
    t["runtime_evidence"] = [
        {"document_id": "future-doc", "filed_at": "2030-01-01", "source_spans": []}
    ]
    atomic_json(tmp_path / "R09.json", t)
    _, packets = diagnose(data, tmp_path, ids=["R09"])
    result, _ = diagnose(data, tmp_path, ids=["R09"], verdicts=[verdict(packets[0])])
    assert result["cases"][0]["task_result"] == "fail"
    assert result["cases"][0]["scope"]["hard_violations"][0]["reason"] == "future_evidence"


def test_catalog_expansion_invalidates_missing_corpus_fixture(data, tmp_path):
    t = saved_trace(data, tmp_path, "B03", status="insufficient_evidence", response="库未覆盖。")
    t["stages"] = [
        {"name": "catalog_snapshot", "outputs": {"catalog": [{"reports": [{"id": "AAPL_FY2025"}]}]}}
    ]
    atomic_json(tmp_path / "B03.json", t)
    with pytest.raises(ValueError, match="precondition_changed"):
        diagnose(data, tmp_path, ids=["B03"])


def test_timing_and_sql_recovery_include_failure_without_summing_nested_spans():
    row = {
        "stages": [
            {
                "name": "generation",
                "started_at": "2026-11-09T00:00:00+00:00",
                "ended_at": "2026-11-09T00:00:03+00:00",
            },
            {
                "name": "llm_call",
                "started_at": "2026-11-09T00:00:01+00:00",
                "ended_at": "2026-11-09T00:00:02+00:00",
            },
            {"name": "retrieve.dense", "status": "error", "outputs": {"search_attempts": [{}, {}]}},
        ]
    }
    r = resources(row)
    assert r["instrumented_span_elapsed_seconds"] == 3
    assert r["end_to_end_seconds"] is None
    assert r["sql_attempts_recorded"] == 2
    assert r["known_new_cost_usd"] is None


def test_paired_comparison_does_not_call_missing_judgment_a_regression(data, tmp_path):
    saved_trace(data, tmp_path, "R09")
    pending, packets = diagnose(data, tmp_path, ids=["R09"])
    passed, _ = diagnose(data, tmp_path, ids=["R09"], verdicts=[verdict(packets[0])])
    compared = paired(passed, pending)
    assert compared["regressions"] == []
    assert compared["cases"][0]["quality_comparison_pending"]
    wrong = copy.deepcopy(pending)
    wrong["cases"][0]["task_result"] = "fail"
    assert paired(passed, wrong)["regressions"] == ["R09"]
    wrong["dataset_hash"] = "different"
    with pytest.raises(ValueError, match="unpaired"):
        paired(passed, wrong)


def test_accepted_bundle_works_with_existing_answer_packets_and_scorer(data, tmp_path):
    source = next(
        e
        for e in map(json.loads, (PILOT / "evidence_catalog.jsonl").read_text().splitlines())
        if e["id"] == "AMD23.727"
    )
    answer = "业务利润合计4,820百万美元，扣除All Other亏损4,419，合并利润401。[E1]"
    t = saved_trace(data, tmp_path, "C07", status="generated")
    t["generation"] = {"answer": answer}
    t["runtime_evidence"] = [
        {
            "citation": "E1",
            "text": source["quote"],
            **{k: source[k] for k in ("document_id", "filed_at", "source_url")},
        }
    ]
    atomic_json(tmp_path / "C07.json", t)
    packets = prepare(tmp_path, PILOT, ["C07"])
    p = packets[0]
    v = {
        "id": "C07",
        "packet_hash": p["packet_hash"],
        "judge_method": "synthetic scorer contract fixture",
        "facts": [
            {
                "id": f["id"],
                "status": "correct",
                "citation_status": "supported",
                "reason": "bridge matches",
                "citation_reason": "table operands",
                "quotes": [answer],
                "sources": [{"citation": "E1", "quote": source["quote"]}],
            }
            for f in p["rubric"]["mandatory_facts"]
        ],
        "numbers": [
            {
                "id": n["id"],
                "mapping": "aligned",
                "quote": answer,
                "literal": "4,820" if n["id"] == "N109" else "401",
                "unit": n["unit"],
                "reason": "correct source and period in fixture",
            }
            for n in p["checks"]
        ],
        "limits": [],
        "material_errors": [{"id": "M1", "status": "absent", "reason": "All Other is retained"}],
    }
    scores = evaluate(packets, [v])
    from finrag.evaluation.rubric import DIMENSIONS, PROMPT_VERSION, rubric_hash, score_quality

    rubric = json.loads(
        (ROOT / "specs/009-answer-evaluation/contracts/whole_answer_rubric.json").read_text()
    )
    whole = {
        "id": "C07",
        "packet_hash": p["packet_hash"],
        "rubric_hash": rubric_hash(rubric),
        "prompt_version": PROMPT_VERSION,
        "judge_method": "synthetic scorer contract fixture",
        "dimensions": [
            {
                "id": name,
                "score": 4,
                "reason": "fixture score, not a financial model rating",
                "answer_quotes": [answer],
                "source_excerpts": [{"citation": "E1", "quote": source["quote"]}],
            }
            for name in DIMENSIONS
        ],
    }
    scores["whole_answer"] = score_quality(packets, scores["questions"], [whole], rubric)
    _, bp = diagnose(data, tmp_path, ids=["C07"])
    result, _ = diagnose(
        data,
        tmp_path,
        ids=["C07"],
        verdicts=[verdict(bp[0], disposition="answer", asked=False)],
        answer_scores=scores,
    )
    assert result["cases"][0]["task_result"] == "pass"
    assert result["summary"]["whole_answer_dimensions"]["truthfulness"] == {"mean": 4, "n": 1}
    assert result["summary"]["numeric_coverage_known_lower_bound"]["value"] == 1
    scores["questions"][0]["trace_hash"] = "stale"
    with pytest.raises(ValueError, match="stale_answer"):
        diagnose(data, tmp_path, ids=["C07"], answer_scores=scores)
