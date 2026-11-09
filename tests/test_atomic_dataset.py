"""Atomic labels preserve lineage and scope without putting review data into runtime inputs."""

import importlib.util
import json
from pathlib import Path

import pytest

from finrag.core.files import atomic_json, digest, write_jsonl
from finrag.evaluation.answers import prepare

ROOT = Path(__file__).resolve().parents[1]
module_spec = importlib.util.spec_from_file_location(
    "atomic_builder", ROOT / "scripts/build_golden_v3.py"
)
builder = importlib.util.module_from_spec(module_spec)
module_spec.loader.exec_module(builder)


@pytest.fixture(scope="module")
def artifact():
    return builder.build()


def test_deterministic_artifacts_and_frozen_parent(artifact):
    before = {str(p): digest(p.read_bytes()) for p in builder.PARENT.iterdir() if p.is_file()}
    files, manifest = artifact
    again, second = builder.build()
    assert files == again and manifest == second
    assert before == {
        str(p): digest(p.read_bytes()) for p in builder.PARENT.iterdir() if p.is_file()
    }
    assert all((builder.OUT / name).read_bytes() == content for name, content in files.items())
    assert manifest["parents"] == 20 and manifest["children"] == 81
    assert manifest["numeric_check_ids"] == 123 and manifest["numeric_check_occurrences"] == 144


def test_scoped_rubrics_boundaries_and_no_runtime_gold(artifact):
    files, _ = artifact
    read = lambda n: [json.loads(s) for s in files[n].decode().splitlines() if s]
    questions = {r["id"]: r for r in read("golden.jsonl")}
    queries = read("retrieval_queries.jsonl")
    rubrics = {r["id"]: r for r in read("rubrics.jsonl")}
    assert all(
        set(q)
        == {"id", "question", "reading_context", "confirmed_context", "as_of", "corpus_scope"}
        for q in queries
    )
    assert len(questions["U01.02"]["evidence_groups"]) < 12
    assert rubrics["U01.04"]["numeric_check_ids"] == []
    assert not questions["U01.04"]["retrieval_applicable"]
    assert questions["U01.04"]["reference_evidence_ids"] == []
    assert questions["U01.04"]["evidence_group_metadata"] == []
    assert all("approval" not in q and "ready_for_scoring" not in q for q in questions.values())
    assert all(
        group["id"].startswith(q["id"] + ":g")
        for q in questions.values()
        for group in q["evidence_group_metadata"]
    )
    assert questions["U03.01"]["split_group"] == questions["U17.01"]["split_group"]
    assert (
        questions["U03.01"]["related_intent_group"] == questions["U17.01"]["related_intent_group"]
    )
    assert "557" not in next(q["question"] for q in queries if q["id"] == "U04.03")
    assert "N043" not in rubrics["U13.01"]["numeric_check_ids"]
    assert "N043" in rubrics["U17.02"]["numeric_check_ids"]
    assert set(questions["U14.01"]["documents"]) == {"NVDA_FY2024"}
    assert all(q["split"] == "dev" and "pending" in q["review_status"] for q in questions.values())


def test_lost_parent_requirement_fails_build(tmp_path):
    specs = builder.load(builder.OUT / "split_specs.json")
    row = next(r for r in specs["rows"] if r["id"] == "U01.02")
    row["numeric_check_ids"].remove("N005")
    atomic_json(tmp_path / "split_specs.json", specs)
    with pytest.raises(ValueError, match="unaccounted checks"):
        builder.build(out=tmp_path)


def test_safe_child_ids_and_literal_reference_heading(tmp_path):
    golden, traces = tmp_path / "golden", tmp_path / "traces"
    golden.mkdir()
    traces.mkdir()
    q = {
        "id": "U01.01",
        "question": "Revenue?",
        "reading_context": "",
        "confirmed_context": None,
        "as_of": "2030-01-01",
        "corpus_scope": {"ACME": [2029]},
    }
    write_jsonl(golden / "retrieval_queries.jsonl", [q])
    write_jsonl(golden / "rubrics.jsonl", [{"id": q["id"], "numeric_check_ids": []}])
    write_jsonl(golden / "numeric_checks.jsonl", [])
    (golden / "reference_answers.md").write_text(
        "## U01x01\nWrong\n## U01.01\nCorrect\n## U02.01\nOther\n"
    )
    atomic_json(
        traces / "U01.01.json",
        {
            "query_id": q["id"],
            "inputs": {
                "original_question": q["question"],
                **{
                    k: q[k]
                    for k in ("reading_context", "confirmed_context", "as_of", "corpus_scope")
                },
            },
            "status": "generated",
            "generation": {"answer": "Saved answer"},
            "runtime_evidence": [],
        },
    )
    packets = prepare(traces, golden, ["U01.01"])
    assert packets[0]["reference"] == "Correct"
    with pytest.raises(ValueError, match="unsafe"):
        prepare(traces, golden, ["../U01"])
