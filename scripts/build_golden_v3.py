"""Build an offline, reviewable atomic DEV derivative without changing the reviewed v2 release."""

import argparse
import json
import re
from collections import defaultdict
from pathlib import Path

from finrag.core.files import digest
from finrag.core.models import Question

ROOT = Path(__file__).resolve().parents[1]
PARENT = ROOT / "data/evaluation/golden_v2"
OUT = ROOT / "data/evaluation/golden_v3"
REF = re.compile(r"\[((?:NVDA|AMD|MU)\d{2}\.\d+)\]")


def load(path):
    return json.loads(path.read_text())


def lines(path):
    return [json.loads(s) for s in path.read_text().splitlines() if s.strip()]


def encoded(value, *, jsonl=False):
    if jsonl:
        return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in value).encode()
    return (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode()


def require(value, message):
    if not value:
        raise ValueError(message)


def project_table(text, columns):
    rows = [r for r in text.splitlines() if r.strip()]
    require(all(r.startswith("|") and r.endswith("|") for r in rows), "not a markdown table")
    cells = [[c.strip() for c in r.split("|")[1:-1]] for r in rows]
    require(len(cells) >= 3 and all(len(c) == len(cells[0]) for c in cells), "ragged table")
    require(columns and len(set(columns)) == len(columns), "duplicate table columns")
    require(all(0 <= c < len(cells[0]) for c in columns), "table column out of bounds")
    return "\n".join(
        "| " + " | ".join(cells[i][j] for j in columns) + " |" for i in range(len(cells))
    )


def reference(parts, parent):
    paragraphs = parent["answer_markdown"].split("\n\n")
    rendered = []
    for part in parts:
        require(set(part) <= {"paragraph", "columns", "text"}, "unknown reference selector")
        if "text" in part:
            require(set(part) == {"text"}, "ambiguous reference selector")
            rendered.append(part["text"])
        else:
            text = paragraphs[part["paragraph"]]
            rendered.append(project_table(text, part["columns"]) if "columns" in part else text)
    answer = "\n\n".join(rendered)
    require(
        answer.strip() and not re.search(r"见U\d|见上题|如上所述", answer),
        "non-standalone reference",
    )
    return answer


def build(parent=PARENT, out=OUT):
    specs = load(out / "split_specs.json")
    sources = {
        n: parent / n
        for n in [
            "answer_specs.json",
            "golden.jsonl",
            "rubrics.jsonl",
            "numeric_checks.jsonl",
            "evidence_catalog.jsonl",
            "retrieval_queries.jsonl",
            "label_specs.json",
        ]
    }
    hashes = {
        str(p.relative_to(ROOT)) if p.is_relative_to(ROOT) else p.name: digest(p.read_bytes())
        for p in sources.values()
    }
    answers = {r["id"]: r for r in load(sources["answer_specs.json"])}
    gold = {r["id"]: r for r in lines(sources["golden.jsonl"])}
    rubrics = {r["id"]: r for r in lines(sources["rubrics.jsonl"])}
    queries = {r["id"]: r for r in lines(sources["retrieval_queries.jsonl"])}
    labels = {r["id"]: r for r in load(sources["label_specs.json"])}
    checks = {r["id"]: r for r in lines(sources["numeric_checks.jsonl"])}
    catalog = {r["id"]: r for r in lines(sources["evidence_catalog.jsonl"])}
    require(len(specs["rows"]) == len({r["id"] for r in specs["rows"]}), "duplicate child ID")
    child_ids = {r["id"] for r in specs["rows"]}
    records, qrows, rs, ragas, lineage, planner = [], [], [], [], [], []
    # Families joined by a shared child intent must never be split across dev/test later.
    parents = {r["id"]: r["id"] for r in specs["rows"]}

    def find(x):
        while parents[x] != x:
            x = parents[x]
        return x

    family_members, related_members = defaultdict(list), defaultdict(list)
    for s in specs["rows"]:
        family_members[gold[s["parent_id"]]["family"]].append(s["id"])
        related_members[s["related_intent_group"]].append(s["id"])
    for members in [*family_members.values(), *related_members.values()]:
        for cid in members[1:]:
            parents[find(cid)] = find(members[0])
    split_groups = {
        cid: "family_component_" + min(k for k in parents if find(k) == find(cid))
        for cid in parents
    }
    seen, check_cases, used_sources = (
        defaultdict(lambda: defaultdict(set)),
        defaultdict(list),
        set(),
    )
    by_parent = defaultdict(list)
    review = [
        f"# {len(specs['rows'])}个独立意图：问题与参考答案（待复核）",
        "",
        "答案从已审核父题及其原始数值检查分配；新的拆分、映射和表格投影未逐条人工审核。全部为dev。",
        "",
    ]
    mapping = [
        "# 原20题与子题对应表",
        "",
        "| 原题 | 子题 | 意图 | 类型 | 数值检查 |",
        "| --- | --- | --- | --- | --- |",
    ]
    for s in specs["rows"]:
        pid, cid = s["parent_id"], s["id"]
        require(
            pid in gold and re.fullmatch(re.escape(pid) + r"\.\d{2}", cid), "invalid lineage ID"
        )
        require(s["facts"] and s["answer_parts"], f"{cid}: empty scoped answer or rubric")
        answer = reference(s["answer_parts"], answers[pid])
        refs = set(REF.findall(answer))
        allowed = set(REF.findall(answers[pid]["answer_markdown"]))
        allowed.update(
            a for n in rubrics[pid]["numeric_check_ids"] for a in checks[n]["source_aliases"]
        )
        allowed.update(
            a["alias"] for g in labels[pid]["evidence_groups"] for a in g["alternatives"]
        )
        require(
            refs <= allowed and refs <= catalog.keys(),
            f"{cid}: unknown/unreviewed source IDs {refs - allowed | refs - catalog.keys()}",
        )
        indexes = s["parent_group_indexes"]
        require(len(indexes) == len(set(indexes)), f"{cid}: duplicate evidence group")
        groups = [gold[pid]["evidence_groups"][i] for i in indexes]
        extra_criteria = []
        for extra in s.get("additional_source_groups", []):
            alias, quote = extra["alias"], extra["quote"]
            require(
                alias in allowed and quote in catalog[alias]["quote"],
                f"{cid}: ungrounded added span",
            )
            source = catalog[alias]
            start = source["start"] + source["quote"].index(quote)
            groups.append(
                [
                    {
                        "document_id": source["document_id"],
                        "block_id": source["block_id"],
                        "start": start,
                        "end": start + len(quote),
                        "quote": quote,
                    }
                ]
            )
            extra_criteria.append(extra["criterion"])
            refs.add(alias)
        limits = list(s["expected_limits"]) or [
            rubrics[pid]["expected_limits"][i] for i in s["parent_limit_indexes"]
        ]
        errors = list(s["material_errors"]) or [
            rubrics[pid]["material_errors"][i] for i in s["parent_error_indexes"]
        ]
        # Custom child wording must still account for inherited constraints in lineage.
        require(
            set(s["parent_fact_ids"]) <= {f["id"] for f in rubrics[pid]["mandatory_facts"]},
            f"{cid}: foreign fact",
        )
        require(
            set(s["numeric_check_ids"]) <= set(rubrics[pid]["numeric_check_ids"]),
            f"{cid}: foreign check",
        )
        for n in s["numeric_check_ids"]:
            check_cases[n].append(cid)
            refs.update(checks[n]["source_aliases"])
        # Include exact source catalog entries for every inherited span, not just inline citations.
        span_blocks = {e["block_id"] for group in groups for e in group}
        refs.update(k for k, e in catalog.items() if e["block_id"] in span_blocks)
        used_sources.update(refs)
        query = {
            **queries[pid],
            "id": cid,
            "question": s["question"],
            "reading_context": "分析范围以问题中指定公司和财年为准；资料截止日及确认约束见请求字段。",
        }
        qrows.append(query)
        docs = sorted({catalog[a]["document_id"] for a in refs})
        require(s["expected_scope"], f"{cid}: missing explicit company/year scope")
        require(
            {d.split("_FY")[0] for d in docs} <= s["expected_scope"].keys(),
            f"{cid}: unrelated company in answer/evidence",
        )
        parent_scope = {e["document_id"] for g in gold[pid]["evidence_groups"] for e in g}
        require(
            set(docs) <= parent_scope | set(gold[pid]["documents"]), f"{cid}: source scope widened"
        )
        cutoff = query["as_of"]
        require(all(catalog[a]["filed_at"] <= cutoff for a in refs), f"{cid}: future evidence")
        confirmed = query["confirmed_context"] or {}
        require(
            not confirmed.get("report_document_id")
            or set(docs) <= {confirmed["report_document_id"]},
            f"{cid}: confirmation lost",
        )
        derivation = {
            "parent_id": pid,
            "parent_family": gold[pid]["family"],
            "parent_fact_ids": s["parent_fact_ids"],
            "parent_group_indexes": indexes,
            "reference_selectors": s["answer_parts"],
            "source_release": "golden_v2",
            "review_status": specs["review_status"],
        }
        r = {
            "id": cid,
            "question": s["question"],
            "question_en": "",
            "reference": answer,
            "evidence_groups": groups,
            "documents": docs,
            "category": s["task_type"],
            "family": gold[pid]["family"],
            "language": "zh",
            "outcome": "answer",
            "as_of": cutoff,
            "dataset_role": "development_atomic_draft",
            "parent_id": pid,
            "split": "dev",
            "split_group": split_groups[cid],
            "related_intent_group": s["related_intent_group"],
            "answerability": s["answerability"],
            "review_status": specs["review_status"],
            "derivation": derivation,
            "retrieval_applicable": bool(groups),
            "reference_evidence_ids": sorted(refs),
            "evidence_group_metadata": [
                {"id": f"{cid}:g{i}", "criterion": criterion, "logic": "any_one_alternative"}
                for i, criterion in enumerate(
                    [labels[pid]["evidence_groups"][j]["criterion"] for j in indexes]
                    + extra_criteria
                )
            ],
        }
        Question(**r)
        records.append(r)
        rubric = {
            "id": cid,
            "parent_id": pid,
            "answerability": s["answerability"],
            "mandatory_facts": [
                {
                    "id": f"{cid}:f{i}",
                    "expected": text,
                    "score": {"0": "遗漏或实质错误", "0.5": "部分正确", "1": "充分且口径正确"},
                }
                for i, text in enumerate(s["facts"], 1)
            ],
            "required_evidence_group_ids": [f"{cid}:g{i}" for i in range(len(groups))],
            "evidence_criteria": [labels[pid]["evidence_groups"][i]["criterion"] for i in indexes]
            + extra_criteria,
            "numeric_check_ids": s["numeric_check_ids"],
            "expected_limits": limits,
            "material_errors": errors,
            "limitations": limits,
            "annotation_review": specs["review_status"],
            "reference_source_ids": sorted(refs),
            "retrieval_applicable": bool(groups),
        }
        rs.append(rubric)
        planner.append(
            {
                "id": cid,
                "expected_companies": sorted(s["expected_scope"]),
                "report_years": s["expected_scope"],
                "as_of": query["as_of"],
                "confirmed_context": query["confirmed_context"],
                "intent": s["title"],
                "task_type": s["task_type"],
                "required_output_criteria": s["facts"],
                "assessment": "semantic intent/scope preservation, not exact rewritten wording",
                "review_status": specs["review_status"],
            }
        )
        ragas.append(
            {
                "id": cid,
                "user_input": s["question"],
                "reference": answer,
                "reference_contexts": [catalog[a]["quote"] for a in sorted(refs)],
                "reference_context_ids": sorted(refs),
            }
        )
        lin = {
            **derivation,
            "id": cid,
            "parent_limit_indexes": s["parent_limit_indexes"],
            "parent_error_indexes": s["parent_error_indexes"],
            "numeric_check_ids": s["numeric_check_ids"],
            "depends_on": s["depends_on"],
            "reference_source_ids": sorted(refs),
        }
        lin["additional_source_groups"] = s.get("additional_source_groups", [])
        require(
            set(s["depends_on"]) <= child_ids and cid not in s["depends_on"],
            f"{cid}: bad child dependency",
        )
        lineage.append(lin)
        by_parent[pid].append(cid)
        for k, values in [
            ("facts", s["parent_fact_ids"]),
            ("groups", indexes),
            ("checks", s["numeric_check_ids"]),
            ("limits", s["parent_limit_indexes"]),
            ("errors", s["parent_error_indexes"]),
        ]:
            seen[pid][k].update(values)
        mapping.append(
            f"| {pid} | [{cid}](reference_answers.md#{cid.lower().replace('.', '')}) | {s['title']} | {s['task_type']} | {len(s['numeric_check_ids'])} |"
        )
        readable_answer = REF.sub(
            lambda match: f"[{match[1]}]({catalog[match[1]]['source_url']})", answer
        )
        review.extend(
            [
                f"## {cid}",
                "",
                f"**{s['title']}** · 原题{pid} · {s['task_type']}",
                "",
                s["question"],
                "",
                readable_answer,
                "",
                "**该子题评分要点：** " + "；".join(s["facts"]),
                "",
                "**边界：** "
                + (
                    "；".join(limits)
                    if limits
                    else "限所给证据、事实期间和口径，不扩展至其他子题。"
                ),
                "",
            ]
        )
    audit = []
    for pid in gold:
        require(by_parent[pid], f"{pid}: no children")
        scoped = specs.get("scoped_out", {}).get(pid, {})
        expected = {
            "facts": {f["id"] for f in rubrics[pid]["mandatory_facts"]},
            "groups": set(range(len(gold[pid]["evidence_groups"]))),
            "checks": set(rubrics[pid]["numeric_check_ids"]),
            "limits": set(range(len(rubrics[pid]["expected_limits"]))),
            "errors": set(range(len(rubrics[pid]["material_errors"]))),
        }
        omitted = {k: sorted(v - seen[pid][k], key=str) for k, v in expected.items()}
        declared = {
            "checks": set(scoped.get("numeric_check_ids", {})),
            "groups": set(scoped.get("group_indexes", {})),
            "facts": set(),
            "limits": set(),
            "errors": set(),
        }
        for k, values in omitted.items():
            require(
                set(values) == declared[k],
                f"{pid}: unaccounted {k}: {values}, declared={declared[k]}",
            )
        audit.append(
            {
                "parent_id": pid,
                "children": by_parent[pid],
                "covered": {k: len(v) for k, v in seen[pid].items()},
                "scoped_out": scoped,
                "omitted": omitted,
            }
        )
    numerical = [
        {**checks[n], "case_ids": cases, "parent_case_ids": checks[n]["case_ids"]}
        for n, cases in sorted(check_cases.items())
    ]
    require(set(check_cases) == set(checks), "some unique numeric checks disappeared entirely")
    # Check that evaluation-only dependencies form a DAG; they are not runtime plans.
    deps = {r["id"]: r["depends_on"] for r in lineage}

    def visit(cid, path):
        require(cid not in path, "cyclic child dependencies")
        for target in deps[cid]:
            visit(target, path | {cid})

    for cid in deps:
        visit(cid, set())
    files = {
        "golden.jsonl": encoded(records, jsonl=True),
        "retrieval_case_ids.json": encoded([r["id"] for r in records if r["retrieval_applicable"]]),
        "retrieval_queries.jsonl": encoded(qrows, jsonl=True),
        "rubrics.jsonl": encoded(rs, jsonl=True),
        "numeric_checks.jsonl": encoded(numerical, jsonl=True),
        "lineage.jsonl": encoded(lineage, jsonl=True),
        "planner_expectations.jsonl": encoded(planner, jsonl=True),
        "evaluation_dataset.jsonl": encoded(ragas, jsonl=True),
        "evidence_catalog.jsonl": encoded([catalog[a] for a in sorted(used_sources)], jsonl=True),
        "parent_coverage.json": encoded(audit),
        "reference_answers.md": ("\n".join(review) + "\n").encode(),
        "parent_child_map.md": ("\n".join(mapping) + "\n").encode(),
    }
    manifest = {
        "version": specs["version"],
        "status": "curated_draft_pending_review",
        "date": specs["created_at"],
        "parents": len(by_parent),
        "children": len(records),
        "retrieval_cases": sum(r["retrieval_applicable"] for r in records),
        "boundary_only_cases": sum(not r["retrieval_applicable"] for r in records),
        "required_evidence_group_occurrences": sum(len(r["evidence_groups"]) for r in records),
        "numeric_check_ids": len(numerical),
        "numeric_check_occurrences": sum(len(r["numeric_check_ids"]) for r in rs),
        "mandatory_fact_occurrences": sum(len(r["mandatory_facts"]) for r in rs),
        "all_dev": True,
        "independent_holdout": False,
        "split_unit": "parent family including related parent questions",
        "source_inputs_sha256": hashes,
        "split_specs_sha256": digest((out / "split_specs.json").read_bytes()),
        "builder_sha256": digest(Path(__file__).read_bytes()),
        "outputs_sha256": {n: digest(b) for n, b in files.items()},
    }
    files["manifest.json"] = encoded(manifest)
    return files, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    files, manifest = build()
    for name, content in files.items():
        path = OUT / name
        if args.check:
            require(path.exists() and path.read_bytes() == content, f"changed artifact: {name}")
        else:
            path.write_bytes(content)
    print(
        json.dumps(
            {
                k: manifest[k]
                for k in [
                    "status",
                    "parents",
                    "children",
                    "retrieval_cases",
                    "boundary_only_cases",
                    "numeric_check_ids",
                    "numeric_check_occurrences",
                ]
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
