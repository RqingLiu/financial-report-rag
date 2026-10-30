# 实验目录与可追溯结果

[项目首页](../README.zh-CN.md) · [项目深挖](project-deep-dive.md) · [指标边界](evaluation.md) · [公开JSON目录](../reports/public/experiments/README.md)

本页呈现历史实测，不是新跑一轮评测。所有百分比均附对应JSON；来源文件SHA256在[manifest](../reports/public/experiments/manifest.json)。20题全部为开发数据；原始模型消息/大Trace保留本地。公开汇总与逐题计数足以检查算术，不等于不提供原始运行文件也能完整重建所有付费响应。

## 数据集和实验不能混在一起

| 系列 | 数据与条件 | 可说明 / 不可说明 |
| --- | --- | --- |
| v1切块/检索 |60题=30dev/30test，各25可回答+5边界；5种切块配置，28组检索组合 | 支持历史dev选型；GPT初稿语义标注仍有局限，不是独立人工金融基准 |
| v2复杂问答 |20题dev，225证据组、123参考数值检查；平均每题11.25组、3.10份报告 | 测复杂比较证据损失；不是独立holdout或在线答案正确率 |
| 真实ANN |2,759块，59次有过滤的缓存子查询，exact Top20作参照 | 真实索引路径/近邻重合；不代表大库RPS |
| 合成ANN |10k/30k/100k，扰动缓存向量，24查询×2次、100%/10%/1%过滤 | 人工分布压力与SQL成本；不是新增真实文档/48个独立意图 |

## 切块与早期检索

v1 dev宏Recall@10的部分结果，完整28组见[v1_dev.json](../reports/public/experiments/v1_dev.json)：

| 配置 | dev R@10 |
| --- | ---: |
| recursive384 plain dense |44.0%|
| recursive768 contextual dense |68.7%|
| structure512 contextual dense |62.0%|
| recursive768 contextual hybrid + domain query |87.3%|
| structure512 table-context hybrid + domain query |94.7%|
| 同上 + parent expansion |92.0%|
| Markdown tree domain control |87.1%|

有些行同时改变多个变量，不把差值归因于单一算法。domain_query含当时的显式词汇扩展，不能冒充新Planner自动改写。选中结构/表格配置后，v1冻结test宏R@5/10/20为71.33%/86.00%/100%；@10跨文档子集全证据完整1/5。[冻结原始结果](../reports/test_release.json)。旧test未用于后续v2策略选择。

## 上下文与精排

原20题saved plans/dense候选，Top80窗口、8K证据上限：

| 上下文选择 | 宏覆盖 | 命中组 | 完整题 | 平均证据代理tokens |
| --- | ---: | ---: | ---: | ---: |
| rank10 |36.60%|78/225|2/20|4,326|
| rank30 |47.34%|102/225|2/20|7,957|
| need-budget30代理策略 |45.16%|89/225|3/20|7,876|

[context.json](../reports/public/experiments/context.json)含80条逐题/策略记录。rank30放宽了item上限且增加实际输入，不是免费提升；need代理不证明语义支持，U11/U12/U20有严重退步，因此不默认采用。

在每题不超过原rank30**实际证据与完整答案输入双预算**、≤30项条件下：

| 精排策略 | 宏覆盖 | 命中组 | 完整题 | 平均证据 / 完整输入代理tokens |
| --- | ---: | ---: | ---: | ---: |
| Top80 LLM，保留原表 |67.66%|146/225|4/20|7,823 /16,526|
| 全候选LLM，保留原表 |71.45%|156/225|4/20|7,827 /16,518|
| 全候选LLM + 选行 |74.06%|160/225|4/20|7,410 /16,128|
| 再按模型need判断分配 |75.24%|162/225|4/20|7,406 /16,149|

[rerank.json](../reports/public/experiments/rerank.json)含120条逐题记录。全池每题29–573候选；“上下文成本不增”不等于总调用成本不增。选行方案U12退步，最高均分未直接部署。该轮新增调用保守列表价估算约$0.7652（含整轮工作，不是单query），复用已完成响应/缓存，不是冷请求均价；单次完成调用延迟也不是端到端p95。默认服务选择有界Top80，继续保留全候选为实验。

## 粗排与聚焦子查询

