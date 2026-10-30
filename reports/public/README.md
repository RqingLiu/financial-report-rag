# Public validation receipts

- [Project guide release](project_guide_validation.json): current local101-test validation, frozen dataset check, source/artifact checks and publication boundaries.
- [Experiment evidence](experiments/README.md): source-hashed historical aggregates and per-question results;27 v2 arms recomputed without credentials.

- `release_validation.json`: correctness/clean-checkout tests, preserved original corpus, new document counts, actual scoped ANN plumbing checks and cost summary.
- `generalization_sources.json`: six Alphabet/Amazon source URLs, filing dates, hashes and parsed/chunk statistics.
- `trace_explorer_validation.json`: local UI/streaming contracts, browser checks and one bounded live full-query smoke.

The release smoke in `release_validation.json` stops before answer generation. The later trace-explorer smoke includes generation and checks citation-ID/output structure only. Neither is a held-out evaluation; numeric/semantic answer quality for the new companies remains unmeasured. A failed planner smoke before the schema-feedback fix is explicitly recorded rather than dropped.

Large local traces, paid responses, model messages, machine-specific audits and caches are excluded from this public tree. Existing development retrieval results and their conditions are documented in [evaluation.md](../../docs/evaluation.md).
