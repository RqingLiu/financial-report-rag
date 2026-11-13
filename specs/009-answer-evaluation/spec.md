# Feature Specification: End-to-End Answer Evaluation

**Feature Directory**: `specs/009-answer-evaluation`
**Created**: 2026-11-04
**Status**: Pilot; human calibration pending.

## User Scenarios & Testing

### User Story 1 — Score saved answers (P1)

A reviewer scores historical answers against the original question and Golden v2 rubric, even if the original plan omitted a subquestion. Score completeness, numeric accuracy and citation support separately.

1. Given a generated answer, report every mandatory fact, applicable numeric check, expected limit and material-error rule with a verdict and reason.
2. Given a missing answer, failed run or wrong clarification, keep the attempt visible; do not score it as a successful response or silently remove it.
3. Given a valid citation ID attached to an unsupported claim, mark it unsupported or partial. A correct disclosure limit does not count as a missing required number.

### User Story 2 — Review and reproduce the pilot (P1)

A reviewer can trace a verdict to an answer excerpt and the actual cited text, correct the annotation, and recompute results without retrieving or generating again.

1. Given a changed answer, rubric, or evidence packet, reject stale verdicts.
2. Given an ambiguous number, currency, period or scope, show a review state rather than guessing. Missing numbers remain in the required-check denominator.

### User Story 3 — Judge the whole answer (P1)

A reviewer can score the whole response against a shared 1–5 rubric, then use the detailed checks to explain the score.

1. A relevant but incomplete answer may receive a high relevance score and a low completeness score. An appropriately limited answer is not penalized for unavailable disclosures.
2. Materially false claims, including wrong fiscal periods, units or accounting categories, constrain truthfulness even when the answer is clear. A claim supported elsewhere in the supplied context can be faithful while its attached citation is wrong.

## Scope and Change Boundaries

- Pilot: six historical development answers from a single saved planner run, using this conversation as the first-pass judge and local code for validation and arithmetic.
- Preserve runtime, existing metrics, frozen data, historical traces and spending controls. Judge reads gold only after answer generation. No paid calls, live queries, holdout claims, production score, automated judge API or publication of local review artifacts in this increment.
- Later: calibrate with reviewer corrections and controlled wrong-answer examples; freeze a judge version, score a current-default baseline, then compare one change at a time and evaluate an untouched holdout.

## Requirements

- **FR-001**: Bind replay to the original question, reading context, confirmed constraints and cutoff. Record a fingerprint of each selected trace and judge input.
- **FR-002**: Grade mandatory facts as correct, partial, missing, incorrect or uncertain; check answer limits and prohibited inferences independently. Use the gold rubric, never the planner's needs, as the denominator.
- **FR-003**: For each answered fact assess citation support against its attached runtime evidence. Distinguish supported, partial, unsupported, uncited and uncertain; use not applicable for omitted facts or disclosure/scope judgments with no source claim. Log invalid citation IDs and cutoff violations separately.
- **FR-004**: Check every applicable numeric ID. A judge maps the literal answer value to the expected metric/period/unit/scope; deterministic comparison uses the published Decimal tolerances and declared rounding. Wrong scope/unit is material even if values match. Unresolved extraction is separate from missing or incorrect.
- **FR-005**: Produce per-item explanations and excerpts, per-question pass/fail/review, and separate aggregate counts. A pass requires every mandatory fact correct, applicable citations supported, applicable numeric checks passing (minor precision reported separately), expected limits met, no material violation and valid temporal scope. Unknown judgments prevent a pass.
- **FR-006**: Report that citations are rubric-anchored, not an exhaustive audit of all answer claims. Include meaningful extra errors as separate observations. All pilot judgments remain provisional until human review.
- **FR-007**: Prepare and score offline, reject malformed/incomplete or stale judge output, and keep local outputs out of Git.

- **FR-008**: Export a reusable, versioned whole-answer judge input with anchored scales for completeness, truthfulness, faithfulness, relevance and clarity. Import one reasoned score per dimension with trace and rubric fingerprints, answer excerpts, and any supporting source excerpts. Keep dimensions separate; do not average them into a quality grade. An uncertain dimension has no score and requires review. A non-generated attempt has no quality scores and remains in the end-to-end attempt count.
- **FR-009**: Keep whole-answer scores distinct from numeric and citation diagnostics. Reject a truthfulness score above 2 when the diagnostic layer flags a material factual/numeric error or the answer cites evidence outside its allowed scope. Keep earlier pilot files unchanged.

