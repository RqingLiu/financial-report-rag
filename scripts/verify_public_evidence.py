"""Credential-free checks of published evidence arithmetic and first-party Markdown links."""

import json
import re
from collections import Counter
from pathlib import Path
from statistics import mean
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "reports/public/experiments"


def load(name):
    return json.loads((BASE / f"{name}.json").read_text())


def close(actual, expected):
    assert abs(actual - expected) < 1e-12, (actual, expected)


def verify_baseline41():
    data = json.loads((ROOT / "reports/public/baseline41.json").read_text())
    cases, summary = data["cases"], data["answer_review"]
    assert len(cases) == len({c["id"] for c in cases}) == summary["attempted"] == 41
    assert Counter(c["task_result"] for c in cases) == summary["integrated_task_results"]
    assert sum(c["execution"] == "completed" for c in cases) == summary["generated"] == 38
    facts = sum((Counter(c["fact_statuses"]) for c in cases), Counter())
    numbers = sum((Counter(c["numeric_statuses"]) for c in cases), Counter())
    assert facts == summary["fact_completeness"]["statuses"]
    assert numbers == summary["numeric_required_coverage"]["statuses"]
    fact_points = facts["correct"] + 0.5 * facts["partial"]
    close(fact_points, summary["fact_completeness"]["points"])
    close(fact_points / sum(facts.values()), summary["fact_completeness"]["value"])
    numeric_correct = numbers["correct"] + numbers["correct_rounded"]
    assert numeric_correct == summary["numeric_required_coverage"]["correct"]
    close(numeric_correct / sum(numbers.values()), summary["numeric_required_coverage"]["value"])
    assert sum(c["required_facts"] for c in cases) == sum(facts.values()) == 80
    assert sum(c["required_numbers"] for c in cases) == sum(numbers.values()) == 84
    citation_counts = sum((Counter(c["citation_statuses"]) for c in cases), Counter())
    citations = summary["citation_support_precision"]
    assert citation_counts["supported"] == citations["fully_supported"] == 61
    assert citation_counts["partial"] == citations["partial"] == 4
    close(61 / 65, citations["value"])
    close(61 / 73, summary["citation_required_delivery_coverage"]["value"])
    close(61 / 80, summary["citation_literal_all_fact_coverage"]["value"])
    assert sorted(c["id"] for c in cases if c["material_error"]) == summary["material_error_cases"]
    for dimension, metric in summary["whole_answer_dimensions"].items():
        scores = [c["whole_answer_scores"][dimension] for c in cases if c["whole_answer_scores"]]
        assert len(scores) == 38 and sum(scores) == metric["sum"]
        close(mean(scores), metric["generated_mean"])
        close(sum(scores) / 41, metric["delivery_adjusted_mean"])
    for stage, key in (
        ("candidate", "candidate"),
        ("shortlist", "coarse_top80"),
        ("context", "context"),
    ):
        values = [c["stage_coverage"].get(stage, {}).get("value") for c in cases]
        values = [v for v in values if isinstance(v, (int, float))]
        metric = data["execution"]["stage_metrics"][key]
        assert len(values) == metric["recorded_cases"] == 34
        close(mean(values), metric["macro_over_recorded"])
        close(sum(values) / 37, metric["confirmed_coverage_lower_bound_all_positive"])
    return len(cases)


def main():
    checked = 0
    for name in ("context", "rerank"):
        d = load(name)
        for summary in d["metrics"]:
            rows = [r for r in d["per_question"] if r["variant"] == summary["variant"]]
            assert len(rows) == summary["n"] == 20
            close(mean(r["score"]["recall"] for r in rows), summary["macro_recall"])
            assert sum(r["score"]["groups_found"] for r in rows) == summary["micro_found"]
            assert sum(r["score"]["groups_required"] for r in rows) == 225
            assert sum(r["score"]["complete"] for r in rows) == summary.get(
                "complete", summary.get("complete_questions")
            )
            checked += 1
    for name in ("focused", "coarse"):
        d = load(name)
        group = "arm" if name == "focused" else "variant"
        for summary in d["summary"]:
            rows = [r for r in d["per_question"] if r[group] == summary[group]]
            assert len(rows) == summary["n"] == 20
            for stage in (
                ("candidate", "shortlist", "context")
                if name == "focused"
                else ("shortlist", "context")
            ):
                close(mean(r[stage]["recall"] for r in rows), summary[stage]["macro_recall"])
                assert sum(r[stage]["groups_found"] for r in rows) == summary[stage]["micro_found"]
                assert sum(r[stage]["groups_required"] for r in rows) == 225
            checked += 1
    d = load("serving")
    for summary in d["metrics"]:
        rows = [
            r
            for r in d["per_question"]
            if (r["arm"], r["ranker"]) == (summary["arm"], summary["ranker"])
        ]
        assert len(rows) == summary["n"] == 20
        assert sum(r["sql_jobs"] for r in rows) == summary["sql_jobs"] == 342
        for stage in ("candidate", "ranked_candidate", "final_context"):
            close(mean(r["scores"][stage]["recall"] for r in rows), summary[stage])
        assert (
            sum(r["scores"]["final_context"]["groups_found"] for r in rows)
            == summary["groups_found"]
        )
        assert sum(r["scores"]["final_context"]["complete"] for r in rows) == summary["complete"]
        checked += 1
    demo = load("recorded_demo")["success"]
    cited = set(re.findall(r"\[(E\d+)\]", json.dumps(demo["structured_answer"])))
    assert cited <= {e["citation"] for e in demo["evidence"]}
    paths = [
        ROOT / "README.md",
        ROOT / "README.zh-CN.md",
        *sorted((ROOT / "docs").glob("*.md")),
        *sorted((ROOT / "reports/public").rglob("*.md")),
    ]
    links = 0
    for path in paths:
        text = re.sub(r"```.*?```", "", path.read_text(), flags=re.DOTALL)
        for target in re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", text):
            target = target.strip().strip("<>")
            if urlsplit(target).scheme or target.startswith("#"):
                continue
            local = (path.parent / unquote(target.split("#", 1)[0])).resolve()
            assert local.is_relative_to(ROOT) and local.exists(), (
                f"{path.name}: broken local link {target}"
            )
            links += 1
    print(
        json.dumps(
            {
                "experiment_arms_recomputed": checked,
                "local_doc_links": links,
                "demo_citations_resolve": True,
                "baseline_cases_recomputed": verify_baseline41(),
            }
        )
    )


if __name__ == "__main__":
    main()
