# Feature Specification: Query Understanding and Retrieval Planning

**Feature Directory**: `specs/001-query-planning`
**Created**: 2026-10-25
**Status**: Implemented as an experimental path. The 20-question development run is complete; semantic/numeric acceptance and an independent holdout remain pending.
**Input**: Convert Chinese, colloquial wording, aliases, follow-ups and compound questions into retrieval plans that preserve constraints. Reuse the existing RAG pipeline, identify ambiguity and missing information, and measure rewriting/decomposition gains.

## User Scenarios & Testing

### User Story 1 - Preserve intent and scope for explicit questions (Priority: P1)

When a user specifies companies and fiscal years, convert the question into searchable information needs while retaining the original wording and every confirmed constraint.

**Why this priority**: Rewriting must preserve companies, periods, metrics and exclusions.
**Independent Test**: Compare constraints and required evidence groups for a canonical question and colloquial variants of the same intent.

**Acceptance Scenarios**:

1. **Given** a question about AMD FY2024 consolidated revenue, **When** the user supplies a disambiguated Chinese shorthand variant, **Then** preserve the company, period, metric and original question.
2. **Given** a clear, simple question supported by the existing path, **When** it is submitted, **Then** allow direct retrieval without a mandatory planning call.
3. **Given** an explicit company or period exclusion, **When** rewriting, **Then** preserve the exclusion.

### User Story 2 - Clarify ambiguity and report missing material (Priority: P1)

For questions such as “Who was more profitable over these two years?” or “What about the other company?”, inherit only confirmed context and clarify missing essential conditions.

**Why this priority**: Guessing a metric definition or period changes the user's intent.
**Independent Test**: Check outcomes and actual retrieval scope for clarification, out-of-corpus and context-conflict cases.

**Acceptance Scenarios**:

1. **Given** no confirmed comparison subjects, metric or period, **When** asked “Who was more profitable over these two years?”, **Then** ask for missing conditions rather than choosing gross margin or the latest fiscal year in the corpus.
2. **Given** a company or period absent from the corpus, **When** queried, **Then** report missing material rather than substituting a similar company or another period.
3. **Given** “latest” cannot be established from the source manifest and cutoff, **When** planning, **Then** explain coverage and clarify; do not equate the latest stored report with the latest actual report.

### User Story 3 - Decompose compound questions and check coverage (Priority: P2)

Split information needs by company, period and topic, and list dependencies, evidence and missing information.

**Why this priority**: One highly relevant passage does not cover an entire comparison.
**Independent Test**: Check subtasks, inherited constraints, evidence mappings, combined coverage and total budget.

**Acceptance Scenarios**:

1. **Given** confirmed NVDA/AMD comparisons for each company's FY2024/FY2025, **When** planning, **Then** cover both firms and required periods, list actual dates separately, and do not present them as identical calendar years.
2. **Given** a need for unavailable data extraction or calculation, **When** executing, **Then** report the missing capability rather than claiming the task was completed.
3. **Given** missing explanatory evidence for one company, **When** combining results, **Then** identify the gap and search again within budget or clarify; do not substitute another company's evidence.

### Edge Cases

- Empty questions, unresolved references, and conflicts between request parameters and conversation context.
- Differences among report FY, calendar year, quarter and comparative table periods; amendments and unpublished reports.
- Candidate terms suggest a cause that the source does not support.
- Invalid plans, unavailable services, dependency cycles and budget limits.
- Missing evidence and service failure are distinct; no retrieval hit does not prove the full report contains no disclosure.

## Scope and Change Boundaries

