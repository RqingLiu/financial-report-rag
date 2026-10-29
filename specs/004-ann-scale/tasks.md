# Tasks

- [x] T01 Implement bounded fixture generator, safe SQL/search settings, metrics and resource sampling.
- [x] T02 Offline + isolated DB smoke validation.
- [x] T03 Execute 10k/30k/100k sweeps, exact references, plan verification and resource report.
- [x] T04 Analyze selectivity/recall/latency tradeoffs; update README/Notion and state remaining real-data/load gates.

完成：75项全量测试；30个ANN测量文件、4320 ANN/432 exact样本及90个代表性计划；原source/config不变。保留基础HNSW失败和post-hoc内存/M32/ef500/1000对照。见reports/ann_scale/20261028_scale_v1/validation.json与overview.md；所有默认不变。

- [x] T05 2026-10-28按用户要求清理大型合成数据：核验独立schema归属/表清单/无活动查询后删除8表及索引（6,643,007,488字节）和两份复制向量快照；保留结果、原始缓存与服务数据。cleanup.json记录schema/快照不存在、来源/配置及清理当时历史报告未变。旧run拒绝续跑；新保护测试通过，本轮70 passed/6 opt-in DB skipped，Ruff通过。README/Notion同步保留状态与人工分布限制。
