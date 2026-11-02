# Tasks

- [x] T01 Implement bounded fixture generator, safe SQL/search settings, metrics and resource sampling.
- [x] T02 Offline + isolated DB smoke validation.
- [x] T03 Execute 10k/30k/100k sweeps, exact references, plan verification and resource report.
- [x] T04 Analyze selectivity/recall/latency tradeoffs; update README/Notion and state remaining real-data/load gates.

Completed: 75 full-suite tests; 30 ANN measurement files, 4,320 ANN/432 exact samples and 90 representative plans. Source/config unchanged. Retain base HNSW failure and post-hoc memory/M32/ef500/1000 controls. See reports/ann_scale/20261028_scale_v1/validation.json and overview.md. Defaults unchanged.

- [x] T05 On 2026-10-28, remove large synthetic fixtures as requested. Verify schema ownership/table inventory/no active benchmark before dropping8 tables/indexes (6,643,007,488 bytes) and 2 copied vector snapshots. Preserve results, original cache and serving data. cleanup.json confirms schema/snapshot absence and unchanged sources/configs/historical reports at cleanup time. Old runs reject resume. New guard tests passed; 70 passed/6 opt-in DB skipped, Ruff passed. README/Notion reflect retention status and synthetic-distribution limits.
