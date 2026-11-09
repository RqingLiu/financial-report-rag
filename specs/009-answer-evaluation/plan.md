# Implementation Plan: End-to-End Answer Evaluation

**Date**: 2026-11-04 | **Spec**: [spec.md](spec.md)

## Summary and Technical Context

Use a provider-free Python 3.12 CLI in `src/finrag/evaluation/answers.py`. Prepare JSON packets from saved traces and Golden v2. Import structured judgments authored in this conversation, validate their anchors, compare numbers with Decimal, and render a Markdown review plus JSON scores. Use existing file helpers; no database, new dependencies, serving changes or network access.

## Constitution Check

Passed before and after design: original scope and filing dates remain explicit; scoring never writes gold or trace inputs; arithmetic is deterministic once observed values are mapped; local outputs live under ignored `reports/`; no provider calls or cost changes. Calibration precedes any selection or independent quality claim.

## Implementation Sequence

1. Freeze pilot selection: U03 (growth/rounding), U06 (inventory accounting and omissions), U10 (risk and realized effects), U12 (segment reconciliation), U14 (historical cutoff), U16 (partial answer). Use one historical planner run for all six. Export only fields needed to judge.
2. Score each rubric item from original request, answer and reference. Then evaluate citation support separately using only the answer's attached runtime evidence. Record exact answer/source anchors. Inspect material limitations and prohibited inferences.
3. Compare observed numeric literals with reference checks using Decimal and published tolerances; accept explicitly lower precision only when correct rounding matches. Record extracted values, scope judgments and reasons. Do not invent numbers for absent checks.
4. Validate input fingerprints and item coverage, generate machine-readable scores and a Chinese review report with evidence. Add tests for missing/invalid outputs and numeric/citation edge cases. Document the replay command.
5. After human review, build calibration controls and an independently versioned judge adapter. Freeze a current-default baseline before A/B tuning. Keep retrieval recalls as diagnostics. Do not run these later steps in this pilot.

## Whole-Answer Rubric Follow-up (2026-11-05)

- Add a machine-readable rubric under `contracts/whole_answer_rubric.json` and a provider-free adapter in `src/finrag/evaluation/answer_quality.py`. Export one prompt/data envelope per answer. The prompt evaluates the original request and entire response, including substantive claims outside the mandatory facts. It distinguishes factual correctness, consistency with retrieved evidence, and support from the exact attached citation.
- Import structured whole-answer verdicts into the existing score report, using the original packet hash and the rubric fingerprint. Validate score range, reasons, exact answer/source excerpts, and the material-error cap. Summarize each dimension with its scored denominator; leave the strict pass rule and diagnostic scores in place.
- Rejudge the same six saved answers in this conversation using the explicit scale. Write a new ignored `pilot_v2` result and retain `pilot_v1`. No retrieval, generation or paid judge API calls. Treat these as calibration candidates, not independently validated scores.

## After the Pilot

- Record reviewer overrides by item ID and compare judge/human agreement by dimension. Add controlled wrong-year, wrong-unit, unsupported-citation and reasonable-partial-answer pairs before locking the judge prompt and pass rules.
- With a separate budget check, score the current serving defaults on the 20 development questions. Compare one change at a time using the same queries, generator, prompt and budgets. Report per-question wins, regressions, failed attempts, latency and cost alongside answer scores.
- Diagnose failures using traces: did the planner omit the requested fact, was evidence missing at retrieval/context selection, or was available evidence misread or left unused? A reference-context generation test can isolate some generation errors; keep that result separate from end-to-end scores.
- Reserve independent Alphabet/Amazon intents before tuning. Run the locked evaluator on that holdout only after selecting the candidate on development data.

## Project Structure

`specs/009-answer-evaluation/`: requirements, plan, data model, CLI contract, decisions, quickstart and tasks.
`src/finrag/evaluation/answers.py`: offline packet preparation, scoring and report generation.
`tests/test_answer_eval.py`: offline contract tests.
`reports/answer_eval/`: ignored pilot packets, verdicts and reports.

