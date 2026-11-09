# Golden v3：规范意图开发集

**20道原题 → 81个子题。** 内容来自已审核的v2参考答案及原始数值检查；子题措辞、答案切片、证据分配与新增映射为Agent整理，**待逐项复核，尚未冻结**。没有调用模型API生成新财报事实，也没有重跑检索/答案。

“独立意图”指能独立验收的一项工作，仍可跨公司、跨财年、需要多条证据；不按问号或单个单元格机械切分。

## 从哪里看

| 文件 | 用途 |
| --- | --- |
| [parent_child_map.md](parent_child_map.md) | 先看原20题各拆成什么、各自任务类型 |
| [reference_answers.md](reference_answers.md) | 每个子题独立问题、参考答案、必答点和边界 |
| `retrieval_queries.jsonl` | 只含请求字段，不含答案、证据、评分点或oracle子任务 |
| `golden.jsonl` | 全81题；兼容Question，含子题自己的参考答案和证据组 |
| `retrieval_case_ids.json` | 75道有正证据标签的ID；筛选golden评span recall，不复制整份标签 |
| `rubrics.jsonl` | 每子题自己的事实、边界、错误和数值ID，未照抄整份父题要求 |
| `planner_expectations.jsonl` | 离线评Planner的公司、报告FY、截止日与目标意图；不要求改写逐字相同 |
| `numeric_checks.jsonl` | 原123个唯一检查ID/期望值/容差，子题内合计144次适用 |
| `lineage.jsonl`、`parent_coverage.json` | 父事实/证据/约束去向、表格投影、改写及去范围理由 |
| `evidence_catalog.jsonl` | 从v2复用的可定位来源、原文与字符区间 |
| `evaluation_dataset.jsonl` | 可由RAGAS读取的参考字段；没有实际检索结果、模型回答或Judge得分 |
| `split_specs.json` | 可编辑的人工整理输入；`manifest.json`记录构建与源文件hash |

v2及其历史结果保持不变。新参考答案不是过去生产答案或新一轮模型生成结果；三者不要混淆。

当前子题仅整理中文，`question_en`为空，不适用于旧的English-query检索选项；若测英文改写，应单独生成并锁定搜索计划。当前有101个局部必答点，证据组适用次数见manifest（含共享及3条新增短原文），不能当作新增独立事实数。

## 拆分实例

原U01分为：产品分类；DRAM/NAND三年收入/占比/增速及Other收入分布；产品毛利披露；市场份额资料边界；产品与分部及重述可比性。收入矩阵仍是一项可独立验收的多年分析，而不是每个年份、金额再造一题。

原U06分为：年度NRV净影响、移除指定效应后的毛利、跨期金额桥接、跨期百分点桥接、批次耗尽及FY2025比较、会计含义。这样能区分“找不到原值”和“原值在但符号/口径读错”。

原U13没要求数据中心占公司收入比，原附加的N043/N047/N051不再扣在它的子题上；这些检查仍在明确询问占比的U17.02使用，原值/容差未改。U15.07补了3条来自已审核目录的短原文标签，用于外包制造与PPE资本基数，新增标签也待复核。

## 用户输入与评测边界

这些子题是从复合题整理出的**规范意图**，不是新收集的用户原始提问。它们可以执行 rewriter 并检查范围是否漂移，但表达已经规整，不能充分测出口语、歧义或上下文指代下的改写收益。原20题用于复杂任务拆解；真实输入与规范意图的配对评测还需另建，mock 也要标明来源。详见 [raw-query 评测设计](../../../docs/evaluation.md#raw-query-and-rewrite-evaluation)。

## 能测哪些环节

| 协议 | 系统输入与控制 | 回答的问题 |
| --- | --- | --- |
| R0：检索组件 | 固定人工/冻结搜索计划、过滤及预算，跳过在线Planner | chunk/index/召回/精排/上下文的损失在哪里？固定搜索计划仍需另行编制或冻结，不是本次已跑结果 |
| R1：Planner＋检索 | 规范子题→线上改写/规划→召回→精排→context | 明确输入下是否保留公司/期间/目标，最终证据是否找全？不能据此证明真实输入改写质量。此时Recall是联合表现，不是纯检索表现 |
| R2：端到端 | R1＋可选计算＋生成 | 完整性、真实性、faithfulness、引用及数值怎样？用现有五维rubric及每子题的局部必答点 |
| R3：复合问题压力测试 | 保留原20题，线上自行拆解；子题映射仅供离线核对 | 是否漏子目标、预算如何分配、跨任务上下文是否完整？不能把gold子题先喂给Planner再宣称会拆解 |

本数据集**不只测retrieval**。具体测到哪层取决于评测入口。若需要区分改写与检索因果，固定索引、重排器和总搜索预算，比较R0/R1并核对Planner契约。没有唯一“正确改写句子”。

6道纯资料边界题不计正证据Recall；不能给它们Recall=1，也不能把不存在的份额/季度表列作必须召回。应评范围说明、是否编造以及是否明确缺什么。其余子题的未标注chunk不能自动当负例，Precision/nDCG仍需要候选相关性判断。

## 统计与拆分纪律

- 全部仍为**dev**；81行不是81个新增独立样本，不能声称测试集扩大或泛化提高。
- 原父题、改写变体和跨父题近重复意图必须同split。`split_group`合并父family与已声明的相关意图，`related_intent_group`显式标注如U03.01/U17.01的重叠。
- 同时报子题宏平均、父题等权结果、类型分层及数值去重统计；不能只用81行均分让拆得多的父题占更大权重。
- 数值有123个唯一ID、144次按子题适用；旧v2为147次，减少3次来自U13去除无关占比要求。共享检查不要冒充独立观测。
- 子题拆解图和`planner_expectations`都是离线标签。未来框架的在线子任务由用户请求产生，不读这些gold文件。
- 新集与旧集任务/分母不同，不能直接比较旧69.81%与新Recall，或把拆题后的高分当模型改进。
- 仍缺口语/歧义/排除/冲突确认等专门对照，也缺独立Alphabet/Amazon新意图保留集。原题已有新公司文件不代表已有泛化标签。

## 离线构建与复核

```sh
.venv/bin/python scripts/build_golden_v3.py
.venv/bin/python scripts/build_golden_v3.py --check
.venv/bin/python scripts/build_golden_v2.py --check
```

后续R1可用下面入口；`--retrieve-only`仍会执行Planner、query embedding及精排，**不是纯R0检索**，未命中缓存会计费。本轮没有执行该命令，也不自动提高现有费用停止线。

```sh
.venv/bin/python -m finrag.evaluation run \
  --queries data/evaluation/golden_v3/retrieval_queries.jsonl \
  --ids U01.01 --retrieve-only --out reports/answer_eval/<new-run>
```

去掉`--retrieve-only`才包含答案生成。离线评分时将`answer_eval prepare --golden`指向本目录；读取的trace必须来自同一子题及其完整请求，不能拿父题历史回答冒充子题新回答。

先复核父子题表，再按子题检查问题是否独立、答案是否答全、证据/数值是否只服务该题、继承的边界是否适用。修改`split_specs.json`后重建；新冻结需新的发布记录，不能覆盖v2。所有后续运行用新目录、新dataset hash。