- **In scope**: Understanding/clarification, constrained rewriting, bounded decomposition, plan output, existing evidence retrieval, gap/budget recording, reuse of feature 002's online need-level generation contract, and incremental evaluation.
- **Out of scope**: Financial fact store, deterministic calculation/forecasting/valuation tools, UI and multiple agents. Reuse 002's model adapter rather than adding a service. Plans may describe these needs; execution may use only available capabilities.
- **Existing behavior to preserve**: CLI/evidence packages, basic filters, fixed term expansion, source locations, frozen configurations and data. The new path remains optional and does not replace the original default before acceptance.
- **Sources**: [Notion v0.9 sections 5.4, 1.1, 5.3, 7.1](https://app.notion.com/p/Agent-3f6fda5b0ede808b9b60cee10e298cee), read 2026-10-25; [README sections 5, 8, 10 at that time](../../README.md).

## Requirements

### Functional Requirements

- **FR-001**: Retain the original question, confirmed context, planning version and traceable decision records.
- **FR-002**: Represent company, actual period, report scope, cutoff, metric and exclusions separately. Rewriting/decomposition must preserve explicit constraints; conflicts must not be resolved silently.
- **FR-003**: Return clarification for missing essential conditions and missing-material status for explicit out-of-corpus requests.
- **FR-004**: Allow simple questions to bypass planning. Each subquestion must be understandable alone, inherit constraints and map to the original information need without assuming an answer.
- **FR-005**: Evidence tasks provide semantic queries, keywords and independent filters. Preserve company/period/topic-to-evidence mappings rather than concatenating everything into one long question.
- **FR-006**: Subtasks list information-need IDs, available paths and dependencies; runtime must not use gold evidence groups. Report unavailable capabilities and invalid dependencies/plans explicitly rather than claiming successful execution.
- **FR-007**: Declare and enforce budgets for subtasks, variants, candidates, final evidence and follow-up retrieval. Initial limits: 4 subtasks, 2 retrieval variants per task, 1 follow-up round, 10 final evidence items and 8,000 proxy tokens. Record candidate quotas separately from the final budget; default changes require matching spec/config/evaluation updates.
- **FR-008**: Deduplicate, check required information coverage, and report gaps/stop reasons when merging. Receiving top-k results does not establish task completion.
- **FR-009**: Compare the new and original paths. Mark any fallback after planning failure; permit it only if the original path preserves every confirmed constraint without widening scope.
- **FR-010**: Record effective constraints, tasks/queries, paths, evidence, budgets, additional calls/cost/time, or explicit not-called/not-measurable states. Do not record secrets.
- **FR-011**: Manually review information needs and evidence groups for incremental evaluation; group variants by intent. Do not overwrite published tests, reuse them for selection, or pass gold to runtime.
- **FR-012**: Invoke only explicitly available capabilities. A plan must not grant arbitrary database-query or code-execution permission.
- **FR-013**: Derive company/report scope from corpus metadata and configurable registration. Do not maintain a fixed three-company or financial-term list in the new path. A name missed by rules is not automatically “no company”; allow validated model alias resolution and preserve/report unknown entities or missing material.
- **FR-014**: Return structured plans and validate companies, periods, cutoff, exclusions, dependencies and budgets. Stop on conflicts with confirmed constraints; never silently widen scope. Structured output does not guarantee semantic correctness.
- **FR-015**: Assemble text/table context only through source mappings. Restore complete original tables or nearby headers within budget; added material counts toward coverage only if it actually enters context. Report unsupported table/image recovery explicitly.
- **FR-016**: Record model failure, invalid plans, resource limits, empty retrieval and clarification separately. Reuse saved plans/candidates for offline comparisons to avoid repeated paid calls. New-company support and scalable design are not evidence of completed large-scale stress tests.
- **FR-017**: Answer each runtime need and validate omissions, citation IDs and truncation. Evaluate semantic support and financial arithmetic separately; valid structure does not mean a verified answer.
- **FR-018**: Add an explicit offline need-aware context-budget experiment using only saved runtime plans, candidates and sources. Select by marginal need/task/source benefit and token cost without charging shared evidence twice. Task/source matches are retrieval proxies, not proof of semantic satisfaction. Retain the 10-item/8K default; report the 30-item safety cap with the same 8K separately, never as a same-k gain.
- **FR-019**: Compare at least rank/need-aware selection ×10/30 items using identical candidate windows, table rules and 8K budgets. Save actual text, source spans, per-question scores/regressions, latency and budget use. Save every selection before loading gold. No new model calls or changes to labels/indexes/old reports/defaults; follow-up retrieval, hierarchical extraction and answer correctness require separate experiments.
- **FR-020**: In an explicit reranking experiment, use the authorized DeepSeek API and shared ledger to grade semantic relevance/need support across all saved candidates in batches, before Top80 truncation. Inputs contain only the original question, runtime plan, sources and candidate text; exclude gold, reference answers and expected numbers. Scores are model judgments, not human qrels. Audit batches, prompts, raw responses, cost, cache and failure. Allow at most one bounded JSON/schema repair; do not retry service errors.
- **FR-021**: Table/prose compression selects only original lines/spans and preserves sources, headers and units; it must not generate or rewrite numbers. Final Hit spans must identify text actually shown, not omitted whole-chunk spans that inflate recall. PostgreSQL JSONB tables are not a financial fact store or reliable column semantics. Do not add fact tables or change old indexes.
- **FR-022**: Cap each question at its rank30 experiment's actual evidence tokens and serialized full-answer-input proxy tokens under the same answer prompt; neither may increase. Report original rank10 actual-budget diagnostics separately. Account for reranking API input/output, cost and latency separately; unchanged context cost does not mean unchanged total cost. Allow at most 30 items without expanding context or weakening company/report/as_of constraints.
- **FR-023**: Add an explicit zero-API Top80 coarse-ranking experiment with fixed original 20-question plans, dense candidate union, indexes and source scope. Build shortlists only from runtime search ranks/distances/query terms/source spans. Exclude old LLM scores, gold and references from coarse ranking. Do not exceed80 items, add company/question-specific rules or replace the default entry point.
- **FR-024**: Predeclare8 controls: original ranking, global RRF, source-deduplicated versions of both, group seed quotas+deduplicated RRF, candidate-local BM25+dense fusion with/without group seeds, and deduplicated cosine ranking. Local BM25 only reranks retrieved text, not full-corpus recall. Seed quotas do not prove need satisfaction. Save shortlists, source/ranking reasons and CPU time.
- **FR-025**: Load old reranking scores only after all shortlists are saved. Reuse the original-table selector and rank30 per-question actual evidence/full-input caps; save actual context before gold scoring. Report Top80 macro/micro evidence recall, final coverage, per-question changes and correlation with old LLM relevance proxies; do not call the latter human Precision@80. Replay does not establish new-batch quality, live API cost/latency or independent generalization.
- **FR-026**: The explicit focused-query experiment changes only dense-query wording in saved plans. Keep companies, report scope, as_of, needs, task IDs/need mappings/tickers and queries per task unchanged. Generate queries with need/evidence-objective explanations from original question, reading context, confirmations and runtime plan; exclude gold, answers, historical failure labels and target Blocks. Allow one structure/scope repair; cache prompt and complete input hashes.
- **FR-027**: Predeclare wide/focused/mixed arms. Mixed keeps the first original wide query and first focused query within existing slots; single-query tasks use the focused query. No extra vector queries, group SQL calls, dense_k or Top80 capacity. Fix chunk/index, dense_k20, original RRF/interleave, at most 512 candidates and Top80. No new FTS, rechunking, fact store, agent framework or default planner change.
- **FR-028**: Call Voyage and read-only PostgreSQL for new queries and save actual candidates/local traces. Complete all retrieval/shortlists before gold candidate/Top80 scoring. Reuse old scores only for identical question/needs/source text; pay only for new Top80 candidates. Retain original tables and rank30 per-question dual actual budgets. Separate reused/new score cost; no generated answers means no answer-accuracy claim.
- **FR-029**: Share the original $5 ledger, with this round's cumulative stop at $1.60 and old unknown reservations retained. Limit each LLM call to 60 seconds total; no automatic service retry and at most one structural repair. Start with a pilot, then complete20 questions; resume/cache to avoid duplicates. Save explicit failure/cost states. Do not expand prompts or parameter grids merely because budget remains.

### Key Entities

- **Original request**: Original question, confirmed context and explicit constraints.
- **QueryPlan**: Resolved constraints, clarification/gaps, tasks, dependencies, paths and budgets.
- **Subtask**: Independent question, scope, retrieval queries/keywords and evidence requirements.
- **Execution record**: Actual execution, evidence relations, gaps, stop reasons and cost.

## Success Criteria

### Measurable Outcomes

- **SC-001**: Preserve100% of explicit company/period/cutoff/exclusion constraints in manually confirmed boundary cases. Never silently widen scope or report unavailable execution as complete.
- **SC-002**: Every valid subtask maps to an original information need, and evidence maps to subtasks. Return explicit outcomes for every invalid, over-limit or cyclic dependency case.
- **SC-003**: Original query regressions pass; frozen labels/defaults/release-marker hashes remain unchanged.
- **SC-004**: Save per-question results for the old baseline, metadata-scoped planning, rewriting/decomposition, fusion/context and generation on the published20-question dev set. Compare at 10 items/8K proxy tokens; report larger budgets separately. Recommend an experiment only if complete-question coverage does not fall and macro coverage improves. Keep the new path explicit rather than replacing the frozen default.
- **SC-005**: Build offline contract cases for Chinese/English company names joined to text, new firms, exclusions, historical cutoffs, absent companies/periods, invalid plans and budget failures. Put same-intent cases in the dev family; mocks validate contracts, not independent generalization. Prepare independent holdout and natural colloquial evaluation separately.
- **SC-006**: Record all four budget arms and per-question changes on 20 dev questions. Verify exact rank10 replay, actual context within 8K/item caps, spans matching shown text, and explicit missing-plan errors. Recommend only what controls support; do not change labels or add per-question rules to force gains.
- **SC-007**: Target 70% final-context macro evidence recall on 20 dev questions under FR-022 per-question cost caps. Compare original ranking, Top80 reranking, full-pool reranking, and full-pool reranking with source compression. Save selections before loading gold; report misses/regressions without label changes or question-specific rules. Meeting the dev target is not holdout, semantic/numeric or production acceptance.
- **SC-008**: Every Top80 arm contains at most 80 original-pool candidates with unchanged as_of/source integrity. Replay original Top80 and reranked context exactly. Record all controls/regressions without repeatedly expanding the grid to force a win; 70% is not mandatory. Verify selection/scoring isolation, duplicate spans, new-company compatibility, protected hashes and zero paid calls; explain why v1/v2 scores are not directly comparable.
- **SC-009**: Verify identical filters/tasks/query counts/SQL groups/k across all three focused-query arms; replay wide candidates, Top80 and context exactly. Verify PostgreSQL index fingerprint, sources and protected config/gold/report hashes. Report pool/Top80 macro/micro recall, complete questions, per-question changes, context/model-score proxies, SQL/embedding/LLM time and actual-usage list-price cost. All 20 remain dev. Report partial answers, unmet targets, insufficient task slots and omitted needs without inventing verified capabilities.

## Acceptance Traceability

| Requirement | Scenario / criterion | Verification evidence to produce |
| --- | --- | --- |
| FR-001, FR-010 | US1 / SC-002, SC-004 | Original request/execution records and call-cost fields |
| FR-002, FR-003 | US1, US2 / SC-001 | Constraint, conflict, clarification and out-of-corpus cases |
| FR-004, FR-005 | US1, US3 / SC-001, SC-002 | Canonical/colloquial task and retrieval-query comparisons |
| FR-006, FR-012 | US3 / SC-001, SC-002 | Unavailable capabilities and invalid plans/dependencies |
| FR-007, FR-008 | US3 / SC-002 | Budgets, deduplication, coverage and follow-up stop cases |
| FR-009 | US1 / SC-001, SC-003 | Original-path regression and scope-preserving fallback |
| FR-011 | SC-003, SC-004 | Intent splits/frozen hashes, per-question results and limits |
| FR-013–016 | SC-001, SC-005 | New-company/scope contracts, source mappings, limits and failures |
| FR-017 | SC-004 | Need-level structure checks on 20 questions and unverified semantic errors |

## Assumptions

- The user explicitly authorized these improvements; published held-out tests are not reused for selection.
- The original 28-case draft was replaced by 20 dev questions plus offline boundary contracts. Published v2 has no independent holdout yet; v1 and historical results remain unchanged.
- Feature 002's model adapter is reusable. Answers were generated for 20 questions; full factual/numeric/citation-support scoring remains incomplete.
- Reuse DeepSeek/Voyage and existing indexes with the original $5 shared ledger. Further reranking iterations and production financial calculation are separate work.
- Initial support covers Chinese, English and common aliases, not arbitrary languages or companies.