## Six-Question Optimization (2026-11-06)

1. Replay exact span coverage from the historical candidate pool, Top80 and actual context; use the saved dense Top80 full-table reranked context as a fixed alternative across all six. Audit plans qualitatively and keep search-scope hypotheses separate from measured stage loss.
2. Append opt-in, generic generation instructions to check the original question, preserve table labels/column periods, distinguish amount/rate/percentage-point units, state valid formulas and report only specifically missing operands. Do not replace serving defaults.
3. Run one new generation per alternative context; use original evidence for U06/U14 prompt-only probes. Pin requests and compare with the already saved original answers; do not label comparisons as same-time controls. Save attempts and usage with the existing DeepSeek ledger and stop at the existing $1.60 threshold. No new embedding, retrieval, reranker or paid judge calls.
4. Use the existing judge schemas and rubric. Report stage attribution, before/after dimension and item-level metrics, timing/cost and regressions. Leave full development rerun and rollout deferred.

## Twenty-Question Historical Baseline (2026-11-06)

Prepare all 20 historical packets, verify the original six hashes, and review the other 14 with the same five dimensions and mandatory fact, numeric, citation and boundary contracts. Save a new ignored run with judge artifacts and report both the original subset and the other questions. Recompute stage evidence coverage separately; do not substitute retrieval scores for answer quality. No new generation or paid judgment is required for this historical baseline.

## Current-Default Paired Benchmark (2026-11-07)

Use `experiments/current_baseline.py` to execute query-only inputs through the real default serving runtime, without importing reference answers. Pin source/config/query/catalog fingerprints and retain each attempt. The existing provider cache keys govern reuse; changed catalog inputs must not be forced to use old planner responses. An experiment-only budget override requires explicit user authorization and must not edit `configs/serving.json`. Stop on provider/budget failure; completed or failed attempts are not silently retried. Attach the evaluation-only corpus-scope metadata after runtime execution, then prepare offline packets and compare all 20 with the existing historical rubric. Whole-answer and item judgments remain provisional until human calibration.

## Targeted Reliability and Numeric Follow-up

1. Preserve the default baseline; inspect failed SQL with cache-only EXPLAIN probes and map numeric omissions/errors to saved needs, source rows and final evidence. Separate reproduced behavior from hypotheses.
2. Add one request-wide SQL timeout recovery slot with transaction rollback, unchanged search semantics and actual-call accounting. Keep ANN JIT disabled transaction-locally, not globally. Add one typed answer-structure repair, preserving failed model outputs.
3. Add an optional bounded arithmetic preparation call and safe Decimal expression evaluator. Literal operands require actual evidence anchors; formulas reference validated operands/results, not Python execution. Trace rejected requests and verified arithmetic. Preparation/answer inputs must fit the existing full-prompt cap. Add generic instructions to finish answerable comparisons, retain precision through arithmetic and derive trend wording from the displayed sequence.
4. Run only the six authorized cases with unchanged planning/index/retrieval/reranking bounds and explicit arithmetic activation. Exact cache hits may be reused. Use the unchanged five-dimensional rubric and numeric tolerances; keep failures in denominators and label comparisons against historical answers as descriptive. No new external data, public push, or all-20 run.

Pilot refinement: preserve the first six-case run even though all deliveries succeeded. It exposed a truncated worksheet, quoted-table formatting mismatches, signed cash-outflow operands being treated as unsigned, and an inverted turnover-days derivation. The second six-case run bounds the worksheet to 32 values/calculations, requests minimal literal quotes, normalizes only table separators/whitespace, preserves source signs and explicitly checks stock/flow versus flow/stock and cross-period net accounting effects. No company, question ID or frozen expected value is used in those rules. Both rounds consume the same authorized $2.20 stop; the calculator stays opt-in.
