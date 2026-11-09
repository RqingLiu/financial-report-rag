"""Offline evaluation of saved answers with imported, evidence-anchored judge verdicts."""

import argparse
import json
import re
from collections import Counter
from datetime import date
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

from finrag.core.files import atomic_json, digest, read_jsonl
from finrag.evaluation.rubric import judge_inputs, quality_report, score_quality

VERSION = "answer-eval-v1"
CITATION = re.compile(r"\[(E\d+)\]")
NUMBER = r"\d+(?:,\d{3})*(?:\.\d+)?"
FACT_POINTS = {"correct": 1, "partial": 0.5, "missing": 0, "incorrect": 0, "uncertain": 0}
CITATION_STATES = {"supported", "partial", "unsupported", "uncited", "uncertain", "not_applicable"}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def index(rows):
    result = {r["id"]: r for r in rows}
    require(len(result) == len(rows), "duplicate item ID")
    return result


def fingerprint(packet):
    fields = {k: v for k, v in packet.items() if k != "packet_hash"}
    return digest(json.dumps(fields, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def prepare(traces, golden, ids):
    require(ids and len(ids) == len(set(ids)), "select unique question IDs")
    queries, rubrics, checks = (
        index(read_jsonl(golden / f"{name}.jsonl"))
        for name in ("retrieval_queries", "rubrics", "numeric_checks")
    )
    references = (golden / "reference_answers.md").read_text()
    packets = []
    for qid in ids:
        require(
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}", qid)
            and ".." not in qid
            and qid in queries,
            f"unknown or unsafe question: {qid}",
        )
        raw = (traces / f"{qid}.json").read_bytes()
        trace = json.loads(raw)
        query, rubric = queries[qid], rubrics[qid]
        require(trace["query_id"] == qid, f"{qid}: wrong trace ID")
        for field in ("question", "reading_context", "as_of", "confirmed_context", "corpus_scope"):
            key = "original_question" if field == "question" else field
            require(trace["inputs"].get(key) == query[field], f"{qid}: changed {field}")
        ref = re.search(
            rf"^## {re.escape(qid)}\s*\n(.*?)(?=^## |\Z)", references, re.MULTILINE | re.DOTALL
        )
        require(ref is not None, f"{qid}: missing reference answer")
        numeric = [checks[i] for i in rubric["numeric_check_ids"]]
        require(all(qid in n["case_ids"] for n in numeric), f"{qid}: check scope mismatch")
        packet = {
            "id": qid,
            "version": VERSION,
            "query": query,
            "rubric": rubric,
            "reference": ref[1].strip(),
            "checks": numeric,
            "trace_hash": digest(raw),
            "status": trace["status"],
            "run": traces.parent.name,
            "answer": (trace.get("generation") or {}).get("answer", ""),
            "evidence": trace.get("runtime_evidence") or [],
        }
        packet["packet_hash"] = fingerprint(packet)
        packets.append(packet)
    return packets


def exact_rows(rows, expected, label):
    mapped = index(rows)
    require(set(mapped) == set(expected), f"{label}: missing or unexpected item IDs")
    return [mapped[key] for key in expected]


def text(value):
    return isinstance(value, str) and bool(value.strip())


def check_quote(quote, original):
    require(text(quote) and quote in original, "unverifiable excerpt")


def numeric_result(row, check, answer):
    mapping = row["mapping"]
    require(mapping in {"aligned", "wrong_scope", "missing", "uncertain"}, "bad numeric mapping")
    if mapping == "missing":
        require(
            not row.get("quote") and not row.get("literal"), "missing number has an observation"
        )
        return {"status": "missing"}
    if mapping in {"wrong_scope", "uncertain"}:
        if row.get("quote") or mapping == "wrong_scope":
            check_quote(row.get("quote"), answer)
        return {"status": "material_error" if mapping == "wrong_scope" else "review"}
    quote, literal = row["quote"], row["literal"]
    check_quote(quote, answer)
    require(
        isinstance(literal, str) and re.fullmatch(rf"(?:[+\-−]?{NUMBER}|\({NUMBER}\))", literal),
        "number must be a literal from the answer",
    )
    require(
        re.search(rf"(?<![\d.,+\-−(]){re.escape(literal)}(?!\d|[.,]\d)", quote),
        "number is not an exact literal in excerpt",
    )
    require(row.get("unit") == check["unit"], "aligned numeric unit mismatch")
    normalized = literal.replace(",", "").replace("−", "-")
    observed = Decimal("-" + normalized[1:-1] if normalized.startswith("(") else normalized)
    direction = row.get("direction", 1)
    require(type(direction) is int and direction in (-1, 1), "invalid numeric direction")
    if direction == -1:
        # A decrease amount can be written as words instead of a signed literal.
        # "decreased to" / "下降至" describe a level and must never qualify here.
        marker = r"(?:减少|下降|降低)(?:了|约|约为)?\s*|(?:decreased?|declined?)(?:\s+by)?\s+"
        require(
            observed >= 0
            and re.search(rf"(?:{marker}){re.escape(literal)}(?!\d|[.,]\d)", quote, re.IGNORECASE),
            "negative direction needs an adjacent decrease amount",
        )
        observed = -observed
    expected = Decimal(check["expected"])
    exact = Decimal(check["exact_decimal"])
    delta = abs(observed - expected)
    normal = Decimal(check["tolerance"]["normal_abs"])
    minor = Decimal(check["tolerance"]["minor_precision_abs"])
    rounded = row.get("accept_rounding", False)
    require(isinstance(rounded, bool), "accept_rounding must be boolean")
    places = max(0, -observed.as_tuple().exponent)
    round_match = (
        rounded
        and places < check["decimal_places"]
        and observed == exact.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)
    )
    status = (
        "correct"
        if delta <= normal
        else "correct_rounded"
        if round_match
        else "minor_precision"
        if delta <= minor
        else "material_error"
    )
    return {"status": status, "observed": str(observed), "absolute_error": str(delta)}


