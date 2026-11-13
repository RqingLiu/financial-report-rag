# Tasks

- [x] T001 Audit all 20 parents, reviewed answers and current execution boundaries.
- [x] T002 Curate standalone child questions, scoped answers/rubrics and lineage.
- [x] T003 Implement deterministic build/check, safe child-ID offline preparation and query-only source selection.
- [x] T004 Validate parent coverage, no runtime gold, source integrity and old-dataset immutability.
- [x] T005 Document layered evaluation and framework migration, including dependencies and budgets.
- [x] T006 Report child counts, review status, checks and unimplemented follow-ups.

Validation: 20 parents map to 81 development children, with 75 positive-evidence retrieval cases and six boundary-only cases. There are 101 scoped fact requirements; all 123 unique prior numeric checks remain, with 144 child occurrences versus 147 parent occurrences. Three unrequested company-share checks were explicitly de-scoped from U13 and retained in U17.02. All parent fact/group/constraint references are accounted for; three added short evidence spans come from the already verified source catalog. Cross-parent related intents join family split components. No parent approval, stale reference lists or parent group IDs are copied into child metadata.

Full offline suite: 123 passed, eight skipped; final builder-focused checks also passed after metadata/source-link refinement. Frozen v2 read-only validation passed, v3 regeneration/check is byte-exact, and RAGAS loaded all 81 reference records. Query-only inputs reject gold columns and unsafe IDs before opening runtime resources. No financial model API calls, framework installation, live default changes, database ingestion, file deletion outside newly generated duplicate exports, or public push occurred. Dataset review/freezing, R0 controlled-search plans, an independent holdout and the proposed runtime migration remain follow-ups.


## Data-review preparation — 2026-11-09

- [x] Select 12 canonical intents with source/period/unit and scoped-rubric notes.
- [x] Prepare 12 synthetic inputs: four colloquial, three exclusion/cutoff, three ambiguous, two unavailable-disclosure cases.
- [x] Export a human review document, offline labels/source catalog and separate query-only records under data/evaluation/pilot_review.
- [x] Validate source locators, cutoff dates, numeric arithmetic, safe query fields and original-data immutability without providers.
- [x] Obtain human approval of the selected questions, reference/rubric corrections and expected mock behavior (2026-11-09 user acceptance; new wording retains synthetic provenance).
- [x] Apply only approved overlays and export scorer-compatible small-batch labels before any authorized paid trial.

The 12 selected intents contain 10 positive-retrieval and two boundary-only cases, with 47 original evidence-group occurrences and 34 applicable existing numeric checks. All 123 existing numeric checks were revalidated; 44 selected/supplemental source aliases were verified against local raw DOM and canonical offsets. Proposed changes address inherited off-scope evidence, explicit units, DSO day conventions and product/segment distinctions. Original v2/v3 artifacts and numeric tolerances remain unchanged. All 24 candidate requests pass the public Request schema; three ambiguous inputs carry no hidden company/year confirmation and have no canonical-answer/positive-recall scoring before clarification. The bundle is not a frozen or scorer-ready release. No API/database calls, new runtime behavior or public publication occurred.


Accepted export validation: data/evaluation/pilot contains 33 development cases (12 canonical, 12 raw mock, six boundary/mixed, three explicit clarification continuations), 38 required numeric IDs plus two dependency-only checks and 46 needed source locations. The original review and v2/v3 hashes are unchanged. Missing-corpus fixtures carry a catalog precondition; derived revenue/conflict cases share their underlying families. New boundary/follow-up wording is explicitly agent-authored under the accepted policy, not observed user traffic. No paid evaluation or runtime behavior change occurred.
