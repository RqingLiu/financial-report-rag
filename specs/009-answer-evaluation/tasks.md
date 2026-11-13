# Tasks: End-to-End Answer Evaluation

## Setup

- [x] T001 Define requirements, design, replay contract and quickstart in `specs/009-answer-evaluation/`.

## US1 — Score saved answers

- [x] T002 [US1] Prepare hashed packets and score validated rubric/number/citation rows in `src/finrag/evaluation/answer_eval.py` (FR-001–004).
- [x] T003 [US1] Author six provisional verdicts in ignored `reports/answer_eval/pilot_v1/verdicts.json` (FR-002–006).

## US2 — Review and reproduce

- [x] T004 [US2] Generate JSON and Markdown reports in `reports/answer_eval/pilot_v1/` (FR-005–007).
- [x] T005 [US2] Test arithmetic, scope, provenance and failure handling in `tests/test_answer_eval.py` and replay the pilot (SC-001–003).
- [ ] T006 [US2] Collect human corrections before rating judge agreement or claiming readiness; use a separate local adjudication artifact.

T001 precedes T002; T003 uses prepared packets. T004 and T005 verify the completed replay before T006. A paid baseline, independent holdout and automated judge adapter are deferred.

Validation: seven new evaluator tests; full suite 101 passed and seven skipped with the static tokenizer vocabulary cached. Frozen Golden v2 passed read-only verification. A second offline replay produced byte-identical packets, scores and review. No paid model calls.

## US3 — Judge the whole answer

- [x] T007 [US3] Define the anchored rubric in `specs/009-answer-evaluation/contracts/whole_answer_rubric.json` and export/validate whole-answer judgments in `src/finrag/evaluation/answer_quality.py`.
- [x] T008 [US3] Score the same six historical answers in ignored `reports/answer_eval/pilot_v2/` and add the dimension table to the replay report in `src/finrag/evaluation/answer_eval.py`.
- [x] T009 [US3] Verify score ranges, provenance, material-error caps and empty attempts in `tests/test_answer_quality.py`; replay the six-answer report without paid calls.

Follow-up validation: 110 tests passed and seven skipped. All 30 whole-answer dimension verdicts imported. Export, score and report replay were byte-identical; original item-level results and frozen Golden v2 were unchanged. Human calibration is pending.

## Six-Question Optimization

- [x] T010 Trace planner coverage and exact evidence losses in the six frozen pilot cases (FR-010).
- [x] T011 Implement and run an opt-in replay experiment in `src/finrag/evaluation/answer_optimization.py` with saved reranked contexts and two prompt-only probes (FR-011).
- [x] T012 Rescore saved outputs under the existing rubric and write a local comparison in `reports/answer_eval/optimization_v1/comparison.md` (FR-012).

Follow-up validation: 112 tests passed and seven skipped. Eight generation attempts succeeded, with no new search, embedding or reranking calls. Rubric hash, original questions and plans matched; prompt-only probes preserved exact original evidence. Estimated peak-list generation cost was $0.04683540. No serving default or frozen label changed.

## Twenty-Question Historical Baseline

- [x] T013 [US3] Prepare and grade all 20 saved responses in `reports/answer_eval/historical_baseline_20/`, preserving six prior verdicts (FR-013).
- [x] T014 [US2] Validate the full replay, subset comparisons and stage diagnostics in `reports/answer_eval/historical_baseline_20/` (FR-014).

Validation: 20 historical responses, 87 required facts, 147 applicable numeric checks, and 225 evidence groups. A second offline replay reproduced the packets, scores and report byte for byte. Prior verdicts and the frozen Golden v2 bundle were unchanged. No provider calls; current-default and independent holdout results remain pending.

## Current-Default Paired Benchmark

- [x] T015 Estimate current cache reuse and cost without provider calls (FR-015–016).
- [x] T016 Run the unchanged default pipeline on all 20 requests within the authorized ledger stop, saving resumable attempts and provenance (FR-015–016).
- [x] T017 Apply the unchanged rubric and compare paired answer completeness, numeric results and regressions with the historical baseline (FR-017).

