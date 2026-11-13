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


## Finalized boundary and execution design — 2026-11-09

FR-011/012 remain planned. FR-013/014 control plumbing is implemented by the authorized increment below; semantic behavior and quality still require evaluation.

- FR-011: Preserve distinct dispositions/reasons for material ambiguity, unrelated tasks, unsupported financial capabilities, missing corpus material, insufficient disclosure and mixed supported/unsupported requests. Do not infer missing scope, expand tool permissions, refuse supported portions, or mislabel dependency failures as corpus absence. Reuse the bounded planner for classification where possible rather than adding an unconditional extra model router.
- FR-012: End clarification as an explicit run; a subsequent user-provided confirmation forms a separately validated request linked to the original run. No hidden gold mapping supplies that confirmation and no persistent memory platform is required by this increment. Test first-turn routing and post-confirmation recovery separately.
- FR-013: Consolidate existing repair/retry/global limits, propagate remaining deadlines and cancellation, preserve unknown reservations and answer headroom, and expose graph-external resource failures. A fallback must be visible and preserve source/scope/context limits. Do not enable rerank degradation or semantic follow-up merely because a plan describes them.
- FR-014: Link execution outcomes and attempts to the shared evaluation contract. Fault-injected and replayed runs establish control correctness only; measured answer quality, scope robustness and operational throughput require separate appropriate datasets and execution. Optional tracing-platform failures never authorize retries or change budget state.

## Authorized execution-control implementation — 2026-11-09

- FR-015: Create request policy/trace before resource setup; share the same control through CLI/API/engine and persist graph-external failures, elapsed scope, typed outcomes and sanitized evidence-only fallback. Never return rejected/late model answers as verified delivery.
- FR-016: Enforce shared node, LLM, provider-attempt, schema-repair, search-attempt and SQL-recovery limits. Cached work is not a new provider request. Transport retries are disabled by default; an explicitly enabled connect-only retry must first settle the demonstrably unsubmitted reservation to zero. Unknown submission/billing is never retried.
- FR-017: Reserve answer headroom in the sole persistent ledger before non-answer provider work, atomically exchange that hold for the answer call, and release only unused policy holds on exit. Keep actual uncertain provider reservations. Enforce cumulative, optional batch and per-request ceilings atomically without nested ledgers or budget resets.
- FR-018: Use a monotonic request deadline across stages, cache/SQL/batch loops and provider timeout arguments. Stop new actions after cancellation; drain and settle already submitted responses when known. Provider/SQL native timeouts bound in-flight blocking; cancellation does not promise refunds or instantaneous hard interruption.
- FR-019: Wire stream disconnect and explicit local cancellation to request-local events, preserve admission until real worker completion and release resources on every exit. Distinguish policy termination from corpus insufficiency. Make source-only fallback visibly unverified and preserve the failure outcome.

Authorization: implement and validate with offline receipts, MockTransport, cancellation events, fake clocks and SQL fault injection. No paid requests are authorized. Keep planner/model/retrieval/reranker/context semantics and cumulative stop unchanged; engineering policy defaults may be explicitly configured and documented. No production throughput or new financial-quality claim follows from these tests.
