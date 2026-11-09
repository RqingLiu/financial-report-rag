"""Whole-answer rubric export and validation; no provider client."""

import json
import re
from statistics import mean

from finrag.core.files import digest

DIMENSIONS = ("completeness", "truthfulness", "faithfulness", "relevance", "clarity")
PROMPT_VERSION = "whole-answer-judge-v1"


def _check(condition, reason):
    if not condition:
        raise ValueError(reason)


def _nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def rubric_hash(rubric):
    ids = tuple(d["id"] for d in rubric["dimensions"])
    _check(ids == DIMENSIONS, "wrong whole-answer rubric dimensions")
    _check(_nonempty(rubric["version"]), "rubric version required")
    for dimension in rubric["dimensions"]:
        anchors = dimension["anchors"]
        _check(
            set(anchors) == set("12345") and all(map(_nonempty, anchors.values())),
            "rubric needs five labeled anchors per dimension",
        )
        _check(
            _nonempty(dimension["label"]) and _nonempty(dimension["question"]),
            "dimension label and question required",
        )
    _check(rubric["rules"] and all(map(_nonempty, rubric["rules"])), "rubric rules required")
    return digest(json.dumps(rubric, sort_keys=True, ensure_ascii=False, separators=(",", ":")))


def judge_inputs(packets, rubric):
    """Return portable message envelopes for a judge run outside this program."""
    rhash = rubric_hash(rubric)
    out = []
    system = (
        "You are reviewing financial-report answers. Apply the supplied versioned rubric. "
        "Read the whole answer before rating it. Return one JSON object in the requested form, "
        "with brief audit reasons, not hidden reasoning. Fill all five dimensions separately. "
        "Use the candidate answer's language for reasons. Copy the IDs and hashes exactly. "
        "Answer excerpts and cited source excerpts must be literal substrings. "
        "Use an empty source_excerpts list if no source excerpt applies. "
        "Use null only when you cannot assess that dimension; explain why."
    )
    for p in packets:
        if p["status"] != "generated":
            continue
        data = {
            "rubric": rubric,
            "original_request": p["query"],
            "candidate_answer": p["answer"],
            "runtime_evidence": [
                {k: e[k] for k in ("citation", "document_id", "filed_at", "text")}
                for e in p["evidence"]
            ],
            "reference_only_for_review": {
                "answer": p["reference"],
                "criteria": p["rubric"],
                "numeric_checks": p["checks"],
            },
            "output_form": {
                "id": p["id"],
                "packet_hash": p["packet_hash"],
                "rubric_hash": rhash,
                "prompt_version": PROMPT_VERSION,
                "judge_method": "your model/run label",
                "dimensions": [
                    {
                        "id": key,
                        "score": "integer 1–5 or null",
                        "reason": "brief rationale",
                        "answer_quotes": ["exact answer excerpt"],
                        "source_excerpts": [{"citation": "E1", "quote": "exact source excerpt"}],
                    }
                    for key in DIMENSIONS
                ],
            },
        }
        out.append(
            {
                "id": p["id"],
                "messages": [
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps(data, ensure_ascii=False)},
                ],
            }
        )
    return out


def _material_truth_error(packet, diagnostics):
    attached = set(re.findall(r"\[(E\d+)\]", packet["answer"]))
    excluded = set(diagnostics["evidence_after_cutoff"])
    excluded.update(diagnostics["evidence_outside_confirmed_document"])
    return (
        bool(attached & excluded)
        or any(x["status"] == "material_error" for x in diagnostics["numbers"])
        or any(x["status"] == "present" for x in diagnostics["material_errors"])
        or any(x["material"] for x in diagnostics["observations"])
    )


