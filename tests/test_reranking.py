import json
import signal
import time

import pytest
from test_need_context import hit, inputs

from finrag.answering import answer_messages
from finrag.deadlines import DeadlineLLM
from finrag.generation import Budget, BudgetExceeded, ProviderFailure
from finrag.models import Block
from finrag.planning import PipelineConfig, PlanRejected
from finrag.rerank_context import compact_source, prompt_tokens, select_reranked
from finrag.reranking import grade_candidates, source_lines, validate_grades


def data():
    _, plan = inputs()
    return {
        "inputs": {
            "original_question": "NEWCO facts",
            "reading_context": "",
            "confirmed_context": None,
            "as_of": "2026-10-11",
        },
        "plan": plan.model_dump(mode="json"),
        "reference": "GOLD_CANARY",
    }


def test_grade_ids_need_ids_and_source_lines_fail_closed():
    candidates = [{"chunk_id": "c", "lines": ["Revenue 100", "Cost 50"]}]
    valid = {"scores": [{"i": 0, "s": 4, "n": ["n1"], "l": [[1, 1]], "r": "direct"}]}
    assert validate_grades(json.dumps(valid), candidates, {"n1"})["c"]["s"] == 4
    valid["scores"][0]["l"] = [[1, 3]]
    with pytest.raises(PlanRejected, match="line_range_invalid"):
        validate_grades(json.dumps(valid), candidates, {"n1"})
    valid["scores"][0]["l"] = [[1, 1]]
    valid["scores"][0]["n"] = ["invented"]
    with pytest.raises(PlanRejected, match="unknown_or_duplicate_need"):
        validate_grades(json.dumps(valid), candidates, {"n1"})
    valid["scores"][0]["i"] = 2
    with pytest.raises(PlanRejected, match="candidate_ids_mismatch"):
        validate_grades(json.dumps(valid), candidates, {"n1"})


def test_compaction_only_claims_actual_rows_and_keeps_headers():
    filing, _ = inputs()
    # Generic unseen issuer, opaque doc ID; no financial term list in extraction logic.
    text = "Year ended\n2025 | 2024\nUSD millions\nMetric | value\nRevenue | 100\nUnrelated | 777\n"
    h = hit("b", text)
    block = Block(
        id="b",
        document_id=h.chunk.document_id,
        ordinal=3,
        kind="table",
        section="Item 8",
        text=text,
        start=0,
        end=len(text),
        locator={},
    )
    compact, rendered = compact_source(h, {"l": [[5, 5]]}, {"b": block}, filing)
    assert "Revenue | 100" in rendered and "USD millions" in rendered
    assert "Unrelated | 777" not in rendered
    assert compact.chunk.id != h.chunk.id and not compact.expanded_spans
    assert all(s["end"] <= text.index("Unrelated") for s in compact.chunk.spans)
    for span in compact.chunk.spans:
        assert text[span["start"] : span["end"]] in rendered
    assert len(source_lines(h, {"b": block})) == 6


def test_cache_and_bounded_schema_repair_never_receive_reference_answer(tmp_path):
    d = data()
    candidates = [{"chunk_id": "c", "source": {"ticker": "NEWCO"}, "lines": ["Revenue 100"]}]

    class LLM:
        calls = 0

        def generate(self, messages, **kwargs):
            self.calls += 1
            assert "GOLD_CANARY" not in json.dumps(messages)
            return {
                "finish_reason": "stop",
                "peak_list_cost_usd": "0.001",
                "answer": json.dumps(
                    {"scores": [{"i": 0, "s": 4, "n": ["n1"], "l": [[1, 1]], "r": "direct"}]}
                ),
            }

    llm = LLM()
    args = (d["inputs"], d["plan"], candidates, llm, tmp_path / "cache", tmp_path / "logs")
    assert grade_candidates(*args)[0]["c"]["s"] == 4
    assert grade_candidates(*args)[1][0]["cached"] is True
    assert llm.calls == 1

    class Invalid(LLM):
        def generate(self, messages, **kwargs):
            self.calls += 1
            return {"finish_reason": "stop", "peak_list_cost_usd": "0.001", "answer": "{}"}

    bad = Invalid()
    with pytest.raises(PlanRejected, match="schema_invalid"):
        grade_candidates(
            d["inputs"], d["plan"], candidates, bad, tmp_path / "bad", tmp_path / "badlogs"
        )
    assert bad.calls == 2
    assert len(json.loads(next((tmp_path / "badlogs").glob("*.json")).read_text())["attempts"]) == 2


def test_full_prompt_cap_is_enforced_independently_of_evidence_cap():
    filing, _ = inputs()
    h = hit("b", "Requested fact is 100.")
    block = Block(
        id="b",
        document_id=h.chunk.document_id,
        ordinal=1,
        kind="text",
        section="Item 7",
        text=h.chunk.text,
        start=0,
        end=len(h.chunk.text),
        locator={},
    )
    d = data()
    assert "GOLD_CANARY" not in json.dumps(answer_messages({**d, "runtime_evidence": []}))
    grade = {"b": {"s": 4, "n": ["n1"], "l": [[1, 1]]}}
    selected, _, _, meta = select_reranked(
        [h],
        grade,
        {"b": block},
        None,
        {filing.id: filing},
        PipelineConfig(),
        d,
        evidence_cap=1000,
        prompt_cap=prompt_tokens(d, []),
        compact=True,
    )
    assert not selected and meta["evidence_tokens"] == 0
    assert meta["decisions"][0]["decision"] == "full_prompt_budget"


@pytest.mark.skipif(not hasattr(signal, "setitimer"), reason="serial POSIX CLI deadline")
def test_absolute_deadline_restores_handler_and_keeps_unknown_charge_reserved(tmp_path):
    budget = Budget(tmp_path / "budget.jsonl", stop_usd="0.002")
    previous = signal.getsignal(signal.SIGALRM)

    class LLM:
        def generate(self, *args, **kwargs):
            budget.reserve("0.001", "mock", "timeout_test")
            time.sleep(1)

    with pytest.raises(ProviderFailure, match="absolute_deadline_billing_unknown"):
        DeadlineLLM(LLM(), seconds=0.01).generate([])
    assert signal.getsignal(signal.SIGALRM) == previous
    assert signal.getitimer(signal.ITIMER_REAL)[0] == 0
    assert budget.snapshot()["unresolved_reserved_usd"] == "0.001"
    with pytest.raises(BudgetExceeded):
        budget.reserve("0.001", "mock", "must_not_ignore_pending_charge")
