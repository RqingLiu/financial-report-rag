from copy import deepcopy
from decimal import Decimal

import pytest

from finrag.evaluation.answers import (
    VERSION,
    evaluate,
    fingerprint,
    numeric_result,
    report,
    score_packet,
)


@pytest.fixture
def replay():
    answer = "FY2024 share was about 78.0% [E1]."
    packet = {
        "id": "U99",
        "version": VERSION,
        "query": {"as_of": "2024-04-30", "confirmed_context": {"report_document_id": "A24"}},
        "status": "generated",
        "answer": answer,
        "trace_hash": "fixture",
        "run": "fixture",
        "evidence": [
            {
                "citation": "E1",
                "document_id": "A24",
                "filed_at": "2024-04-25",
                "text": "Share was 78.01 percent.",
            }
        ],
        "checks": [
            {
                "id": "N900",
                "metric": "FY2024 share",
                "unit": "percent",
                "decimal_places": 2,
                "expected": "78.01",
                "exact_decimal": "78.0098",
                "tolerance": {"normal_abs": "0.005", "minor_precision_abs": "0.02"},
            }
        ],
        "rubric": {
            "mandatory_facts": [{"id": "U99:f1", "expected": "FY2024 share"}],
            "expected_limits": [],
            "material_errors": [],
        },
    }
    packet["packet_hash"] = fingerprint(packet)
    verdict = {
        "id": "U99",
        "packet_hash": packet["packet_hash"],
        "judge_method": "fixture",
        "facts": [
            {
                "id": "U99:f1",
                "status": "correct",
                "reason": "Matches the share.",
                "citation_status": "supported",
                "citation_reason": "Same measure and period.",
                "quotes": [answer],
                "sources": [{"citation": "E1", "quote": "Share was 78.01 percent."}],
            }
        ],
        "numbers": [
            {
                "id": "N900",
                "mapping": "aligned",
                "reason": "Explicit approximation.",
                "quote": answer,
                "literal": "78.0",
                "unit": "percent",
                "accept_rounding": True,
            }
        ],
        "limits": [],
        "material_errors": [],
    }
    return packet, verdict


def test_rounding_and_wrong_scope_are_independent(replay):
    packet, verdict = replay
    result = score_packet(packet, verdict)
    assert result["outcome"] == "pass"
    assert result["numbers"][0]["status"] == "correct_rounded"
    bad = deepcopy(verdict)
    bad["numbers"][0].update(mapping="wrong_scope", reason="Prior period, same number.")
    result = score_packet(packet, bad)
    assert result["outcome"] == "fail"
    assert result["numbers"][0]["status"] == "material_error"


def test_numeric_comparison_distinguishes_wrong_value_and_invented_literal(replay):
    packet, verdict = replay
    row = {**verdict["numbers"][0], "quote": "Share was 79.0%", "literal": "79.0"}
    check = packet["checks"][0]
    assert numeric_result(row, check, row["quote"])["status"] == "material_error"
    row["literal"] = "79"
    with pytest.raises(ValueError, match="not an exact literal"):
        numeric_result(row, check, row["quote"])


def test_missing_number_is_not_excluded_and_incomplete_verdict_fails(replay):
    packet, verdict = replay
    verdict["numbers"][0] = {"id": "N900", "mapping": "missing", "reason": "Not stated."}
    score = evaluate([packet], [verdict])
    assert score["numeric_count"] == 1
    assert score["numeric_statuses"] == {"missing": 1}
    assert score["outcomes"] == {"fail": 1}
    verdict["numbers"] = []
    with pytest.raises(ValueError, match="missing or unexpected item IDs"):
        evaluate([packet], [verdict])


def test_replay_rejects_stale_verdict_and_unattached_source(replay):
    packet, verdict = replay
    bad = deepcopy(packet)
    bad["rubric"]["mandatory_facts"][0]["expected"] = "Another metric"
    bad["packet_hash"] = fingerprint(bad)
    with pytest.raises(ValueError, match="verdict does not match packet"):
        score_packet(bad, verdict)
    verdict["facts"][0]["sources"][0]["citation"] = "E2"
    with pytest.raises(ValueError, match="not attached"):
        score_packet(packet, verdict)


