"""Build auditable, human-review-only answer drafts from offline authored annotations.

This is annotation tooling, not the runtime retriever or a financial-facts service.
No API, database, embedding, RAGAS judge, or approval is invoked here.
"""

import hashlib
import json
import re
from pathlib import Path

from lxml import html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/evaluation/review_v2"
SPEC = ROOT / "data/evaluation/reference_draft_specs_v2.json"
REF = re.compile(r"\[((?:NVDA|AMD|MU)\d{2}A?\.\d+)\]")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    specs = json.loads(SPEC.read_text())
    seeds = [json.loads(s) for s in (ROOT / "data/evaluation/user_seeds_v2.jsonl").read_text().splitlines()]
    filings = {f["id"]: f for f in map(json.loads, (ROOT / "data/sources.jsonl").read_text().splitlines())}
    assert [s["id"] for s in specs] == [s["id"] for s in seeds]
    blocks, doms, canonical, checked = {}, {}, {}, {}
    evidence = {}

    def resolve(alias):
        if alias in evidence:
            return evidence[alias]
        prefix, ordinal = alias.split(".")
        m = re.fullmatch(r"(NVDA|AMD|MU)(\d{2})(A?)", prefix)
        doc = f"{m[1]}_FY20{m[2]}"
        if m[3]:
            doc = next(k for k in filings if k.startswith(doc + "_A_"))
        f = filings[doc]
        if doc not in blocks:
            raw = (ROOT / f"data/raw/{doc}.html").read_bytes()
            assert sha(raw) == f["sha256"], f"Raw source changed: {doc}"
            bs = [json.loads(s) for s in (ROOT / f"data/processed/{doc}.blocks.jsonl").read_text().splitlines()]
            blocks[doc] = bs
            canonical[doc] = "\n\n".join(b["text"] for b in bs)
            assert canonical[doc] == (ROOT / f"data/processed/{doc}.txt").read_text()
            tree = html.fromstring(raw)
            for node in list(tree.iter()):
                style = re.sub(r"\s+", "", node.get("style", "").lower())
                if str(node.tag).lower() in ("script", "style", "noscript", "ix:header", "ix:hidden") or "display:none" in style or "visibility:hidden" in style:
                    node.drop_tree()
            doms[doc] = tree
            checked[doc] = f["sha256"]
        b = blocks[doc][int(ordinal)]
        assert b["ordinal"] == int(ordinal)
        assert canonical[doc][b["start"]:b["end"]] == b["text"]
        xpath = re.sub(r"/([\w.-]+:[\w.-]+)", r"/*[name()='\1']", b["locator"]["xpath"])
        nodes = doms[doc].xpath(xpath)
        assert len(nodes) == 1, f"Missing DOM locator: {alias}"
        normalize = lambda s: " ".join(s.replace("\xa0", " ").split())
        dom_text = normalize(" ".join(nodes[0].itertext()))
        cursor = 0
        for part in b["text"].replace("\n", "|").split("|"):
            part = normalize(part)
            if not part:
                continue
            pos = dom_text.find(part, cursor)
            assert pos >= 0, f"Source text absent from raw DOM: {alias}: {part[:60]}"
            cursor = pos + len(part)
        item = {"id": alias, "document_id": doc, "accession": f["accession"], "report_fiscal_year": f["fiscal_year"], "period_end": f["period_end"], "filed_at": f["filed_at"], "source_url": f["source_url"], "block_id": b["id"], "kind": b["kind"], "section_from_parser": b["section"], "locator": b["locator"], "start": b["start"], "end": b["end"], "quote": b["text"], "canonical_span_verified": True, "raw_dom_verified": True}
        if b["locator"].get("anchor"):
            item["source_url"] += "#" + b["locator"]["anchor"]
        evidence[alias] = item
        return item

    cases = []
    for seed, spec in zip(seeds, specs):
        aliases = list(dict.fromkeys(REF.findall(spec["answer_markdown"])))
        refs = [resolve(alias) for alias in aliases]
        as_of = seed.get("confirmed_context", {}).get("as_of", "2026-10-11")
        assert all(e["filed_at"] <= as_of for e in refs), f"Future source leak: {seed['id']}"
        if seed["id"] == "U14":
            assert {e["document_id"] for e in refs} == {"NVDA_FY2024"}
        assert refs, f"No references: {seed['id']}"
        cases.append({"id": seed["id"], "question": seed["question"], "reading_context": seed["reading_context"], "confirmed_context": seed.get("confirmed_context"), "as_of": as_of, "dataset_role": "development_reference_draft", "review_status": "gpt_source_checked_pending_human", "ready_for_scoring": False, "answer_markdown": spec["answer_markdown"], "limitations": spec["limitations"], "review_focus": spec["review_focus"], "evidence_ids": aliases, "reference_documents": sorted({e["document_id"] for e in refs})})

    OUT.mkdir(parents=True, exist_ok=True)
    def jsonl(path, records):
        path.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records))
    jsonl(OUT / "reference_drafts.jsonl", cases)
    jsonl(OUT / "evidence_catalog.jsonl", evidence.values())
    decisions = OUT / "human_review.jsonl"
    if not decisions.exists():
        jsonl(decisions, [{"id": c["id"], "decision": None, "notes": ""} for c in cases])
    lines = ["# 20题参考答案复核草稿", "", "状态：GPT离线拟答；原文存在性已机械核验，答案语义/完整性仍待人工复核。不是冻结Golden或独立测试集。", "", "普通题按库内资料截止日2026-10-11；MU/NVDA FY2024–2026，AMD FY2023–2025。U14仅NVDA FY2024、as_of=2024-02-21。金额默认百万美元；百分比按表内原数计算并四舍五入，原文披露整数比例可能不同。", "", "引用标识如MU26.986表示MU FY2026解析序号986；完整Block ID、DOM、字符区间、申报日及原文链接在文后。核验的是原始DOM中的有序文字及规范文本区间，不证明会计解读、未披露判断或证据完整性已经人工确认。", "", "请逐题记录：通过/需修改/暂不能定标，并指出数值、口径、推理、缺项或引用问题；先从U02/U03/U06/U09/U12/U14开始。后续才把复核通过的必答事实和替代证据组转成正式评分标签。", "", "## 目录", ""]
    lines += ["人工意见请保存在Notion复核页或同目录human_review.jsonl；本文件为生成视图，重新构建会覆盖。构建命令不会覆盖已有human_review.jsonl，也不会自动把草稿升级为gold。", ""]
    lines += [f"- [{c['id']}](#{c['id'].lower()})：{c['question'][:42]}…" for c in cases]
    for c in cases:
        answer = REF.sub(lambda m: f"[{m[1]}](#e-{m[1].lower().replace('.', '-')})", c["answer_markdown"])
        lines += ["", f"## {c['id']}", "", "**原始问题：** " + c["question"], "", "**阅读背景：** " + c["reading_context"], "", f"**资料截止日：** {c['as_of']}", "", answer, "", "**缺项与限制：** " + "；".join(c["limitations"]), "", "**请重点复核：** " + "；".join(c["review_focus"]), "", "**人工结论／修改意见：** 待填写。"]
    lines += ["", "## 原文证据目录", ""]
    for alias, e in evidence.items():
        anchor = alias.lower().replace(".", "-")
        lines += [f'<a id="e-{anchor}"></a>', "", f"### {alias}", "", f"[{e['document_id']} SEC原文]({e['source_url']}) · filed_at={e['filed_at']} · block_id=`{e['block_id']}` · start/end=`{e['start']}/{e['end']}`", "", f"DOM：`{e['locator']['xpath']}`；解析章节标签：`{e['section_from_parser']}`（原文定位优先）。", "", "```text", e["quote"], "```", ""]
    (OUT / "review.md").write_text("\n".join(lines))
    manifest = {"version": "user-seed-reference-drafts-v2", "status": "pending_human_review", "created_date": "2026-10-25", "generation": "offline current GPT conversation; authored answer specs plus deterministic arithmetic; not runtime retrieval results", "generation_api_called": False, "database_called": False, "cases": len(cases), "evidence_blocks": len(evidence), "sources_checked": checked, "seed_sha256": sha((ROOT / "data/evaluation/user_seeds_v2.jsonl").read_bytes()), "draft_spec_sha256": sha(SPEC.read_bytes()), "outputs_sha256": {p.name: sha(p.read_bytes()) for p in [OUT / "reference_drafts.jsonl", OUT / "evidence_catalog.jsonl", OUT / "review.md"]}, "scope_limitations": ["Development material, not an independent holdout", "Evidence list is not yet a complete gold qrels or mandatory/alternative evidence-group annotation", "Raw DOM/source-span checks do not prove semantic correctness or disclosure absence", "U16 currently/latest intent remains to be clarified; no current external market-share data added", "No retrieval-quality, RAGAS LLM-judge, or production-system result is claimed"]}
    calculations = OUT / "calculations.json"
    if calculations.exists():
        manifest["outputs_sha256"][calculations.name] = sha(calculations.read_bytes())
        manifest["calculation_fixture"] = "Offline annotation arithmetic and inputs; not a deployed financial tool or automatic claim verification"
    (OUT / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"cases": len(cases), "evidence_blocks": len(evidence), "source_documents": len(checked), "review_path": str(OUT / "review.md"), "status": "pending_human_review"}, ensure_ascii=False))


if __name__ == "__main__":
    main()
