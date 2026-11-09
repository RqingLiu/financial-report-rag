# Repository cleanup and evaluation scope correction

## Scope

Keep the current serving pipeline and source/evaluation provenance intact while removing obsolete database copies and separating historical experiments from production entry modules. The user explicitly authorized deleting inactive database data and unnecessary intermediate artifacts.

## Requirements

- Keep `finrag_live_ready`, its selected chunk configuration, published documents, source spans, vectors and usable ANN indexes unchanged. Delete only proven inactive project schemas, after recording metadata, sizes, dependencies and active-data signatures. Do not touch unrelated databases or pgvector itself.
- Retain source HTML, paid model/embedding caches, shared budget ledger, reviewed reference data and compact experimental results. Compress local historical traces with per-file checksums, verify archives before removing expanded copies, and record a restore procedure.
- Move historical Python entry points and adapters out of the production module root, update callers, tests and docs, and remove the obsolete serving bootstrap command once its source database is retired. Current ingestion must work from HTML and metadata without the research database.
- Preserve frozen builders and label bytes. Archive obsolete drafts and historical source snapshots without representing changed code as the original frozen implementation.
- Describe the 81 child questions as canonical intent development cases, not realistic raw user input. They support controlled component checks but do not establish natural-query rewriting quality. Specify a separate paired raw-query protocol with provenance and no gold leakage.
- Write a separate next-step RAG Agent design informed by course chapters 10 and 11: state, decision, action, constrained tools, bounded routing and stage-specific evaluation. No framework installation, new agent runtime, paid experiments or publication in this cleanup.

## Acceptance

Active database counts and content signatures match before/after; no inactive project schema remains; unrelated databases remain. Offline tests and active DB contracts pass. Serving imports do not depend on legacy experiment adapters. Archives verify and have a documented restoration path. Repository navigation distinguishes live defaults, offline evaluation, historical controls and proposed agent work.
