# Implementation plan

1. Freeze request/tool/state/terminal contracts and a small paired evaluation set. Separate natural raw inputs, canonical development intents and original compound queries; validate provenance and scope expectations before tuning.
2. Inspect transitive serving imports and isolate evaluation/legacy LangChain dependencies. Resolve a candidate LangGraph version in a clean environment, lock the dependency set and verify imports without providers.
3. Extract typed RunState/RunPolicy and node adapters from the current orchestrator. Keep retrieval, reranker, context and generation behavior unchanged. Preserve billing guards and local trace/UI events.
4. Implement a single StateGraph with explicit routes and operation IDs. Replay stored tool/model responses to compare the old and new pipelines without paid calls. The old execute adapter remains the rollback path.
5. Test successful short paths, clarification, empty search, partial evidence, dependency failure, SQL timeout, cancellation, unresolved billing, invalid citation and budget exhaustion. No new model call on the equivalence path.
6. Add an initially disabled, one-round evidence-gap follow-up. Deduplicate search fingerprints, preserve scope and enforce shared remaining budgets. Keep generated gap judgments separate from independently labelled evidence coverage.
7. Compare feedback off/on using the same rubric, raw inputs, index/model and total budgets. Report stage losses, end-to-end answer quality, numeric/citation errors, abstention, per-case regressions and latency/cost. Price and authorize paid samples separately.

Target modules: `agent/state.py`, `agent/policy.py`, `agent/tools.py`, `agent/graph.py`, adapters around existing planner/retriever/context/answer services. Ingestion remains separate. Persistent checkpoint adapters and multi-agent expansion are deferred; no new database schema is required for the first migration.

Detailed project rationale and file mapping: `docs/rag-agent-refactor.md`. This document does not execute the plan.

## Current increment

- Relocate shared modules into `core`, `ingestion`, `retrieval`, `answering`, `providers` and `agent`. Update maintained imports, source/code registry, trace callsites and documentation; retain minimal compatibility modules only for immutable frozen builders and installed CLI entry points.
- Resolve the modern runtime in a disposable environment before changing the existing environment. Move heavy RAGAS/legacy integrations to an optional evaluation dependency group; lock runtime and full evaluation dependencies separately.
- Extract typed per-request state, a nonserialized execution context, bounded policy and stage adapters. Compile an actual LangGraph StateGraph that calls the existing functions, with no framework automatic retries/checkpointer or extra model calls.
- Verify with deterministic recorded/fake tool receipts, distinguishing orchestration tests from answer-quality scores. Add success/clarify/missing/error/budget/cancel and concurrent-state-isolation checks. Run existing offline and selected local database checks, plus safe saved-result replay where compatible. Do not start paid API calls.


## Next validation increment — planning only, 2026-11-09

Use the concise capability/data/evaluation/cost plan in `docs/rag-agent-refactor.md`. Review 12 canonical derivatives (select six for the first paired end-to-end trial), prepare 12 provenance-labelled raw inputs, and reserve eight independently labelled Alphabet/Amazon intents before tuning. Keep parent/variant/related families together; do not treat the 81 derivative rows as independent observations.

Calibrate the unchanged five-dimension rubric on six saved compact answers with new packet hashes and human review. Then, only after separate budget authorization, run the six-case current default, locate planning/search/shortlist/context/generation losses, and test one general change under matched total budgets. Preserve delivery failures in task/required-check denominators and report assertive numeric accuracy separately from coverage. Use offline labels only after runtime decisions. Raw-direct, fixed-plan and independently switched prompt/calculator controls still need explicit runner support; do not claim these arms already ran.

Only design a single database-only follow-up if missing-context evidence warrants it. Keep it off by default, distinguish unavailable disclosure from a retrievable gap, and count initial/follow-up attempts against the same total budget. Persistent recovery, multi-agent roles, predictions and valuation remain deferred. No paid execution, new dataset generation, runtime changes or GitHub publication is authorized by this planning increment.


## Execution-policy consolidation design — 2026-11-09, not implemented

Extend the current RunPolicy/RunControl and sole persistent Budget ledger rather than introducing a second orchestrator or monetary ledger. Define stage-local repair limits under global node/SQL/LLM/provider-call, cost and remaining-time bounds; distinguish logical calls, cache hits, paid attempts, schema repair, transport retry and semantic follow-up. Unknown billing retains its reservation and never triggers a blind retry or supplier fallback. Reserve answer headroom before optional reranking expense.

Propagate remaining time/cancellation through serial retrieval/provider loops and the API adapter; browser disconnection currently stops event delivery but does not cancel the paid worker. Capture failures before graph invocation as typed run artifacts. Define visible, scope-preserving degradation before implementing it; never deliver malformed model fragments or relabel dependency failure as missing corpus evidence. Keep evidence follow-up off until a separately matched comparison supports it.

Test normal/clarify/empty/partial/error/budget/deadline/cancellation and concurrent isolation using fault injection and fixed receipts first. No runtime settings, tool defaults or retries are changed by this design-only update. The local independent-review originals contain machine links and remain excluded from publication.


## Final plan alignment

Follow docs/rag-agent-refactor.md for boundary distinctions, explicit clarification continuations, local-first observability, global attempt/budget ownership and planned fault injection. The existing retrieve/clarify/insufficient Plan contract needs a compatible design for the more detailed disposition/reason model; this documentation update does not modify that contract or enable new runtime routes.

## Execution-control implementation

1. Extend RunPolicy/RunControl with provider/search/repair/recovery accounting, remaining time and cleanup hooks. Keep one monetary ledger; add atomic answer holds and optional batch scope to its existing reservations.
2. Start lifecycle before resources; inject it into the graph, record setup/finalization, preserve typed policy failures and evidence-only delivery. Keep sequential reference as an explicitly limited migration control, not a policy bypass for service requests.
3. Gate cache/embedding/retrieval/repair loops; clamp HTTP, connection and SQL timeouts to remaining time. Explicitly disabled connect-only retry may be opted in; never retry unknown billing.
4. Connect API disconnect/cancel events and keep workers/admission alive until cleanup. Align the evaluation runner with public request lifecycle and remove its separate signal-based per-model deadline from the active path.
5. Add offline/fault tests for all ceilings, headroom conversion/release, concurrent/batch ledgers, late known/unknown responses, cancellation, setup errors, safe fallback and parity. Update source maps, configuration and docs; no paid tests or live corpus mutation.
