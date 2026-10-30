# Interactive trace studio

## Goal
Make the existing query workflow immediately understandable and inspectable. Initially local-only; the user subsequently authorized publishing the completed work with008's bilingual project guide and main delivery.

## Requirements
- S01: Connected, clickable eight-stage graph; observed status, duration and nested calls. Do not invent progress or model reasoning.
- S02: Selected-stage inspector offers overview, recorded input, output and implementation code. Existing planner/search/candidate/evidence/answer views remain reachable.
- S03: New spans record relative callsite, line and source hash. Historical traces explicitly lack execution provenance; current implementation references must be labeled as such.
- S04: Source endpoint resolves fixed component symbols only, with bounded snippets; never arbitrary files, SQL or executable user input. Browser projection omits system prompts, credentials and provider bodies.
- S05: Keyboard-accessible selection, responsive layout, graph zoom/fit and no external frontend service. Saved replay makes no paid calls.
- S06: Name the catalog as published annual reports, explain DB versus local raw files versus Git-tracked code. Show recorded filing metadata and an explicitly separate read-only current-catalog view. Use a direct technical page title.
- S07: Every graph node visibly identifies its implementation file/function. Provide a complete repository code map with orchestration, implementation, providers and shared entry points; clickable references open the matching function. Resolve current line numbers through the existing allowlist, never assume one stage equals one file.

## Compatibility / non-goals
Preserve query contracts, admission/disconnect handling, retrieval algorithms, model configuration, budgets and frozen evaluation. No new agent framework or public service deployment. Source publication follows008; code snapshots are current checkout references, not reconstructed historical source.

## Acceptance
Provider-free tests verify provenance, source allowlisting and projection privacy. Replay a real saved trace and inspect nodes, child calls, code, candidates and citations at desktop/mobile widths. New UI must distinguish absent, omitted and failed data.