### Key Entities

Evaluation packet, rubric item, observed numeric value, attached citation, judge verdict, score report and human adjudication.

## Success Criteria

- **SC-001**: Six saved answers scored, with no required item silently dropped and no provider calls.
- **SC-002**: A reviewer can inspect answer snippets, cited runtime evidence and rationale for every marked item. Score files record their inputs and judge method.
- **SC-004**: The same six responses have five whole-answer judgments with explicit score anchors and reasons. Replaying saved judgments is deterministic; malformed and stale judgments are rejected.
- **SC-003**: Replaying the same packet/verdicts produces identical scores; wrong scope, missing numeric values, invalid citations, stale data and incomplete verdicts are caught.

## Acceptance Traceability

| Requirements | Criteria | Evidence |
| --- | --- | --- |
| FR-001, FR-007 | SC-001, SC-003 | Replay CLI, fingerprints and fail-closed validation |
| FR-002, FR-003, FR-006 | SC-001, SC-002 | Rubric/citation review report with explicit denominators |
| FR-004, FR-005 | SC-002, SC-003 | Numeric and pass-rule tests plus pilot results |
| FR-008, FR-009 | SC-002, SC-004 | Versioned whole-answer rubric, export/import checks and six-answer report |

## Assumptions

Historical outputs are development samples, not current serving results. The first judge is an in-conversation assessment with no API model identity claim. Reviewer corrections are stored separately from Golden v2.

## Six-Question Optimization Follow-up (2026-11-06)

- **FR-010**: Diagnose only U03/U06/U10/U12/U14/U16 using original requests, saved plans and evidence-group coverage at candidate, Top80 and final-context stages. Distinguish observed loss from a suspected root cause and identify generation errors even when context contains the relevant evidence.
- **FR-011**: Compare historical responses with a six-question replay using the previously defined dense Top80 reranked contexts and a reusable financial-scope generation prompt. Run two additional prompt-only probes on the original U06/U14 contexts. The generator receives only recorded request, plan and evidence; no rubric, reference, gold passages or case-specific answer rules. Keep serving defaults and frozen results unchanged.
- **FR-012**: Apply the unchanged item and whole-answer rubrics to all generated responses and report per-question changes, failed attempts, spend and context length. The mixed intervention is not a causal test of retrieval versus generation; historical comparisons are not concurrent A/B tests. Limit generation to these six questions and do not raise the shared spending stop.

## Twenty-Question Historical Baseline (2026-11-06)

- **FR-013**: Score all 20 saved responses from the same historical planner run using the existing whole-answer rubric and item diagnostics. Reuse the six earlier verdicts only when packet and rubric hashes match. Keep the six-question optimization subset separate from the remaining 14 for descriptive comparison.
- **FR-014**: Report per-question and aggregate results, stage evidence coverage and known limitations. This is a historical development baseline, not a fresh run of the current serving configuration or an independent generalization test. Do not call providers or change frozen inputs for this baseline.

## Current-Default Paired Benchmark (2026-11-07)

- **FR-015**: Run the same 20 query-only requests through the unchanged serving `execute` path, including the published catalog, planner, HNSW search, Top80 LLM reranking and default answer prompt. Reuse only exact existing cache keys. Preserve the historical baseline and six-question prompt experiment separately.
- **FR-016**: Estimate cost before paid execution. Keep the configured shared spending stop unless the user explicitly authorizes an experiment-only increase. Save configuration/source/catalog fingerprints, actual traces, attempt status, provider usage, cache events and before/after ledger snapshots. Resume completed attempts without rebilling; never automatically retry failed attempts with uncertain billing.
- **FR-017**: Apply the same rubric and deterministic numeric tolerances after generation. Report paired changes and per-question regressions, with all attempted questions visible. Historical comparisons are not concurrent controlled A/B tests; development results do not establish independent generalization.

## Targeted Reliability and Numeric Follow-up (2026-11-07)

