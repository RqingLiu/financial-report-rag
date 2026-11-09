# Tasks

- [x] Inspect runtime, history and local database inventory.
- [x] Separate historical modules and update dependent callers/docs.
- [x] Verify and compress historical artifacts; remove expendable copies.
- [x] Retire inactive database schemas; verify active content and ANN.
- [x] Correct raw-query evaluation scope and write the next agent plan.
- [x] Complete offline and database verification; record cleanup receipt.

Validation: 125 offline tests passed (seven skips), six current PostgreSQL contracts passed. Frozen v2 and draft v3 checks passed; actual HNSW returned 20 hits from the preserved corpus. All seven active-table signatures and index definitions matched across retirement. Retired schemas freed 621,535,232 bytes; 1,917 report files compressed from 1,243,909,698 to 181,980,982 bytes with per-file verification. A 55-file archive restoration passed. No model API calls, framework installation or GitHub push occurred. The obsolete schema-dependent DB test was archived, rather than counted as a passing current contract.
