# Tasks

- [x] T001 Audit all 20 parents, reviewed answers and current execution boundaries.
- [x] T002 Curate standalone child questions, scoped answers/rubrics and lineage.
- [x] T003 Implement deterministic build/check, safe child-ID offline preparation and query-only source selection.
- [x] T004 Validate parent coverage, no runtime gold, source integrity and old-dataset immutability.
- [x] T005 Document layered evaluation and framework migration, including dependencies and budgets.
- [x] T006 Report child counts, review status, checks and unimplemented follow-ups.

Validation: 20 parents map to 81 development children, with 75 positive-evidence retrieval cases and six boundary-only cases. There are 101 scoped fact requirements; all 123 unique prior numeric checks remain, with 144 child occurrences versus 147 parent occurrences. Three unrequested company-share checks were explicitly de-scoped from U13 and retained in U17.02. All parent fact/group/constraint references are accounted for; three added short evidence spans come from the already verified source catalog. Cross-parent related intents join family split components. No parent approval, stale reference lists or parent group IDs are copied into child metadata.

Full offline suite: 123 passed, eight skipped; final builder-focused checks also passed after metadata/source-link refinement. Frozen v2 read-only validation passed, v3 regeneration/check is byte-exact, and RAGAS loaded all 81 reference records. Query-only inputs reject gold columns and unsafe IDs before opening runtime resources. No financial model API calls, framework installation, live default changes, database ingestion, file deletion outside newly generated duplicate exports, or public push occurred. Dataset review/freezing, R0 controlled-search plans, an independent holdout and the proposed runtime migration remain follow-ups.
