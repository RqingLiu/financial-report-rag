# Tasks: 可审计开发基线
- [x] T001 需求与方案：spec.md / plan.md，FR-001–010。
- [x] T002 US1 输入隔离与观测代理/本地stage，baseline.py / tracing.py；FR-001–005。
- [x] T003 US2 跨服务持久预算与有界生成，generation.py；FR-007–009。
- [x] T004 US3 离线重评分、复核视图、唯一运行目录；FR-006,010。
- [x] T005 契约测试、原路径一致性、冻结hash、旧回归；SC-002,003。
- [x] T006 跑20题检索和6题生成pilot，确认后补余14题；SC-001,004。
- [x] T007 写实测总结与README入口，明确本地/云端及未评分项。

验收证据：reports/baseline/20261027T025455Z_3031fa/{summary,validation}.json、findings.md；20题尝试、15题生成、5题误澄清；26 passed/1 skipped。答案语义未正式评分，未实施QueryPlan/调优。
