# 20题开发 Golden / Evaluation Dataset v2

这份数据集按用户对复核意见的反馈修订，2026-10-26发布。20道题全部为 **dev**，可用于开发阶段的检索与回答评估；已经参与讨论、检索和答案修订，不是独立保留测试集。旧v1及其冻结测试结果不变。

## 入口

- `reference_answers.md`：可读的20题修订答案、必答事实、边界及带原文的引用目录。
- `golden.jsonl`：主数据集，兼容项目`Question`，另含answerability、审批来源、证据组说明。所有题outcome=answer，包括可部分回答的U16；不能因此忽略其边界。
- `rubrics.jsonl`：逐题必答事实、错误推断、缺项预期、必需证据组ID和数值检查ID。
- `evaluation_dataset.jsonl`：RAGAS `EvaluationDataset`/`SingleTurnSample`字段导出。没有运行LLM judge。
- `retrieval_queries.jsonl`：只有原问题及已有阅读背景/截止日/语料范围，适合送入待测系统；不含参考答案、证据或标签。U14必须传入已确认的NVDA FY2024限定，不能只把“这份最早年报”这句孤立输入后再处罚模型。
- `evidence_catalog.jsonl`：原文、URL、accession、财年/申报日、block、DOM与字符区间。
- `numeric_checks.jsonl`：原表输入、列与事实财年、Decimal计算、公式、期望值和精度容差。
- `manifest.json`：输入/产物hash、验证项、审批范围、旧v1保护hash。
- `answer_specs.json`、`label_specs.json`、`numeric_specs.json`：本次发布的离线标注输入；发布后更改需新版本。
- `user_feedback.json`：本次用户反馈原文及其适用范围；历史AI复核仍在`../review_v2/`，作为修订前记录保留。

## 怎样评分

**分别报告下列维度，不默认混成一个“RAG质量总分”。**

| 维度 | 规则 |
|---|---|
| 检索证据覆盖 | `evidence_groups`组间AND、组内OR；任一替代原文区间完整覆盖即命中该组。macro recall按题平均，micro recall按组计数；另报全部必需组命中率。 |
| 事实/口径 | 按rubric每个必答事实0/0.5/1评分；0=遗漏或实质错误，0.5=部分，1=充分正确。分开报告口径错误，不因仅0.01个百分点舍入差重复扣事实分。 |
| 计算 | 对齐指标、单位、期间和范围后，用`numeric_checks`比较。报告正确、轻微精度差异、实质错误、未回答四类；未回答必需数值不能从分母剔除。该文件不自动从自由文本抽数，需人工或另建结构化答案提取器。 |
| 引用与时间 | 逐主张核对引用是否支持、是否越过as_of；U14任何后续报告引用即时间泄漏。可报正确支持的已给引用比例及必答事实引用覆盖率，不能只数链接。 |
| 边界与推断 | 按`expected_limits`和`material_errors`核对是否说明缺项、区分事实/估计/预期、有无不支持的归因或身份猜测；另报边界满足率与实质违规条数。 |

`numeric_checks`的百分比/百分点、天数目标通常保留两位：绝对误差≤0.005视为目标精度内；超过0.005但≤0.02为轻微精度差异。美元百万整数表格使用原表整数；原文约数/区间则依相应事实rubric判定，不能拿管理层的整数近似去处罚成计算错误。如果答案主动使用约数，应先按其声称精度正确舍入后比较（例如“约217%”可支持216.73%）；不能容忍不披露的单位/符号/财年或经营范围错误。派生数从未舍入的中间值计算，最终`ROUND_HALF_UP`。

252.29%与252.30%、17.68%与17.67%属于轻微精度差异。把百万当十亿、应收期末当平均、毛利率与毛利额混算、PPE-only混入无形资产、持续经营与合计混算属于实质口径/计算问题。纯计算错误不扣检索分；如果原因是检索了错误年度，则检索及期间维度分别记录根因，不把同一错误重复计为独立失败样本。

U02不因年报没有完整季度序列扣检索分，现有季度线索是补充项。U16不要求无来源的市场份额：正确回答产品映射，并明确年报内无足够同口径份额材料，即可满足预期；整题一概拒答仍会漏掉可回答事实。其他部分可回答题同理。

证据组依据必答事实整理，参考答案的全部引文不是全都必需。表格通常使用所需行的短span，避免要求召回无关整表；时间、单位、列解释另在答案/引用维度审查。备选证据清单不保证穷尽：若模型找到未列出但同样有效的证据，记录人工裁定并在**下一版本**扩充标签，不就地改分。本次不提供全语料二元相关性标签，未标注chunk不自动等于无关，因此不声称可据此可靠计算全库precision或nDCG。

## 离线验证与使用

在项目根目录执行：

```bash
.venv/bin/python scripts/build_golden_v2.py --check
```

该命令只读：核验发布字节/hash、原HTML、DOM/span、来源日期、数值列/财年、Decimal公式、Question及RAGAS格式。无数据库、嵌入、付费模型或外部网络。首次构建命令是同脚本不带`--check`；若已有发布文件则只验证，不覆盖。

当前`fr-rag golden/dev/test`仍固定读取v1，不会偷偷改用本集。显式加载并使用已有纯评分函数：

```python
import json
from pathlib import Path
from finrag.models import Question
from finrag.evaluation import score

path = Path('data/evaluation/golden_v2/golden.jsonl')
questions = [Question(**json.loads(line)) for line in path.read_text().splitlines()]
# hits由待测检索器返回，不得用gold补检索上下文。
# result = score(questions[0], hits)
```

RAGAS导出只保留每组第一个代表性原文。若需要OR替代证据，必须用主集及`score`按span映射到`Uxx:gN`后评分；不能拿文档ID直接当证据组ID，也不能将完整gold上下文喂给待测检索器。没有英文改写轨，`question_en`为空；原问题/既有阅读背景是中文输入契约。

## 审批与后续计算工具

用户明确采纳U01/U04/U06/U09/U10/U16/U18/U20并授权制作完整20题数据集；U02按用户意见将季度缺项列为正常边界。其余通过题保留，补充内容均需来源支持。发布状态为`user_review_accepted_agent_revised`；新rubric/qrels是Agent在该授权下整理，不声称用户逐行人工签认，也不声称已取得RAGAS质量分数。

后续财务计算适合拆为确定性工具：输入来源绑定的数值、币种单位、财年、GAAP/分部、持续/终止经营及公式名；输出公式、Decimal结果、舍入及来源。Skill可规定如何选口径、何时拒绝计算，不能替代计算执行。轻微差异无需上升为检索失败，但正式gold应尽量精确，以免噪声掩盖真正改进。本次只提供离线计算验算，不宣称已经接入生产财务计算工具。