def score_packet(packet, verdict):
    require(
        packet["version"] == VERSION and fingerprint(packet) == packet["packet_hash"],
        "packet is stale or invalid",
    )
    require(
        verdict["id"] == packet["id"] and verdict["packet_hash"] == packet["packet_hash"],
        "verdict does not match packet",
    )
    require(text(verdict.get("judge_method")), "judge provenance required")
    qid, answer, rubric = packet["id"], packet["answer"], packet["rubric"]
    require((packet["status"] == "generated") == bool(answer.strip()), "inconsistent answer status")
    evidence = index([{**e, "id": e["citation"]} for e in packet["evidence"]])
    cutoff = date.fromisoformat(packet["query"]["as_of"])
    attached = set(CITATION.findall(answer))
    unknown = sorted(attached - set(evidence))
    late = sorted(k for k, e in evidence.items() if date.fromisoformat(e["filed_at"]) > cutoff)
    confirmed = packet["query"].get("confirmed_context") or {}
    required_document = confirmed.get("report_document_id")
    outside_document = sorted(
        k
        for k, e in evidence.items()
        if required_document and e["document_id"] != required_document
    )
    fact_map = index(rubric["mandatory_facts"])
    checks = index(packet["checks"])
    limit_map = {f"L{i}": s for i, s in enumerate(rubric["expected_limits"], 1)}
    error_map = {f"M{i}": s for i, s in enumerate(rubric["material_errors"], 1)}
    result = {
        "id": qid,
        "run": packet["run"],
        "status": packet["status"],
        "trace_hash": packet["trace_hash"],
        "packet_hash": packet["packet_hash"],
        "judge_method": verdict["judge_method"],
        "verdict_hash": digest(json.dumps(verdict, sort_keys=True, ensure_ascii=False)),
        "invalid_citation_ids": unknown,
        "evidence_after_cutoff": late,
        "evidence_outside_confirmed_document": outside_document,
        "fact_count": len(fact_map),
        "numeric_count": len(checks),
        "facts": [],
        "numbers": [],
        "limits": [],
        "material_errors": [],
        "observations": [],
    }
    if not answer:
        require(
            not any(verdict.get(k) for k in ("facts", "numbers", "limits", "material_errors")),
            "non-generated attempt cannot have answer verdicts",
        )
        return {
            **result,
            "outcome": "fail",
            "fact_points": 0,
            "note": "No answer; required items remain in the denominator.",
        }
    for row in exact_rows(verdict["facts"], fact_map, f"{qid} facts"):
        status, support = row["status"], row["citation_status"]
        require(status in FACT_POINTS and support in CITATION_STATES, "invalid fact/citation state")
        require(text(row["reason"]) and text(row["citation_reason"]), "fact reasons required")
        quotes, anchors = row["quotes"], row["sources"]
        require(isinstance(quotes, list) and isinstance(anchors, list), "invalid anchor lists")
        if status == "missing":
            require(
                not quotes and support == "not_applicable", "missing fact cannot have citations"
            )
        else:
            require(bool(quotes) or status == "uncertain", "answered fact needs an excerpt")
        for quote in quotes:
            check_quote(quote, answer)
        quote_ids = set(CITATION.findall(" ".join(quotes)))
        if support in {"supported", "partial", "unsupported"}:
            require(bool(anchors), "citation verdict needs source excerpts")
        if support in {"uncited", "not_applicable"}:
            require(not anchors, "uncited or inapplicable fact has source anchors")
        if support == "uncited":
            require(not quote_ids, "uncited excerpt has attached citations")
        for anchor in anchors:
            cid = anchor["citation"]
            require(
                cid in quote_ids and cid in evidence, "source is not attached to answer excerpt"
            )
            check_quote(anchor["quote"], evidence[cid]["text"])
            if support in {"supported", "partial"}:
                require(
                    cid not in late and cid not in outside_document,
                    "out-of-scope evidence cannot support a claim",
                )
        result["facts"].append({**row, "expected": fact_map[row["id"]]["expected"]})
    for row in exact_rows(verdict["numbers"], checks, f"{qid} numeric checks"):
        check = checks[row["id"]]
        require(text(row["reason"]), "numeric reason required")
        result["numbers"].append(
            {
                **row,
                **numeric_result(row, check, answer),
                "metric": check["metric"],
                "expected": check["expected"],
                "expected_unit": check["unit"],
            }
        )
    for field, rules, valid in (
        ("limits", limit_map, {"met", "partial", "missed", "uncertain"}),
        ("material_errors", error_map, {"absent", "present", "uncertain"}),
    ):
        for row in exact_rows(verdict[field], rules, f"{qid} {field}"):
            require(row["status"] in valid and text(row["reason"]), f"bad {field} verdict")
            if row.get("quote") or row["status"] in {"met", "partial", "present"}:
                check_quote(row.get("quote"), answer)
            result[field].append({**row, "expected": rules[row["id"]]})
    for row in verdict.get("observations", []):
        require(text(row["reason"]) and isinstance(row["material"], bool), "invalid observation")
        check_quote(row["quote"], answer)
        result["observations"].append(row)
    result["fact_points"] = sum(FACT_POINTS[r["status"]] for r in result["facts"])
    failed = (
        bool(unknown or late or outside_document)
        or any(
            r["status"] not in {"correct", "uncertain"}
            or r["citation_status"] in {"partial", "unsupported", "uncited"}
            for r in result["facts"]
        )
        or any(r["status"] in {"material_error", "missing"} for r in result["numbers"])
        or any(r["status"] in {"partial", "missed"} for r in result["limits"])
        or any(r["status"] == "present" for r in result["material_errors"])
        or any(r["material"] for r in result["observations"])
    )
    review = any(
        r["status"] in {"review", "uncertain"} or r.get("citation_status") == "uncertain"
        for key in ("facts", "numbers", "limits", "material_errors")
        for r in result[key]
    )
    result["outcome"] = "fail" if failed else "review" if review else "pass"
    return result


