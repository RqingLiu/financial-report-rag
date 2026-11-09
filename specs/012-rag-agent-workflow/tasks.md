# Tasks

- [x] Review the current orchestrator and course chapters 10/11.
- [x] Specify a single-agent scope, state/tool contracts, routes, limits, evaluation and rollback.
- [x] Review existing contracts for the user-authorized equivalent migration.
- [ ] Collect/review raw-query provenance and labels before adding/tuning new agent behavior.
- [x] Isolate dependencies; validate and lock a compatible LangGraph environment.
- [x] Extract state/policy and wrap current tools without changing stage behavior.
- [x] Implement and replay the equivalent StateGraph; preserve API/CLI/local trace.
- [x] Add routing, termination, failure, scope and billing regressions.
- [ ] Implement one bounded follow-up behind a disabled configuration flag.
- [ ] Estimate and authorize a matched small-sample comparison; review improvements and regressions.
- [ ] Decide promotion using end-to-end quality and operational checks, then plan holdout evaluation.

Authorized increment 2026-11-08 implemented the equivalent graph and source layering in an isolated verified environment. The original environment was not replaced. No paid model run, semantic-quality claim or feedback promotion occurred.

Validation (2026-11-08): 136 offline tests passed, with eight opt-in/corpus skips after adding the new database parity test. Seven active PostgreSQL contracts passed, including actual SQL/context parity with fixed model receipts. Eleven graph contracts cover equivalence, finite routes, typed errors, model/node/cost limits, cancellation and concurrent request isolation. No paid financial model APIs or corpus re-ingestion were used. Frozen v2 checks and deterministic v3 checks passed; only the unfrozen v3 builder provenance changed for relocated imports. Runtime and full evaluation locks contain 57 and 106 distributions. The original .venv was retained; .venv-migrate is the verified execution environment.
