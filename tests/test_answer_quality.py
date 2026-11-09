import json
from pathlib import Path

import pytest

from finrag.evaluation.rubric import (
    DIMENSIONS,
    PROMPT_VERSION,
    judge_inputs,
    rubric_hash,
    score_quality,
)

RUBRIC_PATH = (
    Path(__file__).resolve().parents[1]
    / "specs/009-answer-evaluation/contracts/whole_answer_rubric.json"
)


@pytest.fixture
def example():
    rubric = json.loads(RUBRIC_PATH.read_text())
    answer = "FY2024 revenue was 20 million [E1]."
    packet = {
        "id": "U99",
        "packet_hash": "test-packet",
        "status": "generated",
        "query": {"question": "Revenue?"},
        "answer": answer,
        "reference": "Reference-only wording",
        "rubric": {"mandatory_facts": []},
        "checks": [],
        "evidence": [
            {
                "citation": "E1",
                "document_id": "A24",
                "filed_at": "2024-01-30",
                "text": "Reported revenue was 20 million.",
            }
        ],
    }
    diagnostics = {
        "id": "U99",
        "numbers": [],
        "material_errors": [],
        "observations": [],
        "evidence_after_cutoff": [],
        "evidence_outside_confirmed_document": [],
    }
    verdict = {
        "id": "U99",
        "packet_hash": "test-packet",
        "rubric_hash": rubric_hash(rubric),
        "prompt_version": PROMPT_VERSION,
        "judge_method": "fixture-judge",
        "dimensions": [
            {
                "id": k,
                "score": 5,
                "reason": "Matches the relevant criterion.",
                "answer_quotes": [answer],
                "source_excerpts": [],
            }
            for k in DIMENSIONS
        ],
    }
    return packet, diagnostics, verdict, rubric


def test_export_keeps_reference_separate_from_context(example):
    packet, _, verdict, rubric = example
    (envelope,) = judge_inputs([packet], rubric)
    data = json.loads(envelope["messages"][1]["content"])
    assert data["output_form"]["rubric_hash"] == verdict["rubric_hash"]
    assert data["output_form"]["packet_hash"] == packet["packet_hash"]
    assert data["reference_only_for_review"]["answer"] == packet["reference"]
    assert packet["reference"] not in json.dumps(data["runtime_evidence"])


def test_material_error_caps_truthfulness_without_lowering_clarity(example):
    p, d, v, r = example
    d["numbers"] = [{"status": "material_error"}]
    with pytest.raises(ValueError, match="material error caps truthfulness"):
        score_quality([p], [d], [v], r)
    next(x for x in v["dimensions"] if x["id"] == "truthfulness")["score"] = 2
    result = score_quality([p], [d], [v], r)
    assert result["metrics"]["truthfulness"] == {"mean": 2.0, "n": 1}
    assert result["metrics"]["clarity"] == {"mean": 5.0, "n": 1}


def test_missing_dimension_and_rubric_changes_fail_validation(example):
    p, d, v, r = example
    v["dimensions"].pop()
    with pytest.raises(ValueError, match="missing or duplicate dimension"):
        score_quality([p], [d], [v], r)
    r["dimensions"][0]["anchors"]["5"] = "A materially changed standard."
    with pytest.raises(ValueError, match="stale whole-answer verdict"):
        score_quality([p], [d], [v], r)


@pytest.mark.parametrize("bad", [0, 6, True, 3.5])
def test_score_must_be_ordinal_integer(example, bad):
    p, d, v, r = example
    v["dimensions"][0]["score"] = bad
    with pytest.raises(ValueError, match="integer 1–5 or null"):
        score_quality([p], [d], [v], r)


def test_unverifiable_evidence_excerpt_is_rejected(example):
    p, d, v, r = example
    v["dimensions"][0]["source_excerpts"] = [{"citation": "E1", "quote": "Different data."}]
    with pytest.raises(ValueError, match="invalid source excerpt"):
        score_quality([p], [d], [v], r)


def test_unscored_and_non_generated_are_visible_without_fabricating_scores(example):
    p, d, v, r = example
    v["dimensions"][0].update(score=None, reason="Needs human review.", answer_quotes=[])
    other = {"id": "U98", "status": "error"}
    result = score_quality([p, other], [d, {"id": "U98"}], [v], r)
    assert result["attempts"] == 2 and result["generated"] == 1
    assert result["metrics"]["completeness"] == {"mean": None, "n": 0}
    assert result["metrics"]["truthfulness"]["n"] == 1
    assert "U98" not in result["by_question"]
