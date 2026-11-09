# Evaluation evidence and limits

The [atomic v3 draft](../data/evaluation/golden_v3/README.md) separates the 20 compound questions into 81 independently assessable intents, with scoped references and labels. All remain development data. Use its R0/R1/R2/R3 protocols to distinguish retrieval-only, planner-plus-retrieval, end-to-end and original-compound evaluation. Old aggregate scores below retain their original datasets and denominators; they are not v3 baseline results.

## Data contract

The current complex-question dataset has **20 development queries,225 required evidence groups and123 numeric checks**. Questions and revised references were reviewed during development; this is not an independent held-out benchmark. Same-intent oral variants remain in the same development split. The older60-question v1 evaluation is frozen and uses a different task mix.

- `data/evaluation/golden_v2/retrieval_queries.jsonl`: query-only input, including original background/cutoff. No gold evidence goes to the runtime.
- `golden.jsonl`: mandatory evidence groups, with AND across groups and OR across alternative excerpts.
- `rubrics.jsonl` and `numeric_checks.jsonl`: facts, boundaries, formula inputs, periods and tolerances.
- `reference_answers.md` and `evidence_catalog.jsonl`: human-readable reference/source audit material.

Span-based group recall measures whether mandatory source text was recovered; macro averages per question, micro counts groups. Candidate recall, Top80 recall and final-context recall describe different pipeline stages. They are not answer accuracy. Labels do not exhaustively judge all chunks, so unlabelled chunks cannot automatically be counted as irrelevant for Precision/nDCG.

## Historical controlled development comparison

The [experiment guide](experiments.md) covers v1 selection, context/rerank/focused-query studies and ANN conditions. [Public exports](../reports/public/experiments/README.md) include source hashes and per-question counts; `python scripts/verify_public_evidence.py` recomputes aggregate arithmetic without raw paid traces or DB credentials.

| Planner / coarse retrieval | Reranker | Candidate macro recall | Top80 recall | Final-context recall |
| --- | --- | ---: | ---: | ---: |
| Original dense | LLM | 94.47% | 80.95% | 67.66% |
| Dense + BM25 replacement | LLM | 94.77% | 83.87% | 71.53% |
| Evidence-objective regroup | LLM | 95.62% | 79.19% | 67.62% |
| Original dense | CrossEncoder | 94.47% | 80.95% | 59.20% |

Same development questions, selected chunks, Top20 per SQL job, Top80 reranking and matched context budgets;342 SQL jobs per arm. Controls reused saved plans/candidates and some paid reranker results. These are primarily exact-search, saved-plan comparisons, not20 independent cold end-to-end HNSW production requests. The best development arm was not automatically promoted: current serving remains dense+LLM. The separate69.81% focused-query result used a different experiment and should not be mixed into this table.

The diagnostic lesson is candidate→shortlist→context loss: changing only embedding/chunking is not justified when the full pool already contains most mandatory evidence. More complex planning also needs a coarse-rank allocation strategy; greater pool recall alone did not improve final context.

## ANN and engineering checks

The historical2,759-chunk corpus had59 scoped queries with mean HNSW/exact Top20 overlap98.98%, with actual index-plan checks. The later10k/30k/100k expansion used locally perturbed vectors, not new financial documents. Strong synthetic clusters caused an HNSW construction pathology. It demonstrates distribution/parameter sensitivity, not real financial-corpus recall or RPS. Large synthetic fixture tables were removed; recipes/results remain local.

The correctness update adds company-alias/FY counterexamples, typed confirmations, short/fat table preservation, pre-embedding conflict checks and exact reproduction of the original selected chunks. Its historical local DB-backed suite passed87 tests and clean-checkout Linux CI passed76 with11 skips; these receipts are preserved rather than overwritten. The newer guide/UI release passed101 local DB/corpus tests; see [current validation](../reports/public/project_guide_validation.json). DB tests require `FINRAG_INTEGRATION=1`.

## Still required before a quality claim

