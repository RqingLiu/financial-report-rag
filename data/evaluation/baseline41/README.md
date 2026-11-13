# 41-case canonical baseline

Selected on 2026-11-10 from the 81 canonical development intents, **before new model answers**. This is a full end-to-end baseline preparation, not a measured result or an independent holdout. The remaining 40 canonical cases can share families/sources and are not automatically a test split.

- All 20 parent requests and six categories: 3 lookup, 13 calculation, 6 boundary, 11 synthesis, 4 time reasoning, 4 comparison.
- All 12 previously accepted canonical pilot overlays are included under their original U IDs. The other 29 references/rubrics were agent-audited against local source HTML; they are not represented as newly human-reviewed gold.
- 37 cases have positive evidence requirements. Four disclosure-only cases have N/A evidence recall and are assessed for correct limits/non-fabrication.
- The audited bundle has 166 evidence groups, 80 mandatory facts, 75 unique required numeric checks plus two dependency-only checks, and 133 source locations. The numeric checks are not exhaustive audits of every asserted number.

## Review and inputs

| File | Purpose |
| --- | --- |
| [review.md](review.md) | All 41 questions and per-case review decisions |
| [reference_answers.md](reference_answers.md) | Reviewed references and public SEC links; judge-only |
| `retrieval_queries.jsonl` | The only runtime input, with no labels or reference answers |
| `cases.jsonl` / `rubrics.jsonl` | Task-local behavior, evidence and answer requirements; judge-only |
| `numeric_checks.jsonl` | Source-anchored formulas/units/periods, tolerances and dependencies |
| `evidence_catalog.jsonl` | Source excerpts, disclosure dates, DOM and character locations |
| `audit.json` / `manifest.json` | Selection, audit provenance, source/output hashes |
| [cost_estimate.json](cost_estimate.json) | No-provider cost preflight and cache/usage assumptions |

The original compound v2, 81-intent v3 and accepted pilot were not changed. Corrections remove unrelated inherited requirements rather than relaxing a case to fit new outputs. New outputs have not been observed. Do not compare the revised evidence denominator directly with historical scores.

Validated offline: original HTML SHA, DOM locations, exact canonical spans, disclosure cutoffs and 77 numeric formulas/dependencies. The historical-point-in-time case uses only NVDA FY2024. Complete answer/citation truthfulness still needs rubric review after actual generation; source validation is not a new answer-quality score.

## Cost gate

The user authorizes a requested full round only if the entire estimate is **below USD 0.20**; later tuning rounds have the same per-round threshold. Do not split an over-budget 41-case round into cheaper sub-batches to bypass that condition. No paid Judge is included.

Preflight found 0/41 exact planner-cache hits and no matching question payload in the saved rerank cache. Document vectors are reused; future search-query embedding hits remain unknown until planning. Estimates use current peak uncached list prices, without assuming provider cache/free/off-peak credits. [DeepSeek pricing](https://api-docs.deepseek.com/quick_start/pricing/) · [Voyage pricing](https://docs.voyageai.com/docs/pricing).

| Scenario | Planner | LLM rerank | Generation | Embedding / repairs | Total |
| --- | ---: | ---: | ---: | ---: | ---: |
| Lean | $0.076 | $0.234 | $0.107 | $0.001 | **$0.417** |
| Central | $0.076 | $0.350 | $0.169 | $0.051 | **$0.646** |
| Conservative | $0.076 | $0.602 | $0.279 | $0.101 | **$1.058** |

These are assumptions grounded in 45 saved planner responses, 252 rerank batches (15 with one/two needs), and 17 generated answers; they are not exact invoices or worst-case guarantees. Lean assumes two rerank batches and shorter answers on only the 37 positive-evidence cases. The current Top80 path often needs three or more batches. Provider discounts may lower the bill; the persistent ledger currently reserves conservative peak list costs.

**Decision: wait for approval of a larger round cap; no paid calls started.** The proposed one-time baseline cap is **USD 1.10**, with the same persistent cumulative ledger and unresolved charges preserved. A cap can still stop a high-cost run early; incomplete execution must remain visible. This proposal does not raise future tuning-round authorization above USD 0.20. The default service cumulative stop was not edited.

## Commands

The following command does not call providers or the database:

```bash
python -m finrag.evaluation validate-set --dataset data/evaluation/baseline41
```

After a separately approved live run, use the existing `diagnose`, `prepare-judge`, `export-judge`, `score` and `compare` commands with this dataset. Diagnostics alone do not create a semantic Judge score. See [evaluation contract](../../../docs/evaluation.md).

## Execution approval — 2026-11-11

The user approved the one-time USD 1.10 hard cap for this 41-case baseline. The preceding cost report records the earlier preflight state and is preserved. The run uses default retrieval/generation settings, no paid Judge, the original cumulative ledger and a USD 1.10 batch cap. Only this experiment receives an explicit cumulative-stop override; the default service configuration and future USD 0.20 tuning-round rule remain unchanged. Actual outputs and complete traces stay in the ignored local reports directory.

## Baseline execution — 2026-11-11

All 41 cases were attempted with the approved default configuration: 38 generated responses and three scope-validation failures before retrieval. The new conservative peak-list cost was USD 0.91794642 (cap USD 1.10); no new unresolved holds. Source/config/dataset identities and prior annotations remained unchanged. The three failures remain in the round denominator; they were not rerun.

Among 34 positive-evidence cases with recorded retrieval stages, macro candidate recall was 93.15%, Top80 recall 87.97%, and actual-context recall 78.55%. Including three pre-retrieval failures as not covered gives an all-37-positive-case confirmed context-coverage lower bound of 72.18%. Four disclosure-only cases have N/A positive-evidence recall. This is a new baseline with different questions/labels; do not claim improvement over older compound-question scores.

Five-dimension answer quality and task accuracy remain pending calibrated Judge/human review. Complete local outputs, 41 review packets, 38 whole-answer prompt envelopes, costs and seven anchored bad-case/annotation-review entries are stored under `reports/current/baseline41_20261111_default/` (ignored, not published). No paid Judge or tuning round was run.

## Offline answer review — 2026-11-12

The first-pass, in-conversation assisted review now covers all 41 attempts using the unchanged whole-answer rubric, item requirements and actual runtime evidence. It is not an independent Judge or human approval. There are 26 strict passes, 12 answer-level failures and 3 execution failures; required fact points are 66/80 and correct required numeric applications 70/84. Missing/failed deliveries remain in those denominators. All 38 generated answers have five reasoned rubric scores; separate delivery-adjusted aggregates retain the 41-attempt denominator. Five additional material-error cases show why passing the mapped numeric checks does not establish full-answer truthfulness.

Reviewable local summary and 41 case pages: `reports/current/baseline41_20261111_default/review/review.md`. The same directory holds hash-bound judgments, original answer/source excerpts, scored diagnostics and verification receipts. These outputs remain ignored by Git. No new provider calls, paid Judge, retrieval or tuning occurred. Thirty related offline regressions passed; reviewer adjudication remains pending. The preceding preparation/execution sections retain their original dated states. Frozen source/annotation files and manifests were not edited.
