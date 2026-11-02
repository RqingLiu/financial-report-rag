# Tasks: Auditable Development Baseline
- [x] T001 Requirements/design: spec.md / plan.md, FR-001–010.
- [x] T002 US1 Input isolation, observation proxy/local stages, baseline.py / tracing.py; FR-001–005.
- [x] T003 US2 Persistent cross-provider budget and bounded generation, generation.py; FR-007–009.
- [x] T004 US3 Offline rescoring, review views and unique run directories; FR-006, 010.
- [x] T005 Contract tests, original-path equivalence, frozen hashes and old regressions; SC-002, 003.
- [x] T006 Retrieve 20 questions, pilot 6 generated answers, then remaining 14 if checks permit; SC-001, 004.
- [x] T007 Record measured summary/README entry, local/cloud status and unscored items.

Evidence: reports/baseline/20261027T025455Z_3031fa/{summary,validation}.json and findings.md; 20 attempted, 15 generated, 5 incorrect clarifications; 26 passed/1 skipped. Formal semantic answer scoring remains pending; QueryPlan/tuning were not implemented in this increment.
