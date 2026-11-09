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
