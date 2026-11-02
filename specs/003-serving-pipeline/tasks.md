# Tasks

- [x] T01 Audit concrete scaling/generalization risks and separate runtime/experiment boundaries (FR01, 03, 09).
- [x] T02 Atomic document publisher, database catalog, bootstrap and resource validation (FR02, 03).
- [x] T03 ANN adapters, maintenance/benchmark and indexed BM25 (FR04, 06).
- [x] T04 Evidence-objective regrouping with same SQL/coverage validation (FR05).
- [x] T05 CrossEncoder and LLM Top80 reranking integrated into real answer path (FR07).
- [x] T06 Shared CLI / bounded optional localhost API and safe traces (FR08).
- [x] T07 Offline and DB tests, controlled dev comparisons and end-to-end pilot (A1–A4).
- [x] T08 README/Notion update, exact limitations and reproducibility evidence (A5).

Validation: 71 passed with FINRAG_INTEGRATION=1; Ruff passed with unchanged vendor code excluded. Real CLI/HTTP and 8 complex-question generation checks completed; see reports/serving/validation.json. T08's FigJam update was blocked by connector quota; README/Notion diagrams were synchronized. Large-scale load, holdout and semantic answer acceptance remain future work, not production acceptance for this increment.
