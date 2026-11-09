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