- **FR-018**: Diagnose the three failed deliveries without erasing attempts. A search may recover once per request from a confirmed statement timeout, using the same filters, ANN parameters and five-second per-attempt bound. Preserve rollback, count retries against the SQL-call budget, and record timing/error diagnostics. Do not retry explicit user cancellation or other database errors. Disable JIT locally for ANN statements whose forced plan costs can spuriously trigger compilation; do not claim this proves the original transient cause.
- **FR-019**: Validate generated answer structure separately from generation. Give at most one repair with concrete structural violations, the original evidence and the preceding response. Never synthesize missing-evidence explanations or silently change partial to supported in code. Provider failures/unknown billing are not repairable answer errors. Preserve both responses and validation feedback in traces.
- **FR-020**: Diagnose U11/U04/U06 at planner, candidate, final-context and generation stages. Add a generic, opt-in evidence-bound arithmetic preparation step: the model selects literal operands and expressions from actual context; a bounded Decimal evaluator checks source anchors and arithmetic without executing arbitrary code. Company, case IDs, gold values and reference formulas must not occur in runtime rules. Arithmetic verification is not proof of correct accounting scope or complete operand selection. Keep full-input/evidence limits and shared ledger enforcement.
- **FR-021**: Re-evaluate only U01/U02/U15/U11/U04/U06, retaining the current-default 20-question run as the comparison. Record the experiment-only $2.20 cumulative stop, exact cache reuse, failed attempts, costs, unchanged rubric and per-question regressions. Calculator activation remains explicit during this pilot; broader rollout and all-20 retesting are out of scope.

- **FR-022**: A judge may explicitly map a decrease amount written in words to a negative change. Verify the adjacent direction phrase and exact numeric literal; reject level phrases such as “decreased to” and “下降至”. This extraction correction does not change Golden values or tolerances. Recompute the same six control judgments with the same scorer used for the candidate; never silently compare different scorer versions.


## Finalized pilot evaluation contract — 2026-11-09, design only

- **FR-023**: Evaluate answer, partial answer, clarification, unavailable disclosure and unsupported task as distinct expected dispositions. Distinguish business-out-of-domain, unsupported financial capabilities, missing corpus coverage and material ambiguity. Infrastructure failure, deadline, cancellation and budget exhaustion are operational outcomes, not valid refusals. Mixed requests retain supported portions and explicit limitations. Do not require financial-answer scoring for a correctly scoped clarification.
- **FR-024**: Use the metric definitions, applicability, denominators and strict task-pass semantics in docs/evaluation.md. Report selected/attempted/completed coverage and success, separate five-dimensional quality, fact and required-numeric coverage, asserted-numeric accuracy with audit coverage, and citation validity/support/coverage. No arbitrary composite score or conversion of Likert scores to correctness percentages. Preserve missing/failed answer requirements and null/unjudged states.
- **FR-025**: Report planner intent/constraint checks and source-group recall at candidate, Top10/20/80 and actual-context stages as diagnostics. Require explicit qrels/judgment coverage for MRR, Precision, nDCG and context relevance/precision; unlabelled results are not negatives. Boundary/clarification cases never receive empty-gold recall=1. Preserve case/family grouping and paired controls.
- **FR-026**: Link all failures, material errors, regressions and disputed judgments to local run/span/source/code evidence and a reproducible bad-case record. Distinguish observed first divergence from a proven cause. Truncated historical traces cannot support invented upstream reconstruction. Keep a small set of success controls.
- **FR-027**: Reuse the current evaluation CLI, pytest, source/numeric validators and versioned rubric. Use local trace storage/Trace Studio first; optional LangSmith export must be explicitly enabled, sanitized, noncritical and independently cost-accounted. Trace ingestion must not change financial execution, cause paid retries or silently call an evaluator. This plan does not authorize credentials, cloud uploads, paid evaluation or default changes.
- **FR-028**: Before claiming scope robustness, add six planned boundary/mixed-case types and explicit follow-up inputs for the three ambiguous mock cases. Independent reviewer opinions remain pending user confirmation; label freezing and code implementation are later deliverables. Report performance only for the selected, actually measured batch.

## Authorized 41-case baseline preparation — 2026-11-10

Select exactly 41 of the 81 canonical development intents before observing new model outputs, cover all 20 parent requests and all task categories, and carry accepted pilot corrections forward by origin ID. Audit the selected references, task-local evidence/rubrics, disclosure cutoffs, units, arithmetic and provenance. Preserve v2/v3 and the accepted pilot unchanged; publish a separate purpose-scoped development bundle, not a holdout.