- [coarse.json](../reports/public/experiments/coarse.json)：8组固定Top80的离线回放，新增API=0。全局RRF最终67.66%→68.77%，但U14/U17退步；候选内BM25不能找回全库未召回证据。
- [focused.json](../reports/public/experiments/focused.json)：不改chunk/index/过滤/查询槽位/每次k，wide/focused/mixed最终67.66%/69.81%/66.78%。聚焦组两题改善、18持平；仅新候选补评分，旧评分复用，未生成答案。
- [funnel.json](../reports/public/experiments/funnel.json)：候选宏94.47%、Top80宏80.95%、rank30/8K宏47.34%。未覆盖123组中的16/33/74分别损失于召回、窗口、窗口内选择；这是阶段归因，不是唯一语义根因证明。

## 同SQL预算的重组／BM25／专用精排

每组342次SQL、同index、Top20/job、Top80、逐题匹配上下文预算；对照使用exact以隔离检索方案，LLM复用部分历史判断，CrossEncoder在各shortlist上重新评分。不是线上默认HNSW的独立冷请求评测。

| 取证方案 | 精排 | 候选宏 | Top80宏 | 最终宏 | 完整题 |
| --- | --- | ---: | ---: | ---: | ---: |
| 原dense |LLM|94.47%|80.95%|67.66%|4/20|
| 原dense |CrossEncoder|94.47%|80.95%|59.20%|4/20|
| 证据目标重组 |LLM|95.62%|79.19%|67.62%|5/20|
| 证据目标重组 |CrossEncoder|95.62%|79.19%|55.82%|4/20|
| BM25替换第二dense槽位 |LLM|94.77%|83.87%|71.53%|5/20|
| BM25替换第二dense槽位 |CrossEncoder|94.77%|83.87%|58.90%|4/20|

[serving.json](../reports/public/experiments/serving.json)含6组汇总与120条逐题记录。71.53%与focused的69.81%来自不同实验，不串成同一条累加提升曲线。当前默认仍dense+LLM；缺独立holdout与答案支持验收，不宣称BM25或CrossEncoder普遍优劣。

## ANN与规模条件

真实小库[ann_real.json](../reports/public/experiments/ann_real.json)：59次实际HNSW索引检查，Top20与exact平均重合98.98%。后续扩容用已有向量加噪、归一化、100个合成文档桶，没有新embedding调用。

100k合成数据的代表组，完整99条参数结果见[ann_synthetic.json](../reports/public/experiments/ann_synthetic.json)：

| 过滤后保留比例 | 方法 | 近邻重合 | SQL p95 |
| --- | --- | ---: | ---: |
|100%|exact|100%|450.06ms|
|100%|HNSW M32 /ef1000 /scan20k|99.17%|5.52ms|
|100%|IVF lists100 /probes10|99.58%|18.24ms|
|1%|exact|100%|6.39ms|
|1%|HNSW M32 /ef1000 /scan20k|94.38%|10.94ms|
|1%|IVF lists100 /probes30|96.67%|59.32ms|

环境：PG17.11、pgvector0.8.6、1024维、单客户端、关闭并行、固定24个缓存查询各重复2次，OS缓存未严格控制。M16在此强聚簇分布发生严重漏召回；高分参数是对同合成分布调参得到，不能直接当成真实金融语料参数。采样RSS不是数据库总RAM。大型隔离测试数据已删除，不自动恢复；不以表中SQL毫秒数宣传服务SLA。

## 复现、校验和费用

1. 只核验公开汇总的逐题算术与文档链接：`python scripts/verify_public_evidence.py`。不需DB、密钥或私人Notion。
2. 从已有本地原始实验重新导出：`python scripts/export_public_experiments.py --check`；缺被忽略原始run时不能执行。来源哈希用于识别原始输入，不假装哈希能替代原始文件。
3. 全量重做需要按[数据说明](data-and-ingestion.md)重建语料，保留gold不入运行时；使用对应实验模块的新run。`context_experiment`、`coarse_experiment`、`focus_experiment`、`rerank_experiment`及`experiments/serving_eval.py`等保留在源码；历史模块依赖saved plans/响应时需先重建或恢复输入，**不是一条命令从新clone复现所有数字**。
4. 缓存缺失的embedding/LLM会计费；本次公开整理没有启动新的付费实验，也未重新生成答案。配置、模型版本、数据范围和随机条件变化后应创建新结果，不能覆盖冻结回执。

后续最重要的是未参与调优的新意图holdout、答案数值/引用支持与拒答评估，再做真实扩库、并发和端到端成本。当前没有完整人工候选相关性标签、没有生产RPS与端到端p95成绩。
