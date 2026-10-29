# Tasks

- [x] T01 Audit concrete scaling/generalization risks and separate runtime/experiment boundaries (FR01,03,09).
- [x] T02 Atomic document publisher, database catalog, bootstrap and resource validation (FR02,03).
- [x] T03 ANN adapters, maintenance/benchmark and indexed BM25 (FR04,06).
- [x] T04 Evidence-objective regrouping with same SQL/coverage validation (FR05).
- [x] T05 CrossEncoder and LLM Top80 reranking integrated into real answer path (FR07).
- [x] T06 Shared CLI / bounded optional localhost API and safe traces (FR08).
- [x] T07 Offline and DB tests, controlled dev comparisons and end-to-end pilot (A1–A4).
- [x] T08 README/Notion update, exact limitations and reproducibility evidence (A5).

验证：71 passed（FINRAG_INTEGRATION=1），ruff排除原样vendor通过，真实CLI/HTTP与8份复杂题生成；参见reports/serving/validation.json。T08的FigJam未更新，原连接器额度耗尽；README/Notion当前图已同步。大规模/holdout/答案语义验收是后续门槛，不勾作本轮生产验收。
