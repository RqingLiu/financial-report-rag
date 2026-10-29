# Public validation receipts

- `release_validation.json`: correctness/clean-checkout tests, preserved original corpus, new document counts, actual scoped ANN plumbing checks and cost summary.
- `generalization_sources.json`: six Alphabet/Amazon source URLs, filing dates, hashes and parsed/chunk statistics.

The live smoke check stops before answer generation and is not a held-out evaluation. Numeric/semantic answer quality for the new companies remains unmeasured. A failed planner smoke before the schema-feedback fix is explicitly recorded rather than dropped.

Large local traces, paid responses, model messages, machine-specific audits and caches are excluded from this public tree. Existing development retrieval results and their conditions are documented in [evaluation.md](../../docs/evaluation.md).
