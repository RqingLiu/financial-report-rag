<!--
Sync Impact Report
2026-10-26: 1.0.0 -> 1.0.1 status-only baseline correction; core principles unchanged.
Version: template -> 1.0.0 (initial adoption, 2026-10-25).
Principles: source/period integrity; evidence-based evaluation; bounded changes;
deterministic operations; simple reproducible engineering.
Added: baseline, document ownership, workflow, governance.
Removed: unused examples and placeholder rules.
Templates: spec-template.md, plan-template.md, tasks-template.md updated.
Installed skills retained upstream; no extension hooks installed.
Runtime guidance: AGENTS.md and README.md updated.
Deferred placeholders: none; existing features are not retrospectively specified.
-->
# Financial Report RAG Constitution

## Core Principles

### I. Verifiable sources and periods

Facts, passages and tables must retain company, document/accession, actual period, filing time and source location.
Treat report FY and fact period separately; `filed_at <= as_of` constrains disclosure availability.
Rewriting must preserve confirmed companies, periods, exclusions and comparison scope.
Clarify material ambiguity. Report missing material rather than guessing numbers, mixing versions or silently loosening filters.

### II. Claims require evidence

Distinguish implemented behavior, design drafts and validated results. Recall@k measures evidence coverage, not answer accuracy.
Do not overwrite/delete frozen data, release markers or results to select new features.
Record data/config/code version, splits, scoring and cost for each evaluation. Keep an intent and its variants in one split.
Gold/reference answers must not enter runtime queries, indexes or tools. Mocks do not establish real retrieval or financial-analysis quality.

### III. Bounded specifications

Before new features or behavior changes, define goals, scope, non-goals, compatibility, requirement IDs and acceptance criteria.
Update the spec before semantic changes, then check design/tasks/validation. Do not merely change code or weaken assertions to hide differences.
Resolve conflicts using user intent and record the impact; routine implementation choices remain within authorized scope.
Installing development tools does not authorize all proposed features. Historical code does not need complete retrospective specifications.

### IV. Explicit calculation and execution permissions

Check metric, unit, currency, period and accounting basis before financial arithmetic; use deterministic code and retain sources/formulas.
Separate LLM explanations, user assumptions and scenarios from filed facts.
Use controlled database parameters; model output cannot grant arbitrary SQL, shell or code execution.
Plans may choose only declared available capabilities. Bound query variants, subtasks, follow-ups, calls and spending.
Report unavailable tools and service errors explicitly; never claim unperformed execution or retry indefinitely.

### V. A small, reproducible project

Reuse Python CLI/service, PostgreSQL + pgvector, metadata and provenance.
One coordinating agent is the future default; retrieval, planning, skills and calculators are not automatically separate agents.
Add services, databases, queues, frameworks or subagents only for a concrete requirement.
Record actual models/prompts/configuration/dependencies. Keep secrets in ignored local configuration.
Test affected behavior and outcomes; do not add implementation-mirroring tests for documentation or low-impact edits.

## Current Baseline and Document Ownership

README, code, configuration and tests describe current implementation. The original baseline includes SEC HTML acquisition, parsing, chunking, Voyage embeddings, hybrid retrieval, evidence export and frozen evaluation, with rule-based filters and fixed Chinese/English term expansion.
On 2026-10-26 an explicit experimental path added metadata-catalog QueryPlan, bounded retrieval/source-table assembly, online need-level generation and local traces; retain the old path for replay. On 2026-10-27 an isolated serving path added atomic document ingestion, database catalog, ANN/BM25, reranking integrated with generation and a localhost API. Evidence-objective planning and CrossEncoder remain optional. Financial facts, deterministic calculation, forecasting/valuation, autonomous agent loops, independent semantic acceptance and production-load acceptance remain future work.

- Notion holds the overall roadmap, research and technical diagrams; do not copy the full plan into the repository.
- README describes current code; this constitution governs development; feature `spec.md` defines execution requirements.
- `plan.md` records design and `tasks.md` tracks delivery. Notion proposals become commitments only when included in a feature's scope.
- Latest user instructions take precedence. Record/resolve source conflicts; planning text is not proof of implementation.

Sources: [Notion v0.9 sections 5.3, 5.4, 6, 7, read 2026-10-25](https://app.notion.com/p/Agent-3f6fda5b0ede808b9b60cee10e298cee), and historical README sections 5, 8, 9, 10.

## Development Workflow and Quality Gates

1. Start with one reviewable change and record specification/compatibility; clarify when necessary.
2. Check the constitution, reuse actual modules, and distinguish current implementation from future dependencies.
3. Map tasks to requirement IDs and verification. Check spec/plan/tasks consistency before implementation.
4. Run appropriate offline/contract checks. State database and paid-API dependencies/costs.
5. Deliver implementation, evidence and remaining work. Freeze release tests; create separate versions for later selection.
6. Treat feature specifications as living contracts: preserve Git history and synchronize downstream design/tasks/validation.

## Governance

Semantic versioning: removed/incompatible principles require a major version; new constraints a minor version; wording clarification a patch.
Explain changes and migration needs, updating related templates/documents without adding a separate approval platform.
Record significant departures with reasons/alternatives/verification.
Tool versions are recorded in `.specify/integration.json`; review template/skill changes on upgrade and preserve project customizations.

**Version**: 1.0.1 | **Ratified**: 2026-10-25 | **Last Amended**: 2026-10-26