def evaluate(packets, verdicts):
    keys = list(index(packets))
    require(bool(keys), "empty packet set")
    rows = [score_packet(p, v) for p, v in zip(packets, exact_rows(verdicts, keys, "verdicts"))]
    facts = Counter(f["status"] for r in rows for f in r["facts"])
    numbers = Counter(n["status"] for r in rows for n in r["numbers"])
    citations = Counter(f["citation_status"] for r in rows for f in r["facts"])
    for row in rows:
        if row["status"] != "generated":
            facts["not_generated"] += row["fact_count"]
            numbers["not_generated"] += row["numeric_count"]
    return {
        "version": VERSION,
        "scorer_sha256": digest(Path(__file__).read_bytes()),
        "split": "development",
        "human_review": "pending",
        "attempts": len(rows),
        "generated": sum(r["status"] == "generated" for r in rows),
        "outcomes": dict(Counter(r["outcome"] for r in rows)),
        "fact_points": sum(r["fact_points"] for r in rows),
        "fact_count": sum(r["fact_count"] for r in rows),
        "fact_statuses": dict(facts),
        "numeric_count": sum(r["numeric_count"] for r in rows),
        "numeric_statuses": dict(numbers),
        "citation_statuses": dict(citations),
        "questions": rows,
    }


def report(scores, packets):
    by_id = index(packets)
    citation = scores["citation_statuses"]
    applicable = sum(n for k, n in citation.items() if k != "not_applicable")
    out = [
        "# 端到端答案试评 · 待人工复核",
        "",
        "离线评分器导入 Judge 判定，校验原文锚点、检查日期并计算数值差。",
        "样本来自保存的开发集运行。此评分命令不调用 API、不重跑检索或生成。",
        "引用只检查 rubric 覆盖的事实，非全文逐句审计；聚合分数不能作为当前线上成绩。",
        "复核时可按条目标识（如 `U12:f3`、`N093`）反馈同意、改判或需补证。",
        "",
    ]
    if "whole_answer" in scores:
        out.extend(quality_report(scores["whole_answer"], packets))
        out.extend(["## 逐项诊断", ""])
    out += [
        (
            f"- 生成回答：{scores['generated']}/{scores['attempts']}；整题通过："
            f"{scores['outcomes'].get('pass', 0)}/{scores['attempts']}。"
        ),
        (
            f"- 必答事实：{scores['fact_points']:g}/{scores['fact_count']} 分"
            "（正确 1，部分 0.5，其余 0；待判另计）。"
        ),
        f"- 数值检查：{scores['numeric_count']} 项；{scores['numeric_statuses']}。",
        f"- 引用完整支持：{citation.get('supported', 0)}/{applicable} 个适用事实；{citation}。",
        "",
        "| 题号 | 必答事实分 | 数值通过 / 应查 | 整题结果 |",
        "|---|---:|---:|---|",
    ]
    for r in scores["questions"]:
        correct = sum(
            n["status"] in {"correct", "correct_rounded", "minor_precision"} for n in r["numbers"]
        )
        numeric_display = f"{correct}/{r['numeric_count']}" if r["numeric_count"] else "—"
        out.append(
            f"| {r['id']} | {r['fact_points']:g}/{r['fact_count']} | "
            f"{numeric_display} | {r['outcome']} |"
        )
    for r in scores["questions"]:
        p = by_id[r["id"]]
        ev = {e["citation"]: e for e in p["evidence"]}
        out += [
            "",
            f"## {r['id']} · {r['outcome']}",
            "",
            p["query"]["question"],
            "",
            (
                f"截止日：{p['query']['as_of']}。非法引用：{r['invalid_citation_ids']}；"
                f"超期证据：{r['evidence_after_cutoff']}；"
                f"不符指定文档：{r['evidence_outside_confirmed_document']}。"
            ),
            "",
            "### 必答事实与引用",
            "",
        ]
        for f in r["facts"]:
            out += [
                f"- **{f['id']} · {f['status']} / {f['citation_status']}**：{f['expected']}",
                f"  - 判定：{f['reason']} 引用：{f['citation_reason']}",
            ]
            out.extend(f"  - 回答：{s}" for s in f["quotes"])
            for s in f["sources"]:
                e = ev[s["citation"]]
                out.append(
                    f"  - {s['citation']} [{e['document_id']}]({e['source_url']})："
                    + " ".join(s["quote"].split())
                )
        out += ["", "### 数值", ""]
        if not r["numbers"]:
            out.append("无适用的冻结数值检查。事实 rubric 中的数字仍按事实项检查。")
        for n in r["numbers"]:
            out.append(
                f"- **{n['id']} · {n['status']}**：{n['metric']}；"
                f"预期 {n['expected']} {n['expected_unit']}；"
                f"观察 {n.get('observed', '—')}。{n['reason']}"
            )
            if n.get("quote"):
                out.append(f"  - 回答：{n['quote']}")
        for key, title in [("limits", "边界"), ("material_errors", "错误推断")]:
            out += ["", f"### {title}", ""]
            for item in r[key]:
                out.append(
                    f"- **{item['id']} · {item['status']}** {item['expected']}：{item['reason']}"
                )
                if item.get("quote"):
                    out.append(f"  - 回答：{item['quote']}")
        for item in r["observations"]:
            out.append(
                f"- **额外观察（实质错误：{item['material']}）**：{item['reason']}"
                f" 回答：{item['quote']}"
            )
    return "\n".join(out) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    p = commands.add_parser("prepare")
    p.add_argument("--traces", type=Path, required=True)
    p.add_argument("--golden", type=Path, required=True)
    p.add_argument("--ids", nargs="+", required=True)
    p.add_argument("--out", type=Path, required=True)
    j = commands.add_parser("export-judge")
    j.add_argument("--packets", type=Path, required=True)
    j.add_argument("--rubric", type=Path, required=True)
    j.add_argument("--out", type=Path, required=True)
    s = commands.add_parser("score")
    s.add_argument("--packets", type=Path, required=True)
    s.add_argument("--verdicts", type=Path, required=True)
    s.add_argument("--rubric", type=Path)
    s.add_argument("--whole-verdicts", type=Path)
    s.add_argument("--out", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        atomic_json(args.out, prepare(args.traces, args.golden, args.ids))
        return
    packets = json.loads(args.packets.read_text())
    if args.command == "export-judge":
        require(bool(index(packets)), "empty packet set")
        require(
            all(p["version"] == VERSION and fingerprint(p) == p["packet_hash"] for p in packets),
            "packet is stale or invalid",
        )
        rubric = json.loads(args.rubric.read_text())
        atomic_json(args.out, judge_inputs(packets, rubric))
        return
    require(
        bool(args.rubric) == bool(args.whole_verdicts),
        "pass --rubric and --whole-verdicts together",
    )
    verdicts = json.loads(args.verdicts.read_text())
    scores = evaluate(packets, verdicts)
    if args.whole_verdicts:
        rubric = json.loads(args.rubric.read_text())
        whole = json.loads(args.whole_verdicts.read_text())
        scores["whole_answer"] = score_quality(packets, scores["questions"], whole, rubric)
    review = report(scores, packets)
    atomic_json(args.out / "scores.json", scores)
    atomic_json(args.out / "review.md", review, raw=True)


if __name__ == "__main__":
    main()
