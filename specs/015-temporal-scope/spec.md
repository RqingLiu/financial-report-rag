# Analysis periods and disclosure cutoffs

## Scope
Move the browser disclosure cutoff to advanced options and clarify planner behavior for missing or ambiguous analysis periods. Preserve existing retrieval/reranking settings, costs, attempts and source boundaries. No paid execution or benchmark claims.

## Requirements
- T1: A browser query requires no manual date selection. Advanced options retain an information cutoff defaulting to the local current date, distinct from requested analysis periods.
- T2: Preserve explicit or confirmed company/period/exclusion constraints. The cutoff limits filing publication dates, never silently chooses the analysis year. Later eligible reports may support earlier fact periods.
- T3: If no analysis period is supplied and coverage can reasonably answer the question, use all eligible in-corpus report years for each requested company and disclose that scope. Do not claim complete history or externally latest coverage. Do not require clarification solely because a period was omitted.
- T4: When period interpretation materially affects the answer (calendar versus fiscal year, relative/historical dates or incompatible comparison periods), ask a concrete clarification; no retrieval or generation runs for a clarification outcome. Model judgment is a policy, not deterministic semantic proof.
- T5: The validated plan records analysis-period interpretation, scope source, verbatim supporting quote when supplied by the user, and a short decision basis (not hidden reasoning). State and safe browser projections expose these fields alongside actual selected report years and disclosure cutoff.
- T6: Inferred catalog scope is visibly stated in the rendered answer even if generation omits it. Existing saved plans/traces remain readable; new planner-cache identities isolate the changed contract/prompt.

## Acceptance
Provider-free tests cover omitted scope, explicit earlier facts with later reports, ambiguity/clarification, confirmed scope, historical cutoff filtering, quote validation, default-scope omissions, state/SSE projection and answer scope rendering. All current tests pass. The ledger remains byte-identical and the browser never submits a query during verification.
