# Implementation Plan

1. Inspect the frozen query/reference/label/numeric sources and current serving runtime. Choose one independently assessable intent per child; retain the compound parent suite for decomposition tests.
2. Author editable split specifications under `data/evaluation/golden_v3/`. Each row binds explicit reference paragraphs/table projections or carefully rewritten text to parent fact IDs, evidence-group indexes, numeric IDs and scoped boundaries. Reuse reviewed values and exact evidence alternatives; flag new labels as a curated draft.
3. Build query-only, retrieval, judge, RAGAS, source-catalog and lineage exports through `scripts/build_golden_v3.py`. Validate parent accounting and semantic scope, then record artifact/input hashes. No database or provider calls.
4. Extend only offline packet preparation to recognize safe child IDs and escaped reference headings. Preserve prior packet/evaluation behavior. Test fixtures should catch accidental whole-parent inheritance, answer leakage and lost parent constraints.
5. Write the layered evaluation protocol and `docs/rag-agent-refactor.md`. Compare a typed Python controller, LangGraph and Deep Agents; recommend a bounded graph only after dependency and replay tests. Preserve the existing FastAPI, PostgreSQL/pgvector, provider adapters and shared cost ledger.
6. Update documentation navigation, verify the draft and frozen v2 read-only checks, and report what was created versus what is only planned. Framework migration, a new paid baseline and dataset freezing are separate follow-ups.

Constitution: preserved source/date integrity, no gold in runtime input, no new services or uncontrolled loops, no raised spending stop. Child label review is not silently inherited from parent approval.


## Data-review preparation

1. Choose a purposive 12-intent development sample covering source lookup, multi-year numeric comparisons, cross-period accounting, historical disclosure limits, cross-company comparison and unavailable disclosures.
2. Verify selected references and supplemental source locators against local raw HTML/canonical blocks; recompute the applicable deterministic numeric checks. Flag overbroad inherited evidence/rubric requirements without rewriting the parent release or the 81-case draft.
3. Author four colloquial, three exclusion/cutoff, three ambiguity and two unavailable-disclosure mock cases. Keep known input scope separate from latent intended mappings, expected routes and future clarification requirements.
4. Write only a review document, machine-readable offline labels and query-only JSONL under a purpose-named pilot directory. Validate counts, source/cutoff integrity, query schema, lineage and original-data immutability without providers. Human approval, promotion and any paid evaluation remain pending.

## Accepted pilot export — 2026-11-09

Apply the user's acceptance to a purpose-named pilot bundle compatible with existing saved-answer preparation. Preserve the original review packet so the independent reviewer input hashes remain valid. Reconcile corrected references, scoped facts, alternative evidence groups, numeric comparisons and source provenance; add six policy-approved synthetic boundary cases and three explicitly scripted clarification continuations. Keep newly authored wording marked as such and all data in development families. The export and its validation must not invoke providers or the database.
