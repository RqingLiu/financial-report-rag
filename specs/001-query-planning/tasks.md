# Tasks: QueryPlan and RAG Increment

## Focused subquery comparison (FR026–029 / SC009)
- [x] T019 Implement wording-only refinement, three plan arms, equivalent-search-quota validation and failure/cache contracts.
- [x] T020 Keep chunks/indexes and read-only PostgreSQL; pilot then run 20 questions, saving pools/Top80. Reuse old scores, grade only new Top80 candidates and save actual context under the shared budget.
- [x] T021 Evaluate stages, per-question failures/changes, source/budget/index/protected hashes and regressions. Update README/Notion flow/results without changing defaults.

Acceptance: `reports/focused_queries/20261028T022730Z_78c0ce/`. Wide/focused/mixed Top80 macro recall 80.95/82.24/82.08%; final 67.66/69.81/66.78%. Focused: 2 improved/18 unchanged/0 regressed, 150/225 groups, 4/20 complete, below 70%. Its full pool slightly regressed; U19 remained 2/23. Mixed regressed on U19/U20; neither promoted. Tests: 56 passed/1 skipped; lint passed. Verified 60 contexts/6,759 spans, filters/tasks/query counts/SQL/dual budgets, byte-identical baseline replay and index/protected hashes. Only 70 new Top80 candidates graded. Round including failed pilot: $0.03394216 conservative list price; cumulative $0.97575738 and old unknown $0.0093642 retained. Historical README §8.10, Notion §5.12 and diagrams §3.4/§5.10 synchronized. No new answers, independent holdout or cold-request cost claim.

## Offline Top80 coarse ranking (FR023–025 / SC008)
- [x] T016 Implement8 predeclared strategies isolated from LLM scores/gold; save Top80, reasons and CPU time.
- [x] T017 Replay old scores/original-table context with zero API calls; verify baseline identity, text/dual budgets/as_of/protected hashes.
- [x] T018 Run 20 questions; compare shortlist/final coverage, regressions/model proxies and v1/v2 task differences. Run regressions and update README/Notion without default promotion.

Acceptance: `reports/coarse_rank/20261028T014418Z_b5443e/` (UTC; local October 27). Global RRF Top80 macro recall 80.95%→82.18%, reused-score context 67.66%→68.77%; 5 improved/13 unchanged/U14 and U17 regressed. Below 70%; no default promotion. All 8 arms/160 contexts passed text/dual-budget/as_of/protected-hash/original-Top80 replay checks; 50 passed/1 skipped, lint passed, zero new API cost. All 16 missing pool groups lacked target Blocks, 10 from U19. V1 averages3.08 evidence groups versus v2's11.25; scores are not directly comparable. Local BM25 is not full-corpus recall; model relevance is not human Precision; reused scores are not new-service acceptance.

- [x] T001 Revise spec/plan/SC-004; record baseline and scaling audit.
- [x] T002 `planning.py`: corpus catalog, structured planning and scope validation (FR001–006,013–014).
- [x] T003 `planned_retrieval.py`/`context.py`: independent scope, candidates and source-context budgets (FR005, 007–008,015–016).
- [x] T004 `answering.py`/`pipeline.py`: need-level answers, traces/offline controls and CLI (FR009–012,016–017).
- [x] T005 Configurable company/collection entry and new-company contracts (FR013).
- [x] T006 Offline/regression/real20-question dev run and 6-question generation pilot; record cost/regressions (SC001–005).
- [x] T007 Summarize measured recommendations and next reranker/calculator work; update README/Notion.

Acceptance: all 20 questions planned/retrieved/generated successfully. At Top10/8K, macro coverage 13.56%→36.60%; 14 improved/4 unchanged/U07 and U15 regressed. Tests: 39 passed/1 skipped; original index/frozen hashes unchanged. Formal numeric/semantic review, independent holdout, reranking and deterministic calculation were future work at this stage, not accepted as complete.

## 2026-10-27: Context-budget experiment (FR018–019 / SC006)
- [x] T008 Add explicit need_budget selection, runtime need/task/source links and marginal-benefit/token-cost logs; preserve old selection.
- [x] T009 Add zero-API four-arm replay with selection/gold isolation; save actual contexts/results/hashes.
- [x] T010 Test sources, budgets, shared needs, gold isolation, missing plans and old replay; run 20 read-only cases.
- [x] T011 Record gains/regressions/limits/recommendation; update README, Notion §5.8 and experiment entry without changing defaults or claiming better generation.

Outcome: `reports/context_budget/20261027T072215Z_6c99b5/`; rank10/rank30/need10/need30 macro evidence recall 36.60%/47.34%/26.40%/45.16%. Need-aware selection did not beat rank under matching caps; retain only as experiment. Tests: 42 passed/1 skipped; 80 actual contexts passed budgets; all 20 rank10 outputs replayed exactly. Zero cost, protected hashes unchanged. Follow-up retrieval, hierarchical extraction and new answer generation were not completed here.

## Fixed actual context-cost reranking, target 70% (FR020–022 / SC007)
- [x] T012 Verify PostgreSQL table storage; add full-pool LLM grading with cache/trace/budget and strict line/need validation.
- [x] T013 Extract original lines only, rebuild actual spans and enforce full-prompt/evidence dual token caps; preserve old answer-message compatibility.
- [x] T014 Pilot then grade20 questions and select four arms; load gold after selection; preserve defaults/old data.
- [x] T015 Test spans, table retention, injection/invalid IDs, dual budgets and cache; report target/regressions/cost and sync README/Notion.

Acceptance: `reports/rerank/20261027T170703Z_9a25db/`. Under rank30 per-question actual evidence/full-input caps, macro recall 47.34%→71.45% (17 improved/3 unchanged/0 regressed), meeting 70%. Compression+need allocation 75.24% regressed on U12. Earlier 10-item actual-budget result 56.95% is separate. Tests: 47 passed/1 skipped; 100 contexts/8,919 spans, dual budgets/as_of/read-only gold/frozen core hashes verified. Incremental peak list-price usage estimate $0.76523250 plus $0.0093642 unknown reservation; resume reused 19 questions/successful batches. No generated answers, serving-default switch or financial-fact/tool acceptance.
