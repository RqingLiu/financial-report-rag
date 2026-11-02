# Feature Specification: Auditable 20-Question Development Baseline

**Feature Directory**: `specs/002-trace-baseline`
**Created**: 2026-10-26
**Status**: Implemented and measured: 20 attempted, 15 generated, 5 incorrectly routed to clarification. Semantic answer review remains pending.
**Input**: Run existing retrieval/generation on the published20-question dev set, retain execution evidence, and analyze before tuning.

## User Scenarios & Testing

### User Story 1 - Locate evidence loss (Priority: P1)
Developers inspect each question's input, effective scope, candidates, fusion ranks and actual context.
**Why this priority**: Aggregate recall cannot explain a failure.
**Independent Test**: Observed and original retrieval return identical results for identical input; evidence present in the pool but absent from context can be located.
**Acceptance Scenarios**:
1. **Given** confirmed reading context and cutoff, **When** running the baseline, **Then** record the original question/actual queries without using answers or evidence labels to modify retrieval.
2. **Given** budget truncation, **When** inspecting the trace, **Then** distinguish retrieval misses, low ranking and context omissions.

### User Story 2 - Generate and save answers within budget (Priority: P1)
Run a small pilot under one generation configuration, then expand to 20 questions.
**Why this priority**: Separate retrieval from answer quality and control cost.
**Independent Test**: Simulate exhausted budgets, network errors, truncation and missing usage; reject further over-limit calls and retain traceable failures.
**Acceptance Scenarios**:
1. **Given** reservations reach the stop threshold, **When** a new call is requested, **Then** reject before calling; spending the entire budget is not a goal.
2. **Given** a timeout with unknown billing, **When** recording the outcome, **Then** retain the reservation without automatic retry.
3. **Given** a generated answer, **When** reviewing, **Then** retain actual evidence, answer and readable view; do not describe arithmetic as verified by a deterministic tool.

### User Story 3 - Reproduce, rescore and extend observation (Priority: P2)
Browse saved runs and recompute deterministic retrieval metrics without repeated fees. Missing cloud credentials do not block local experiments.
**Why this priority**: Preserve audit evidence and a baseline for comparison.
**Independent Test**: Offline rescoring makes no model calls; frozen artifact hashes remain unchanged.
**Acceptance Scenarios**:
1. **Given** saved execution output, **When** rescoring, **Then** do not retrieve or generate again.
2. **Given** no observability-platform credentials, **When** experimenting, **Then** label tracing local-only without claiming a cloud integration.

### Edge Cases
Empty evidence, no documents before cutoff, confirmed-context/parameter conflicts, partial answerability, invalid/empty/truncated responses, provider failure, duplicate execution, concurrent reservations, candidate/context limits and credential disclosure.

## Scope and Change Boundaries
- **In scope**: 20-question dev adapter, stage observation, fixed retrieval/generation baseline, billing ledger, per-question review and deterministic rescoring.
- **Out of scope**: QueryPlan/dynamic rewriting, rerankers, new chunking, forecasts/valuation, complete financial calculators, independent holdout, full automated semantic scoring, multiple agents and automatic cloud-account creation.
- **Existing behavior to preserve**: Old CLI/retrieval source behavior, defaults, published v1/v2 data and historical tests. Keep the QueryPlan draft separate; this baseline does not accept that feature.
- **Sources**: User instructions2026-10-26; historical README §5/8; golden_v2/README; prior evaluation discussion.

## Requirements
### Functional Requirements
- **FR-001**: Runtime accepts only published query inputs: original question, reading context, confirmed context, cutoff and available corpus scope. Gold is offline-scoring input only.
- **FR-002**: Record a unique execution ID per question, effective scope, queries, candidates/ranks from each route, fusion ranks, actual context, and answer or explicit error.
- **FR-003**: Record stage relations/time, inputs/outputs and data/code/prompt/model-config versions; exclude credentials.
- **FR-004**: Preserve retrieval behavior; distinguish unconstrained ranking diagnostics from actual10-item/8K proxy-token context.
- **FR-005**: Reuse source-span scoring and report macro/micro evidence-group recall, complete-evidence rate and stage-level gaps.
- **FR-006**: State numeric, factual, citation-support and boundary-semantic review status. No automatic perfect scores without human review; citation-ID existence is not claim support.
- **FR-007**: Bound generation output/time/cost reservations, return explicit failure without hidden retries, and save usage/pricing basis.
- **FR-008**: All new paid calls, including query embedding/generation, share a persistent ledger. Authorization: $5; default stop: $4.5, with $0.5 buffer. Earlier stopping is allowed.
- **FR-009**: Retain unknown billing reservations and make concurrent reservations atomic. Missing usage is not free usage; estimates are not invoices.
- **FR-010**: Rescore saved runs offline; new runs do not overwrite old results. Retain complete local records without cloud credentials.

### Key Entities
Request, Trace/Stage, Evidence, Experiment, BudgetReservation, Evaluation/Review.

## Success Criteria
### Measurable Outcomes
- **SC-001**: Every attempted question has a complete success record or explicit failure; every item sent to the answer model is traceable.
- **SC-002**: Observed/original paths return identical evidence for identical input/configuration; protected artifact hashes remain unchanged.
- **SC-003**: Over-budget/missing-usage/unknown-timeout tests block uncontrolled further calls. Spending is not targeted at the cap.
- **SC-004**: Pilot 6 questions, then complete20 if APIs/budget permit. Report per-question coverage/root causes and mark unreviewed answer scores pending.

## Acceptance Traceability
| Requirement | Scenario / criterion | Verification evidence |
| --- | --- | --- |
| FR-001, 004 | US1 / SC-002 | Input isolation, constraints and original-path equivalence |
| FR-002, 003,005 | US1 / SC-001 | Stage traces and per-question scores |
| FR-006 | US2 / SC-004 | Review views and pending status |
| FR-007, 008,009 | US2 / SC-003 | Offline failure/budget tests and ledger |
| FR-010 | US3 / SC-002 | Rescoring and protected hashes |

## Assumptions
The local database and saved model credentials are available; external failures are valid observations to deliver. Start locally without cloud credentials. Generation does not itself complete semantic scoring or financial calculation tools. All 20 questions remain dev and support no independent generalization claim.