Validation: all 20 attempted; 17 delivered answers, two SQL timeouts and one structural answer rejection. No automatic retries or default configuration changes. The user authorized an experiment-only cumulative stop of $2.20; new conservative list-price spend was $0.47730198. All 20 planner keys and 52 rerank batch keys missed; 54 rerank calls include two contract repairs. Existing document vectors were reused. Paired 17-answer completeness rose from 2.71 to 3.41; truthfulness remained 3.53. Numeric passes rose 40/108 to 42/108 on those 17, but fell 50/147 to 42/147 across all attempts. Judge calibration remains pending. Full artifacts are ignored under `reports/answer_eval/current_default_20/`.

## Targeted Reliability and Numeric Follow-up

- [x] T018 Preserve failure probes and stage attribution for the six cases (FR-018–020).
- [x] T019 Implement bounded SQL recovery, answer-contract repair and generic arithmetic preparation; test cancellation, budgets, invalid anchors and expression safety (FR-018–020).
- [x] T020 Run only the six requested cases and compare unchanged rubric/numeric checks with the frozen default baseline, including spend and regressions (FR-021–022).

Validation: 118 offline tests passed, eight skipped; six PostgreSQL integration checks passed, including injected statement timeout and rollback. Both six-case rounds delivered 6/6; U15 exercised one answer-contract repair. U04/U06/U11 retained identical plans and evidence. Second-round numeric passes were U11 17/20, U04 0/9 and U06 3/16 versus 0/20, 3/9 and 1/16. All six required checks rose 4/84 to 46/84, substantially affected by delivery recovery. Direction-word extraction was checked against adjacent amount versus level phrasing, and both control and candidate were replayed with the same scorer; Golden and tolerance values were unchanged. Combined new estimated peak-list spend was $0.22960740; cumulative known spend $2.08623396 plus unchanged $0.0093642 unresolved reserve, under the authorized $2.20 stop. Default budget stays $1.60.

Decision: retain SQL/structure reliability fixes by default, but keep arithmetic and its experimental precision prompt opt-in because U04 regressed and U06 still has sign/period errors. The original default generation prompt is preserved. Do not select different prompts by question or call mathematical expression execution a verified financial calculator. Original SQL timeout cause remains unconfirmed; read-only hot-cache probes did not reproduce it. First-round failures of the new arithmetic approach are retained under `reports/answer_eval/targeted_fix_v1/`; final paired verdicts and explicit limitations are under `targeted_fix_v2/`. Human calibration and independent generalization remain open.


Pilot-stage follow-up (design reviewed 2026-11-09):
- [x] Reconcile the pilot reviewer corrections and obtain approval for scoped labels/new required comparisons.
- [x] Export compatible pilot evaluation inputs, references and behavior labels without changing v2/v3.
- [ ] Add behavior, planner and stage scorers plus a unified paired per-case report.
- [x] Exercise the evaluator with fixed receipts and explicit failure/skip denominators before paid baseline execution.

These tasks are planned, not implemented or validated pipeline improvements.


Finalized evaluation scope (2026-11-09):
- [x] Add the six policy-approved boundary/mixed scenario types and explicit clarification continuations, and export the corrected accepted pilot (new wording marked synthetic).
- [ ] Implement disposition-specific behavior metrics, the documented formulas/N/A states and strict per-case success accounting.
- [x] Implement shared stage/resource extraction and a paired report with local bad-case run/span/source/code links.
- [ ] Calibrate judge sensitivity and human disagreement on saved answers and controlled-error fixtures.
- [ ] Run only separately authorized paid subsets and report measured scope; leave any LangSmith export disabled until explicitly configured.

Design is finalized; these implementation and data tasks are not marked complete.


First offline implementation: dataset.py validates the accepted manifest, safe query-only schema, source/cutoff/group and family contracts; benchmark.py diagnoses saved traces, exact context spans, temporal/document violations, anchored imported behavior reviews, existing answer/whole-rubric results and paired regressions. Unrun/unjudged cases never pass. Intent preservation still requires semantic review; full claim auditing and conditional ranking metrics are not claimed. Existing runtime, budgets, provider defaults and cloud tracing were untouched. This is control/scoring verification, not a new financial accuracy score.

Validation of the first offline increment: 116 local tests passed with seven opt-in database skips; a clean working-tree export passed 114 with nine corpus/database skips. Ten new contracts exercise manifest/query leakage rejection, exact selected-span recall, unrun/unjudged accounting, anchored/stale review rejection, failure/cutoff invariants, corpus-precondition changes, nested timing/SQL recovery accounting, paired regressions and compatibility with existing item/five-dimensional scoring. All 40 exported numeric definitions (38 required plus two support-only) were rechecked against local raw sources. Original v2/v3 validators and publication/link checks passed; three provider-free CLI entries were exercised without importing runtime provider/DB wiring. No paid calls, runtime policy changes or GitHub push occurred.

