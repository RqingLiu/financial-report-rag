"""Credential-free checks of published evidence arithmetic and first-party Markdown links."""

import json
import re
from pathlib import Path
from statistics import mean
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "reports/public/experiments"


def load(name):
    return json.loads((BASE / f"{name}.json").read_text())


def close(actual, expected):
    assert abs(actual - expected) < 1e-12, (actual, expected)


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
            }
        )
    )


if __name__ == "__main__":
    main()
