# Evaluation evidence and limits

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

Detailed local trace/HTML/paid-response files are excluded from the public repository. Compact public receipts live in `reports/public/`; experiment implementations and configs remain in source for reproduction after rebuilding the corpus. Old failed pilots were preserved in compressed local archives rather than erased from the narrative.