41-case baseline increment, 2026-11-10:
- [x] Lock 41 representative IDs without looking at new answers.
- [x] Audit references, task-local evidence, rubric, numbers and accepted overlays.
- [x] Validate the separate baseline bundle and source/date/numeric checks offline.
- [x] Estimate the entire default round using cache identities and historical usage.
- [x] Apply the USD 0.20 full-round gate; obtain approval before any over-limit paid execution.

Preflight completed on 2026-11-10: 41 cases across all 20 parents; 12 accepted overlays plus 29 agent source audits. Revised 191 inherited evidence groups into 166 task-local groups; 80 fact requirements, 75 required numeric checks plus two dependencies, 133 verified source locations. No new answers were used for selection or label changes. Cache probe: zero exact planner hits and zero matching rerank-question payloads. Estimated complete-round costs USD 0.417 / 0.646 / 1.058 exceed the USD 0.20 gate. Paid execution is pending approval of the proposed one-time USD 1.10 cap; future tuning authorization remains USD 0.20 per requested round.

Execution approval, 2026-11-11:
- [x] Receive explicit one-time USD 1.10 approval; retain the original ledger and unknown holds.
- [x] Execute the exact 41-case default baseline under matched source/config identity and the approved cap.
- [x] Diagnose actual traces and export answers/Judge packets without paid Judge calls; preserve failures and not-run cases.
- [x] Record per-case delivery, coverage, resources, costs and bad-case evidence; distinguish stage metrics from answer quality.

2026-11-11 result: all 41 selected cases executed; 38 generated responses (10 answered, 28 model-declared partial), 3 invalid-result failures in scope validation before retrieval. New conservative peak-list cost USD 0.91794642 < USD 1.10, zero new unknown holds, historical unknown hold preserved. There were 232 provider attempts, 194 logical LLM calls and 512 search SQL attempts. Recorded positive-stage averages (n=34): candidate 93.15%, Top80 87.97%, actual context 78.55%. Across all 37 positive cases, confirmed context-coverage lower bound is 72.18%; four disclosure-only cases are N/A. These are not answer-accuracy scores. Exported 41 answer packets, 38 whole-answer Judge prompts and 41 behavior packets locally, with no paid Judge calls. Seven anchored bad-case/annotation-review entries were inspected. Full calibrated whole-answer scoring/human review remains pending. No rerun, optimization, index/config change or Git publication occurred.

Offline whole-batch review, 2026-11-12:
- [x] Verify saved receipts and author anchored judgments for all facts, numeric applications, limits and material errors.
- [x] Rate all generated answers on the unchanged five-dimensional rubric; preserve the three failed deliveries in whole-batch denominators.
- [x] Validate excerpt/hash/unit/rounding contracts and report citation support separately from ID validity.
- [x] Deliver reviewable reasons, disagreements and full-batch summaries without paid Judge or tuning.

2026-11-12 first-pass review completed: 41 item and behavior verdicts, 38 whole-answer verdicts, 80 required facts and 84 numeric applications. All saved packet identities were regenerated and matched; literal/source/citation/unit contracts passed. Results: 26 strict passes, 12 answer failures, 3 execution failures; 66/80 weighted fact points and 70/84 correct required numbers. Five cases have additional material errors, including one unit-magnitude error outside the frozen numeric checks. Thirty related offline tests passed. No provider/Judge calls, retrieval, tuning or publication. Human adjudication remains pending; this is not independent validation.

Offline triage and next-step proposal, 2026-11-12:
- [x] Reproduce all three guard failures from the six saved model responses; distinguish model intent from deterministic scope rejection.
- [x] Reconstruct fusion rankings from saved records and locate Top80/context losses for five material-error cases.
- [x] Check actual source alternatives, units, periods and contradictory output; distinguish observed defects from causal hypotheses.
- [x] Deliver a general, same-budget optimization plan with offline checks, live-comparison controls and no paid execution.
- [ ] Implement the proposed scope and financial-output contracts as a subsequent increment, retaining negative scope controls.
- [ ] Compare same-pool ranking/context alternatives and validate source-bound periods/headers without gold-driven runtime rules.
- [ ] After a separate live-run instruction and whole-round cost gate, evaluate generated answers with unchanged rubric and successful controls.
