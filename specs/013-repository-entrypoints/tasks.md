# Tasks

- [x] Audit current runtime, test, dataset and script dependencies.
- [x] Preserve compact answer/evidence records and delete historical bulk.
- [x] Consolidate evaluation commands and dataset tooling.
- [x] Retire unused research modules/configs/tests without removing current contracts.
- [x] Document every retained directory/script and execution path.
- [x] Validate and report actual changes/remaining boundaries.

Validation: 106 current offline tests passed, seven DB tests skipped by default. Retired tests exclusively exercised removed experimental drivers, issuer glossaries, synthetic benchmarks, tree retrieval or old v1 data; provider and source-span contracts were preserved in current test modules. Compound validation retains 20 questions/225 groups/123 checks; the 81-intent draft remains byte-consistent and pending review. The evaluation CLI and U11 saved-trace packet/Judge-prompt export ran without API calls. Public arithmetic/link checks pass. The archive, historical prompt/research folders and experimental drivers were actually deleted, not moved to another hidden copy. Active DB, paid cache, ledger and environments were not modified.

Publication follow-up (2026-11-09): the user separately authorized publishing the completed cleanup and LangGraph migration to main. Merge contribution and data/license notices into both READMEs, remove the standalone files, keep AGENTS.md local, check the actual staged files for private/generated material, and run offline validation before publication. This does not authorize new paid experiments or database changes.

Pre-publication validation (2026-11-09): 106 tests passed and seven opt-in database checks skipped in the local checkout; a temporary export of the actual staged files passed 104 tests with nine corpus/database skips. Ruff, dependency consistency, both dataset validators, public-result arithmetic and 92 local documentation links passed. The staged publication scan and an additional machine-path/identifier scan found no failures. NOTICE and CONTRIBUTING are incorporated in the bilingual READMEs; AGENTS remains local and untracked. No paid API runs or database changes were made. The deterministic draft reference output retains its generated trailing newline.
