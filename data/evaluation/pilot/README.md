# Accepted pilot development dataset

The user accepted the independent review corrections and boundary behavior policy on 2026-11-09. This bundle applies those corrections without changing Golden v2, the 81-intent draft, or the original review packet. It is development data, not a holdout or a measured model result.

| IDs | Count | Purpose / provenance |
| --- | ---: | --- |
| C01–C12 | 12 | Selected canonical intents, corrected references and scoped evidence requirements |
| R01–R12 | 12 | Explicitly synthetic raw inputs: seven answerable, three needing clarification, two disclosure boundaries |
| B01–B06 | 6 | Agent-authored wording under the accepted boundary policy: unrelated task, unsupported financial capability, missing corpus, conflicting scope, mixed unsupported and mixed ambiguous requests |
| F01–F03 | 3 | Scripted explicit user confirmations after R08–R10; separate linked requests, not proof of persistent conversation memory |

The original 24 corrections/behavior expectations were accepted. New boundary and follow-up wording remains clearly agent-authored; policy approval is not a claim that these are observed user queries. Shared intent families stay together, including B04/B05/B06 and their related canonical cases. All are development cases.

## Files

| File | Responsibility |
| --- | --- |
| `retrieval_queries.jsonl` | **Only runtime input.** Exact allowlisted request fields, no answers, expected actions or latent intent mappings |
| `cases.jsonl` | Offline behavior rules, scope expectations, evidence groups, family and continuation links |
| `rubrics.jsonl` | Scoped answer facts, limitations, material errors and applicable numeric IDs; compatible with existing answer scoring |
| `numeric_checks.jsonl` | 38 required checks: 34 preserved original checks plus three margin-gap comparisons and one direct revenue value; two additional dependency-only checks are not extra answer requirements |
| `reference_answers.md` | Corrected standalone references with public SEC links; not runtime context |
| `evidence_catalog.jsonl` | Actual source excerpts, filing dates, DOM locations and character offsets needed by this bundle |
| `manifest.json` | User-acceptance scope, counts, input provenance and exact output hashes |

Evidence groups use OR across alternative source excerpts and AND for complete coverage across required groups. NRV alternative report columns are not both required; C09 does not require unrelated server CPU/GPU material. DSO wording explicitly requests actual fiscal-year days. C08 preserves the Data Center denominator and automotive data-center-processing scope. C12 includes trends and unrounded margin-gap comparisons.

## Offline commands

Run from the repository root with the verified environment activated. These three commands never open the database or call providers:

```bash
python -m finrag.evaluation validate-set --dataset data/evaluation/pilot

# Analyze existing matching traces; absent files are marked not_run, not simulated answers.
python -m finrag.evaluation diagnose \
  --dataset data/evaluation/pilot --traces reports/current/pilot-run/traces \
  --out reports/current/pilot-run/diagnostics

python -m finrag.evaluation compare \
  --before reports/current/pilot-control/diagnostics/diagnostics.json \
  --after reports/current/pilot-candidate/diagnostics/diagnostics.json \
  --out reports/current/pilot-comparison.json
```

`diagnose` produces `diagnostics.json`, anchored `behavior-packets.json` and a human report. It measures exact source-group coverage at recorded candidate/coarse/shortlist stages and **actual context spans**, checks cutoff/document invariants, and links failed spans and code identities. Missing stages are N/A. It does not infer semantic correctness from recall.

To score behavior, review each packet against its criteria and import an array using `--behavior-verdicts FILE.json`. Each verdict has:

```json
{
  "id": "R09",
  "packet_hash": "copy the exact exported hash",
  "judge_method": "human/model provenance",
  "disposition": "clarify",
  "asked_clarification": true,
  "criteria": [
    {"id": "R09:b1", "status": "pass", "reason": "explain the judgment", "quote": "literal response excerpt"}
  ]
}
```

Include **every** criterion ID from that case; statuses are `pass`, `fail` or `uncertain`. Passing judgments require nonempty literal response anchors. Other dispositions are `answer`, `partial_answer`, `unavailable`, `unsupported`. Anchor/hash checks establish auditability, not independent truth certification. Without imported review the case remains `needs_review`; no automatic semantic pass is fabricated.

Financial answer assessment reuses existing commands:

```bash
python -m finrag.evaluation prepare-judge \
  --traces reports/current/pilot-run/traces --golden data/evaluation/pilot \
  --ids C07 --out reports/current/pilot-run/answer-packets.json
```

Then use existing `export-judge` / `score` with the unchanged five-dimension rubric. Pass the resulting `scores.json` to `diagnose --answer-scores FILE.json`. Trace/packet identities and denominators must match. Whole-answer scores are reported separately, and no trace/Judge is called by these offline tools. The scorer still needs externally authored verdicts.

## Current implementation limits

- Stage recall, scope invariants, imported behavior judgments, existing answer-score merging, basic resource extraction, per-case reporting and paired deltas are implemented. Task/fact/numeric summaries are explicitly **known lower bounds** while judgment or execution coverage is incomplete.
- Planner intent coverage and complete semantic scope preservation still need manual/structured judging; they are not faked by word matching. Precision/nDCG/context relevance require additional qrels and remain unavailable.
- Full claim-level citation coverage, asserted-number auditing, automatic Judge execution, judge/human calibration on real historical answers, and consolidated orchestrator cancellation/deadline/fallback remain next increments.
- Existing traces may omit admission/resource time. The reported instrumented-span range is not an end-to-end p95 and does not sum overlapping spans.
- B03's missing-corpus precondition must remain true; if a recorded catalog now contains AAPL FY2025, diagnosis rejects that outdated scenario instead of blaming the model.
- Original review artifacts retain their prior pending-review state as historical evidence. This accepted export, not edits to their original hashes, records the later user decision.

No new financial model answer, paid evaluation, live retrieval result, cloud upload or measured generalization score was produced by preparing this dataset/framework.

## 新增情境：可直接阅读的索引

以下具体措辞由Agent按已接受的行为政策编写；均为合成开发场景。B03明确提供了“未入库”的场景前提，不代表任何未来数据库永远不包含该公司。

| ID | 用户问题 | 预期行为 |
| --- | --- | --- |
| B01 | 明天去旧金山旅游需要带伞吗？帮我查天气。 | 说明当前任务/能力不支持 |
| B02 | 给我NVDA现在的实时股价，再用DCF算一个可以买入的价格区间。 | 说明当前任务/能力不支持 |
| B03 | 只用当前已入库资料分析AAPL FY2025的营业收入，不要上网找。 | 说明资料库缺覆盖 |
| B04 | 比较AMD FY2023和FY2024的收入。 | 澄清冲突范围 |
| B05 | NVDA FY2026数据中心收入是多少？顺便查一下明天旧金山会不会下雨。 | 回答可证部分，说明限制或澄清其余部分 |
| B06 | NVDA FY2026数据中心收入是多少？再比较它和AMD那几年的毛利率。 | 回答可证部分，说明限制或澄清其余部分 |

澄清后续是显式提供的用户补充，首轮R08–R10看不到这些内容：

- F01 接 R08：我指MU美光，比较FY2024、FY2025和FY2026年报里的HBM产品进展。
- F02 接 R09：比较AMD FY2023、FY2024和FY2025，给出四项业务收入和两次增量的合并勾稽。
- F03 接 R10：两家是NVDA和AMD，分别用NVDA FY2024–2026和AMD FY2023–2025年报，比较游戏与专业绘图产品用途。