1. New natural questions and new intents from Alphabet/Amazon; reserve an unseen holdout before tuning.
2. Check scope/need decomposition, factual completeness, actual-value FY, units, numeric/formula accuracy and claim-level citation support.
3. Review no-answer/partial-answer behavior; a citation ID existing is not proof that the cited text supports the claim.
4. Compare cold/warm end-to-end latency/cost; test provider/SQL failures and concurrent publication/query behavior. No production p95/RPS claim is made.

RAGAS schemas and ID-based metrics assist evaluation. RAGAS question generation or an LLM judge has not independently certified this project. Current numeric checks verify reference arithmetic; they are not a production financial calculator.

## Offline answer-scoring pilot

The [answer evaluation specification](../specs/009-answer-evaluation/spec.md) and [replay guide](../specs/009-answer-evaluation/quickstart.md) describe the six-answer development pilot. An offline evaluator imports provisional judge judgments, checks excerpts against the saved answer and its citations, and compares mapped numeric observations with the frozen checks. A judge still identifies the metric, period and scope in free text; the numeric comparison itself is deterministic. Citation support is assessed for rubric facts, not every sentence in the answer.

The pilot uses historical traces and costs no API calls. A later current-default development run is described below. Human calibration and an independent holdout remain pending. Retrieval recall remains useful for locating evidence loss; answer scores determine whether a change improved the result.

The [whole-answer rubric](../specs/009-answer-evaluation/contracts/whole_answer_rubric.json) adds explicit 1–5 anchors for completeness, truthfulness, faithfulness, relevance and clarity. `export-judge` prepares reusable prompts; `score` imports reasoned verdicts without calling a model. Keep the five scores separate and use item-level checks to locate errors. An answer can be faithful to its context while citing the wrong excerpt, or truthful but incomplete.

Detailed local trace/HTML/paid-response files are excluded from the public repository. Compact public receipts live in `reports/public/`. Retired experimental drivers and the archive have been removed; historical results document their original conditions. Current runtime evaluation remains available through `python -m finrag.evaluation`.

## Current-default answer baseline (2026-11-07)

`python -m finrag.evaluation run --out reports/answer_eval/<new-run>` executes the same 20 query-only requests through the actual serving runtime. It preserves exact cache behavior, configuration/source fingerprints and individual attempts. Resume skips saved attempts, including failures; it does not rebill them. The optional `--stop-usd` overrides only this experiment's cumulative ledger stop and requires explicit budget authorization. Serving defaults are unchanged.

All 20 were attempted: **17 delivered answers, two SQL timeouts and one answer-schema rejection**. Newly estimated peak-list cost was **$0.4773**, within the authorized $2.20 cumulative stop. Document vectors were reused; the current catalog changed planner inputs, so historical planner/rerank caches did not match this run.

Using the same rubric on the same 17 delivered questions, completeness rose **2.71→3.41/5**, while truthfulness remained **3.53/5**. Numeric passes rose only **40/108→42/108**. Across all 20 attempts, including failed deliveries, numeric passes fell **50/147→42/147**. These are required-check coverage rates, not the accuracy of every number in the answer. Missing and failed answers remain in the denominator. Historical versus current comparisons are descriptive, not concurrent single-variable A/B tests.

U11 is the largest numeric regression: the answer had source values but omitted all requested absolute-growth calculations, reducing passes from 15 to zero. Other failures include a wrong trend summary, calculation after premature rounding, and calendar-year versus report-FY confusion. Better evidence coverage alone did not solve those generation errors. Provisional item and whole-answer judgments, exact excerpts and paired comparisons are saved locally under `reports/answer_eval/current_default_20/`; human calibration is still required.

## Six-case reliability and arithmetic follow-up

Only U01/U02/U04/U06/U11/U15 were rerun, twice, retaining both rounds. Both delivered 6/6 answers versus 3/6 in the default control; answer-structure repair was exercised on U15. The original SQL timeout was not reproduced in read-only hot-cache probes. A real PostgreSQL timeout injection verified rollback and one bounded recovery, not the original root cause.

