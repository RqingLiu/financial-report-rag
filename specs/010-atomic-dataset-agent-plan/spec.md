# Atomic Development Dataset and RAG Agent Migration Design

Date: 2026-11-07. Scope: reconstruct the 20 compound development questions and design, rather than implement, the next runtime migration.

## Requirements

- FR-001: Preserve Golden v2, reviewed parent references, numeric tolerances and historical runs byte for byte. Create a versioned child dataset with parent/family provenance and no new claim of independent test data or renewed human approval.
- FR-002: Split by independently assessable intent, not punctuation, fiscal year or individual table cell. Keep legitimate multi-year/multi-company comparisons. Every child must be standalone, with explicit company, report years, cutoff and inherited confirmations.
- FR-003: Give each child its own reference answer, mandatory facts, boundaries, source evidence groups and relevant numeric checks. Do not copy all parent requirements into every child. Allow synthesis children to depend on supporting child intents for evaluation only; never give these gold dependencies to the runtime.
- FR-004: Audit parent coverage: account for all parent facts, evidence groups and numeric-check occurrences through explicit inheritance or documented de-scoping. Preserve approved source values; any rewritten reference or new answer boundary is agent-curated and pending review.
- FR-005: Export query-only input separately from judge data and provide Question-compatible retrieval labels and RAGAS-compatible records. Support child IDs in offline answer-packet preparation without changing old scores, tolerances or path safety.
- FR-006: Describe separate retrieval-only, planner-plus-retrieval, end-to-end and original-compound-suite protocols. Do not compare new and old aggregate percentages as a measured model improvement. Group all derivatives of an intent/family in the same split; report parent-balanced results and shared numeric-check duplication.
- FR-007: Audit current orchestration, error handling, budget ownership and module responsibilities. Plan one coordinating RAG agent using explicit typed state, bounded decisions, reusable retrieval tools and shared billing controls. Explain framework selection using current primary documentation and current dependency constraints.
- FR-008: Specify migration stages, target file responsibilities, compatibility/rollback and measurable acceptance checks. Do not install a framework, move/delete working modules, change live retrieval defaults, start paid evaluation or publish repository changes in this task.

## Acceptance

All 20 parents have mapped children, each child has a scoped answer/rubric and traceable evidence. Parent constraints/checks are accounted for. Rebuilding/checking the artifact is deterministic and offline; v2 hashes remain unchanged. Tests cover scoping, leakage, parent accounting and child-ID packet preparation. The runtime proposal separates implemented controls from planned controls and keeps accounting correctness distinct from orchestration.
