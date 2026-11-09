# Bounded single-agent RAG workflow

Status: equivalent StateGraph migration implemented on 2026-11-08; evidence-driven follow-up, persistent recovery and paid quality comparison remain pending.

## Problem and course basis

The current `serving.runtime.execute` already orchestrates planning, retrieval, context and generation. The missing boundary is a common typed state and policy for conditional clarification, evidence inspection, limited follow-up and terminal outcomes. Course chapter 10 motivates State / Decision / Action and constrained execution; chapter 11 motivates original-query preservation, retriever contracts, source-preserving context processing and evidence-aware responses. Teaching examples and fake components are not evaluation evidence.

## Requirements

- FR-001: Preserve the raw user query, trusted confirmations, disclosure cutoff and catalog scope separately from rewritten search queries. Never infer a material missing entity or period merely to make a query concrete.
- FR-002: Use one coordinating agent with finite routes: clarify, plan, retrieve, context, inspect evidence, optional follow-up, optional typed calculation, answer, validate and deliver. Stable steps remain deterministic functions. No supervisor or subagents in this feature.
- FR-003: Treat retrieval/reranking/calculation as constrained tools. Validate arguments, enforce server-side scope and preserve chunk IDs, original source offsets, filing identity, actual fact periods and units where available. Tool errors must not become successful empty results.
- FR-004: Use typed RunState, ToolResult and RunPolicy. Separate single-run state from conversation history and long-term memory. Trace node inputs/outputs, operation IDs, decisions, usage and failures without secrets, connection objects or internal reasoning transcripts.
- FR-005: Retain the shared persistent billing ledger as the only monetary authority. All graph nodes inherit the same remaining request/cumulative budgets. Enforce deadlines, SQL/model call counts and context caps before executing tools. Unknown billing is not automatically retried.
- FR-006: Preserve current stage behavior and budgets in the first graph migration. Support at most one source-gap-driven follow-up only in a later, separately compared step. Count recovery attempts and follow-up against the same total limits; prevent repeated search plans and scope expansion.
- FR-007: Context selection must retain original-source mappings and financial qualifiers. Start with the existing extractive context; do not add abstractive summaries as part of the framework migration.
- FR-008: Return typed outcomes for success, partial answer, clarification, insufficient material, dependency failure, budget exhaustion and cancellation. Citation validity is separate from semantic support; uncalibrated self-reported confidence is not a probability of correctness.
- FR-009: Use LangGraph StateGraph after dependency isolation and version-lock validation. Retain existing services and API response adaptation. Do not install incompatible packages by upgrading the entire current environment in place.
- FR-010: Evaluate canonical intent cases, raw-query paired cases and compound requests separately. Keep human-authored and synthetic provenance, related intent families in one split, and offline gold out of runtime state. Compare quality, regressions, latency and cost under matched budgets.

## Non-goals

Persistent checkpoint infrastructure, long-term memory, multi-agent collaboration, arbitrary SQL/code tools, predictions, valuation, new embeddings, index rebuilding or default retrieval-algorithm changes. Financial typed calculators require a separate operand/period/unit specification; the current experimental expression tool remains opt-in.

## Acceptance

Equivalent cached/replayed old and new runs preserve plans, source-context identities and prompts without extra provider calls. All routes terminate under documented limits. Raw-query tests check intent/constraint preservation and clarification behavior rather than string matching. At most one follow-up runs, repeated plans stop, and failures remain visible. API/CLI share one engine; old research schemas and gold labels are never read. No score improvement is claimed without paired real-service evaluation and review of per-case regressions.

## Authorized implementation increment — 2026-11-08

Implement preparation and equivalent LangGraph migration now, including a responsibility-based source layout and updated bilingual README/file-linked diagrams. Preserve reviewed data, model prompts, query-plan semantics, retrieval defaults and existing API statuses. New internal typed terminal outcomes may be exposed as additive agent metadata. Existing provider ledgers and timeouts remain authoritative; graph node limits and optional request policy guards must not introduce blind retries. Keep trusted resources outside serializable state and expose sanitized node state summaries in traces.

This increment does not enable evidence-driven re-querying, a new semantic judge, financial tools by default, persistent checkpoints, or paid answer experiments. User-provided natural-query collection and the later feedback comparison do not block the behavior-preserving graph migration. Preserve a sequential reference adapter for offline parity checks/rollback until validated.