The second arithmetic candidate used identical plans and evidence for U04/U06/U11. Numeric passes were U11 **0→17/20**, U04 **3→0/9**, U06 **1→3/16**. Across all six, including the three recovered deliveries, required numeric passes were **4→46/84**. That aggregate is strongly affected by delivery recovery and must not be described as uniform semantic improvement. U04 developed a new growth-rate summary error; U06 still confused cross-period accounting effects and an unsupported zero value. The first round also exposed a truncated worksheet and an inverted turnover-days derivation.

Default changes are limited to bounded SQL recovery/diagnostics and one answer-contract repair. The arithmetic tool and experimental generation prompt remain explicitly opt-in. Source-literal checks plus correct Decimal arithmetic do not prove financial operand/formula selection. No company or question-specific rules were introduced. Full local verdicts and paired controls are in `reports/answer_eval/targeted_fix_v2/`; frozen Golden values/tolerances and the original 20-question report were not changed.

## Raw query and rewrite evaluation

The 81 derived questions are **canonical intent cases**. They can exercise planner code and test scope/intent preservation, but already name companies, fiscal years and tasks clearly. Their scores cannot establish that rewriting improves real user input. The original 20 compound requests test decomposition and budget allocation; they are also curated development material, not organic production-query logs.

Maintain three linked views rather than replacing one dataset with another:

| View | Input | What it measures |
| --- | --- | --- |
| Canonical intent cases | One explicit task with local references/rubric | Controlled retrieval, context and answer failures |
| Raw-query paired cases (not yet built) | Human-written or clearly labelled mock input; trusted conversation context when applicable | Rewrite, ambiguity handling, constraint preservation and downstream utility |
| Original compound suite | Complete multi-intent request; child mapping used offline only | Task decomposition, shared budgets and end-to-end completeness |

For each raw case record `id`, provenance (`human_authored` / `synthetic_mock`), raw question, supplied context, disclosure cutoff, related intent/family, accepted intents and constraints, expected route (direct/rewrite/clarify/out_of_scope), and review status. Labels and canonical targets stay in judge-only files. A vague request can legitimately require clarification; do not invent a year/company merely to score retrieval. Any follow-up turn and user confirmation are separate recorded inputs.

Start with a small balanced set covering clear questions, colloquial references/paraphrases, exclusions/negative constraints, ambiguous company/year references, and genuinely unavailable material. Mock cases are useful development tests, but need their own label and cannot be claimed as user observations. Keep variants, parent questions and overlapping intent families in the same split. New Alphabet/Amazon intents can supply a holdout only if reserved before tuning; paraphrasing a tuned intent does not create one.

Run paired controls with the same index, company/date access scope, model, total SQL attempts, candidate/context caps and answer rubric:

1. **Raw direct:** retrieve using the raw query with only application-validated scope; no oracle child queries.
2. **Current planner:** the same request through current rewrite/decomposition and retrieval.
3. **Proposed agent:** only after equivalence migration, compare bounded feedback disabled/enabled on the same requests.

A fixed canonical-search-plan oracle is a diagnostic upper control, not an online baseline. Original+rewritten parallel search must share the same total search budget, rather than doubling it. Stratify cases needing clarification instead of forcing an arbitrary interpretation into a recall denominator.

Score intent coverage, unsupported intent additions, company/FY/as-of/exclusion preservation, and clarification correctness. Then compare candidate/context evidence recall and the unchanged answer rubric: completeness, truthfulness, faithfulness, relevance, clarity, numeric checks and citation support. Report regressions and cost/latency per case. Do not grade rewrite wording by exact string match or infer semantic quality solely from evidence recall. No raw-query robustness score or new paid evaluation was produced in this cleanup.

The full historical archive has been deleted. Compact answers/evidence and comparisons remain under `reports/current/`; old large-run paths cannot be restored. See [current result navigation](../reports/README.md).