Estimate a full default end-to-end round from current official prices, exact available cache identities and historical usage; include planner, query embeddings, LLM reranking, generation and repair uncertainty. Exclude paid Judge calls unless separately authorized. Never present a capped partial run as a complete 41-case baseline. The user authorizes this baseline and later explicitly requested tuning rounds only when each entire round is estimated below USD 0.20 and bounded by that amount in the existing ledger. A higher or uncertain estimate requires approval before any paid call. Keep the historical cumulative ledger and unknown reservations intact; no credit resets, index/model/reranker changes or arbitrary price discounts to meet the threshold.

## One-time execution approval — 2026-11-11

The user approved a USD 1.10 hard cap for the selected 41-case default end-to-end baseline. This approval supersedes the USD 0.20 automatic-start threshold for this baseline only. Preserve all historic spend and unknown reservations in the sole ledger; apply a batch scope of USD 1.10 and an experiment-only cumulative stop equal to pre-run known plus held cost plus USD 1.10, still below the original project authorization. No paid Judge, algorithm/configuration tuning, automatic failed-case rebilling, or additional full rounds are included. Later requested tuning rounds retain the user's USD 0.20-per-round rule.

## Authorized offline 41-case end-to-end review — 2026-11-12

Score all 41 saved baseline attempts against the existing finrag-whole-answer-v1 rubric, 80 mandatory facts, 84 scoped numeric applications and attached runtime citations, without new retrieval, generation, paid Judge calls or tuning. Use an in-conversation first-pass judge with explicit provenance; leave disputed source-equivalence or wording judgments visible for human review. Preserve all trace/dataset/rubric hashes and tolerances. Assess additional material errors, including wrong table fact periods, rather than only preselected numbers.

Failures remain in the 41-task, 80-fact and 84-numeric denominators. Do not invent truthfulness scores for absent answers: retain the original 1–5 rubric means for the 38 generated answers, and separately report per-dimension delivery-adjusted means over 41 with failed deliveries contributing zero (a reporting penalty, not a new zero rubric anchor). Keep dimensions separate, never call their average an accuracy rate. Report numeric required coverage separately from asserted-number accuracy on auditable mapped checks; report attached-citation support and required-fact citation coverage with explicit denominators. Unit-equivalent displays and valid rounding must not be scored as retrieval/financial errors; record unresolved mappings as review rather than guessing.

Offline normalization detail: retain the actual numeric literal and target check unit. Optional `display_unit` may select only an allowlisted USD conversion (100-million USD to million USD, or billion USD to million USD), with the displayed unit verified immediately next to the literal. Apply Decimal comparison and rounding at the original display precision; reject unsupported conversions or missing unit anchors. This does not alter references, numeric tolerances or rubric scores. A non-generated response must explicitly show its required numeric count as not_generated in the report, rather than claiming there were no applicable checks.

## Offline bad-case triage and optimization proposal — 2026-11-12

The user requested source-anchored analysis of three failed executions and five material-error cases, followed by a general optimization plan without paid execution. Preserve runtime configuration, prior answers, gold and scores. Reproduce the current scope-validation failure using saved model plans and reconstruct fusion ranks from saved records; identify stage loss separately from fact-equivalent alternative evidence. Do not equate strict span recall with the absence of usable facts, or assign a single causal stage from an answer score.

Proposed next increments, not implemented by this planning request: (1) distinguish report scope, comparative fact periods and disclosure cutoff while retaining strict exclusions; (2) evidence-anchored numeric units/periods and deterministic normalization plus item-level missing-evidence/accounting explanations; (3) same-budget evidence-objective Top80 retention and context deduplication/atomic source headers; (4) conditional BM25/CrossEncoder ablations only if residual losses warrant them. No issuer/question-ID branches, gold-driven runtime selection, automatic scope widening, extra unbounded repair loop, new agent or context-cap increase. Deterministic arithmetic and metadata do not certify semantic source mapping.

Validate proposed contracts with offline generic positive/negative and metamorphic fixtures first. Any later real generation comparison must be separately requested, maintain original controls and denominators, estimate the entire round and preserve the user's USD 0.20-per-round gate unless explicitly superseded. This design request grants no paid execution, including a round estimated below the gate.
