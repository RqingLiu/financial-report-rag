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


2026-11-09 planning review: checked the actual graph, node gate, optional policies, evaluator and course chapters 10/11. Added a compact current-capability and next-evaluation plan to `docs/rag-agent-refactor.md`, including data review, family-aware splits, rubric calibration, stage attribution, cost assumptions and later authorization. This is documentation only; outstanding data, semantic-gate and paid-comparison tasks above remain unchecked.


2026-11-09 data preparation: the 12 canonical reviews and 12 provenance-labelled synthetic raw-input cases are available under data/evaluation/pilot_review. Human approval is pending, so the raw-query review gate above remains open. No paid run, semantic gate or follow-up loop was added.


Execution-policy tasks (implemented offline, 2026-11-09):
- [x] Centralize accounting for stage attempts, provider calls and existing SQL/model/node limits without nested retry multiplication.
- [x] Preflight cumulative/request/batch ceilings including unresolved reservations and answer headroom.
- [x] Propagate request deadlines and client cancellation to future tool calls; capture graph-external failures.
- [x] Define and fault-test visible fallback outcomes without relaxing provenance or returning invalid answers.

The independent pilot review was read and its 62 quoted locations checked against local sources. Review comments do not authorize paid execution or certify current pipeline behavior.


Finalized scope (2026-11-09): behavior-specific out-of-domain/capability/corpus/ambiguity handling and clarification continuations are part of the next design. Integrate their tests with the evaluation contract before paid trials. The current runtime, automatic follow-up and cloud tracing settings remain unchanged.

Authorized execution increment:
- [x] Implement the shared policy/accounting and persistent answer/batch reservations.
- [x] Gate provider/search/repair loops with remaining time and cancellation.
- [x] Capture full request lifecycle, resource failures and evidence-only fallback.
- [x] Connect local API cancellation and align evaluation lifecycle.
- [x] Verify offline/fault contracts and document actual limits without paid calls.

Execution-control implementation was authorized and completed with offline fault tests. No paid calls, provider promotion, semantic follow-up, new quality scores, or cumulative-budget changes. Active defaults and limitations are documented in docs/rag-agent-refactor.md §6.

Final validation for this increment: 33 new fault-injection contracts; complete offline suite 149 passed, 7 opt-in DB skips. Ruff and diff checks passed. Working-tree publication-pattern scan: 261 files, zero findings. No API fees, DB mutation, Git commit or push.