@pytest.mark.parametrize("patch", [{"filed_at": "2024-05-01"}, {"document_id": "B24"}])
def test_valid_citation_id_does_not_override_scope(replay, patch):
    packet, verdict = replay
    packet["evidence"][0].update(patch)
    packet["packet_hash"] = verdict["packet_hash"] = fingerprint(packet)
    with pytest.raises(ValueError, match="out-of-scope evidence"):
        score_packet(packet, verdict)


def test_non_generated_attempt_counts_against_end_to_end_rate(replay):
    packet, verdict = replay
    packet.update(answer="", status="clarify")
    packet["packet_hash"] = verdict["packet_hash"] = fingerprint(packet)
    verdict.update(facts=[], numbers=[])
    result = evaluate([packet], [verdict])
    assert (result["attempts"], result["generated"], result["outcomes"]) == (1, 0, {"fail": 1})
    assert result["fact_statuses"] == result["numeric_statuses"] == {"not_generated": 1}


def test_explicit_decrease_amount_is_not_a_negative_level(replay):
    packet, verdict = replay
    check = {**packet["checks"][0], "expected": "-78.00", "exact_decimal": "-78"}
    row = {**verdict["numbers"][0], "literal": "78", "direction": -1}
    for quote in ["Revenue decreased by 78 units.", "收入减少78单位。"]:
        assert numeric_result({**row, "quote": quote}, check, quote)["status"] == "correct"
    for quote in ["Revenue decreased to 78 units.", "收入下降至78单位。", "收入增加78单位。"]:
        with pytest.raises(ValueError, match="adjacent decrease"):
            numeric_result({**row, "quote": quote}, check, quote)


def test_explicit_display_unit_conversion_keeps_literal_and_checks_scale(replay):
    packet, verdict = replay
    check = {
        **packet["checks"][0],
        "unit": "USD_million",
        "expected": "440",
        "exact_decimal": "440",
        "decimal_places": 0,
    }
    row = {
        **verdict["numbers"][0],
        "quote": "MI308净费用约4.4亿美元。",
        "literal": "4.4",
        "unit": "USD_million",
        "display_unit": "USD_100million",
    }
    result = numeric_result(row, check, row["quote"])
    assert result["status"] == "correct"
    assert Decimal(result["observed"]) == 440
    assert result["unit_scale"] == "100"
    # The same written number without conversion is a real magnitude error.
    wrong = {k: v for k, v in row.items() if k != "display_unit"}
    assert numeric_result(wrong, check, wrong["quote"])["status"] == "material_error"
    for bad in [
        {**row, "display_unit": "arbitrary_100x"},
        {**row, "quote": "MI308净费用4.4百万美元。"},
    ]:
        with pytest.raises(ValueError):
            numeric_result(bad, check, bad["quote"])


def test_converted_rounding_uses_the_precision_of_the_written_unit(replay):
    packet, verdict = replay
    check = {
        **packet["checks"][0],
        "unit": "USD_million",
        "expected": "443",
        "exact_decimal": "443",
        "decimal_places": 0,
    }
    row = {
        **verdict["numbers"][0],
        "quote": "净费用约4.4亿美元。",
        "literal": "4.4",
        "unit": "USD_million",
        "display_unit": "USD_100million",
    }
    assert numeric_result(row, check, row["quote"])["status"] == "correct_rounded"


def test_failed_answer_report_keeps_required_numeric_denominator(replay):
    packet, verdict = replay
    packet.update(answer="", status="error")
    packet["query"]["question"] = "What was the share?"
    packet["packet_hash"] = verdict["packet_hash"] = fingerprint(packet)
    verdict.update(facts=[], numbers=[])
    output = report(evaluate([packet], [verdict]), [packet])
    assert "1 项应查数值均保留在分母，计 not_generated" in output
    assert "无适用的冻结数值检查" not in output