def score_quality(packets, diagnostics, verdicts, rubric):
    rhash = rubric_hash(rubric)
    generated = {p["id"]: p for p in packets if p["status"] == "generated"}
    by_id = {v["id"]: v for v in verdicts}
    _check(
        len(by_id) == len(verdicts) and set(by_id) == set(generated),
        "whole-answer verdicts must match generated answers exactly",
    )
    scored = {key: [] for key in DIMENSIONS}
    output = {}
    for d in diagnostics:
        qid = d["id"]
        if qid not in generated:
            continue
        p, v = generated[qid], by_id[qid]
        _check(
            v["packet_hash"] == p["packet_hash"]
            and v["rubric_hash"] == rhash
            and v["prompt_version"] == PROMPT_VERSION,
            f"{qid}: stale whole-answer verdict",
        )
        _check(_nonempty(v["judge_method"]), f"{qid}: judge provenance required")
        rows = {r["id"]: r for r in v["dimensions"]}
        _check(
            len(v["dimensions"]) == len(DIMENSIONS) and set(rows) == set(DIMENSIONS),
            f"{qid}: missing or duplicate dimension",
        )
        evidence = {e["citation"]: e["text"] for e in p["evidence"]}
        for key in DIMENSIONS:
            row = rows[key]
            value = row["score"]
            _check(
                value is None or (type(value) is int and 1 <= value <= 5),
                f"{qid}/{key}: score must be an integer 1–5 or null",
            )
            _check(_nonempty(row["reason"]), f"{qid}/{key}: reason required")
            quotes = row["answer_quotes"]
            _check(
                isinstance(quotes, list)
                and (quotes or value is None)
                and all(_nonempty(q) and q in p["answer"] for q in quotes),
                f"{qid}/{key}: invalid answer excerpt",
            )
            sources = row["source_excerpts"]
            _check(isinstance(sources, list), f"{qid}/{key}: invalid source excerpts")
            for src in sources:
                _check(
                    _nonempty(src["quote"]) and src["quote"] in evidence.get(src["citation"], ""),
                    f"{qid}/{key}: invalid source excerpt",
                )
            if value is not None:
                if key == "truthfulness" and _material_truth_error(p, d):
                    _check(value <= 2, f"{qid}: material error caps truthfulness at 2")
                scored[key].append(value)
        output[qid] = v
    return {
        "rubric_version": rubric["version"],
        "rubric_hash": rhash,
        "rubric": rubric,
        "prompt_version": PROMPT_VERSION,
        "generated": len(generated),
        "attempts": len(packets),
        "metrics": {
            key: {"mean": round(mean(values), 2) if values else None, "n": len(values)}
            for key, values in scored.items()
        },
        "by_question": output,
    }


def quality_report(quality, packets):
    rows = [
        "## 整答评分 · 1–5 分",
        "",
        f"量表 `{quality['rubric_version']}`。五个维度独立评分；`—` 表示未生成或待判。",
        "Faithfulness 检查实际上下文能否支持内容；下文的逐项引用检查核对的是所标原文。",
        "这些是 Judge 的初评，严格通过规则与数值核对见下文。",
        "",
        "| 题号 | 完整性 | 真实性 | 证据一致性 | 相关性 | 清晰度 |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]
    verdicts = quality["by_question"]
    for p in packets:
        v = verdicts.get(p["id"], {})
        values = {r["id"]: r["score"] for r in v.get("dimensions", [])}
        rows.append(
            "| " + " | ".join([p["id"], *(str(values.get(k) or "—") for k in DIMENSIONS)]) + " |"
        )
    averages = [
        f"{m['mean']:.2f} (n={m['n']})" if m["mean"] is not None else "— (n=0)"
        for m in (quality["metrics"][k] for k in DIMENSIONS)
    ]
    rows.extend(["| 均分 | " + " | ".join(averages) + " |", "", "### Judge 判定理由", ""])
    labels = dict(zip(DIMENSIONS, ("完整性", "真实性", "证据一致性", "相关性", "清晰度")))
    for p in packets:
        v = verdicts.get(p["id"])
        if not v:
            continue
        rows.extend([f"#### {p['id']}", ""])
        rows.extend([f"Judge：`{v['judge_method']}`。", ""])
        dims = {r["id"]: r for r in v["dimensions"]}
        ev = {e["citation"]: e for e in p["evidence"]}
        for key in DIMENSIONS:
            r = dims[key]
            rows.append(f"- **{labels[key]} {r['score'] or '待判'}**：{r['reason']}")
            rows.extend(f"  - 回答：{q}" for q in r["answer_quotes"])
            for s in r["source_excerpts"]:
                e = ev[s["citation"]]
                quote = " ".join(s["quote"].split())
                rows.append(f"  - {s['citation']} [{e['document_id']}]({e['source_url']})：{quote}")
        rows.append("")
    rows.extend(["### 量表分档", ""])
    for dim in quality["rubric"]["dimensions"]:
        rows.extend([f"**{dim['label']} · {labels[dim['id']]}**", ""])
        rows.extend(f"- {k} 分：{dim['anchors'][str(k)]}" for k in range(5, 0, -1))
        rows.append("")
    return rows
