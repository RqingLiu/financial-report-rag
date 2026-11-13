"""Provider-free loader for accepted, purpose-scoped evaluation bundles."""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from finrag.agent.planner import Request
from finrag.core.files import digest, read_jsonl
from finrag.core.models import Evidence

QUERY_FIELDS = {"id", "question", "reading_context", "confirmed_context", "as_of", "corpus_scope"}
DISPOSITIONS = {"answer", "partial_answer", "clarify", "unavailable", "unsupported"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def indexed(rows):
    result = {r["id"]: r for r in rows}
    require(len(result) == len(rows), "duplicate_dataset_id")
    return result


@dataclass
class Dataset:
    path: Path
    identity: str
    manifest: dict
    queries: dict
    cases: dict
    rubrics: dict
    numbers: dict

    def select(self, ids=None):
        selected = list(ids) if ids is not None else list(self.queries)
        require(selected and len(set(selected)) == len(selected), "empty_or_duplicate_selection")
        require(set(selected) <= self.queries.keys(), "unknown_selected_case")
        return selected


def load_dataset(path):
    path = Path(path).resolve()
    raw = (path / "manifest.json").read_bytes()
    manifest = json.loads(raw)
    require(manifest.get("role") == "development", "unsupported_dataset_role")
    outputs = manifest["outputs_sha256"]
    required = {
        "retrieval_queries.jsonl",
        "cases.jsonl",
        "rubrics.jsonl",
        "numeric_checks.jsonl",
        "reference_answers.md",
        "evidence_catalog.jsonl",
    }
    require(required <= outputs.keys(), "incomplete_dataset_manifest")
    for name, expected in outputs.items():
        target = path / name
        require(Path(name).name == name and not target.is_symlink(), "unsafe_dataset_path")
        require(digest(target.read_bytes()) == expected, f"dataset_hash_mismatch:{name}")
    queries = indexed(read_jsonl(path / "retrieval_queries.jsonl"))
    cases = indexed(read_jsonl(path / "cases.jsonl"))
    rubrics = indexed(read_jsonl(path / "rubrics.jsonl"))
    numbers = indexed(read_jsonl(path / "numeric_checks.jsonl"))
    require(queries.keys() == cases.keys() == rubrics.keys(), "inconsistent_dataset_ids")
    require(len(queries) == manifest["cases"], "dataset_count_mismatch")
    references = (path / "reference_answers.md").read_text()
    catalog = read_jsonl(path / "evidence_catalog.jsonl")
    by_block = {r["block_id"]: r for r in catalog}
    for qid, query in queries.items():
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", qid) and ".." not in qid,
            "unsafe_dataset_id",
        )
        require(set(query) == QUERY_FIELDS, "query_only_fields_required")
        Request(
            **{k: query[k] for k in ("question", "reading_context", "confirmed_context", "as_of")}
        )
        case, rubric = cases[qid], rubrics[qid]
        require(case.get("ready_for_development") is True, "case_not_ready_for_development")
        require(
            case["expected_dispositions"] and set(case["expected_dispositions"]) <= DISPOSITIONS,
            "invalid_expected_disposition",
        )
        indexed(case["behavior_criteria"])
        require(case["behavior_criteria"], "missing_behavior_criteria")
        require(
            re.search(rf"^## {re.escape(qid)}\s*$", references, re.MULTILINE), "missing_reference"
        )
        parent = case.get("parent_case_id")
        if parent is not None:
            require(parent in cases and cases[parent]["family"] == case["family"], "family_leakage")
        for group in case["evidence_groups"]:
            require(group, "empty_evidence_alternative_group")
            for ref in group:
                e = Evidence(**ref)
                source = by_block.get(e.block_id)
                require(
                    source is not None and source["document_id"] == e.document_id,
                    "unknown_source_span",
                )
                offset = e.start - source["start"]
                require(
                    offset >= 0
                    and e.end <= source["end"]
                    and e.end - e.start == len(e.quote)
                    and source["quote"][offset : offset + len(e.quote)] == e.quote,
                    "invalid_source_span",
                )
                require(source["filed_at"] <= query["as_of"], "future_evidence_label")
        require(
            bool(case["evidence_groups"]) == rubric["retrieval_applicable"],
            "inconsistent_retrieval_applicability",
        )
        indexed(rubric["mandatory_facts"])
        require(
            len(set(rubric["numeric_check_ids"])) == len(rubric["numeric_check_ids"]),
            "duplicate_numeric_requirement",
        )
        for nid in rubric["numeric_check_ids"]:
            require(nid in numbers and qid in numbers[nid]["case_ids"], "numeric_scope_mismatch")
    for n in numbers.values():
        require(set(n["case_ids"]) <= queries.keys(), "unknown_numeric_case")
        for item in n["inputs"]:
            if "check_id" in item:
                require(item["check_id"] in numbers, "missing_numeric_dependency")
    return Dataset(path, digest(raw), manifest, queries, cases, rubrics, numbers)
