# Evaluation evidence and limits

<a id="evaluation-contract"></a>

## Finalized evaluation design — 2026-11-09

本节保留2026-11-09评测契约，后面的历史结果保留原数据集、分母和条件。**截至2026-11-12：另选的41条规范意图已真实跑完并完成离线初评；33条pilot中的口语、澄清和边界行为不因此视为已批量实测。** 本节完整设计不是全部已实现的功能清单；命令与范围见[pilot说明](../data/evaluation/pilot/README.md)和[41题数据说明](../data/evaluation/baseline41/README.md)。**最终回答/行为决定是否改进，中间Recall用于定位损失。**

本轮流程与环境报告在本地`reports/current/baseline41_20261111_default/review/evaluation-report.md`，逐题判定在同目录`review.md`；完整回答/trace/评分不公开上传。本轮为本对话辅助的离线初评，不是付费或独立Judge；运行时`validate`仅做结构结果/终态处理，离线评测由`evaluation/answers.py`和`rubric.py`导入判定并验证/计算，不能混为同一步。

### 1. 样本、分母与成功规则

- `N`：manifest在运行前选定的案例数；`E`：实际开始执行的案例数；`S`：通过该类全部预先冻结验收项的案例数。报告**执行覆盖率 E/N**、**整批任务成功 S/N**、**已执行成功 S/E**，同时列未执行、错误、预算中止。未完成批次不得宣称全量通过或与完整批次直接比均分。
- 可答题的严格任务通过沿用逐项规则：必答事实正确、适用数字/引用/边界通过、无重大范围或财务错误、无待判项。五维rubric单独报告，不将1–5分换算成“正确率”。澄清/范围外/缺资料题采用其行为验收项，不强求生成财务答案。
- 对分母为0或标签不足的指标输出`null / not_applicable / not_judged`及原因，不能填1或0。每个均值列实际`n`；宏平均先逐题再平均，微平均汇总分子/分母。原题、变体及近重复意图同split，并加报父family等权结果。
- 先保留五维量表、数值容差及原严格pass含义；新增原子验收点/证据替代关系须在实验前确认。所有失败保留，不能通过删题、改参考值或缩小必答范围“提高”分数。

### 2. 最终结果：主指标

| 指标 | 计算方式 / 评判依据 | 分母与限制 |
| --- | --- | --- |
| Task success | 按上文S/N和S/E，同时列E/N | 覆盖正确回答、澄清、部分回答与有理由的不支持；技术错误不是正确拒答 |
| Completeness / Truthfulness / Faithfulness / Relevance / Clarity | 既有五维1–5锚点；各维均值、分布及逐题差，不合成总分 | 财务答案适用时评分；null、未交付数量另列。Truthfulness对参考/原文；Faithfulness只对实际runtime context |
| 必答事实覆盖 | 每题`Σ credit(f)/必答事实数`；正确1、部分0.5、其余0；加报macro/micro | 必答项来自独立标签，不取Planner自行生成的needs。运行失败/缺答的对应必答项为0；待判单列 |
| 必需数字覆盖 | `通过的必需数值检查 / 本批适用检查`；区分exact、容差内、轻微舍入、错误、缺失、待判 | 缺答/运行失败仍保留其适用检查；纯披露缺口没有不存在的必需数。加报去重检查ID数，避免共享检查冒充独立观测 |
| 已输出数字正确率 | `正确的已审核且可判定数值主张 / 已审核且可判定数值主张` | 另报`可判定已审核主张/答案中全部识别的数值主张`、未知和漏审数。主张按公司/指标/期间/单位/口径/值定义，不按数字token计数 |
| 引用有效率 | `属于本次实际context的有效引用链接 / 所有受检引用链接`，重复链接去重 | 只说明ID/范围有效，不说明支持内容。无引用时N/A，不能当引用质量100% |
| 引用支持率 | `附带引用集合足以支持的受检主张 / 有引用的受检主张` | 按整组引用共同判断支持；引用存在或邻近数值相似不等于支持 |
| 引用覆盖率 | `有有效且充分来源支持的需引证主张 / 全部受检需引证主张` | 无引用主张进入分母；首轮小批尽量审核全部重要主张，抽样时标审核覆盖，不能说成全文精确率 |
| 重大错误率 | `至少一项重大公司/期间/单位/口径/公式/事实/引用错误的财务回答数 / 受检财务回答数` | 缺答单独降低交付/覆盖，不把沉默当正确；新增关键主张也须检查，不能只匹配参考中已有句子 |

### 3. 路由、范围与澄清

`expected_disposition`与实际语义行为比较，不只检查Planner的action字符串。标签包括：回答、部分回答、澄清、资料不足、不支持任务；技术错误/取消/预算终止另记运行终态。一个case允许多个合理动作时，实际动作须属于允许集合且满足解释/约束要求。

| 指标 | 计算方式 |
| --- | --- |
| 行为正确率 | `动作及用户可见响应均符合标签的案例 / 已执行受检案例`；加报按类型混淆矩阵 |
| 澄清Precision | `应澄清且正确询问缺失条件的案例 / 实际请求澄清的案例` |
| 澄清Recall | `应澄清且正确询问缺失条件的案例 / 标签要求澄清的案例` |
| 不必要澄清率 | `信息已足够却要求补充的案例 / 标签信息足够的案例` |
| 边界遵守率 | `正确说明不支持/缺披露且未编造或越界执行的案例 / 对应边界案例`；业务范围外、能力未支持、库不覆盖、缺披露分别报 |
| 错误拒答率 | `可答却无正当理由拒绝整个请求的案例 / 标签可答案例`；部分可答请求被整体拒绝也单列 |
| 澄清后恢复 | 使用冻结的用户补充输入，`正确吸收补充并完成后续任务的案例 / 已确认范围且有后续标签的案例`；第一轮不能读潜在映射 |

澄清应只问必要缺项；不能重复询问已给公司、默认“最近三年”，或用答案暗示诱导用户确认。第一轮澄清成功不自动证明第二轮恢复成功。库不覆盖与业务范围外不是同类；依赖故障不得伪装任一边界。

### 4. 中间阶段：用于归因

令`Gq`为题q的必需证据组，组间AND；每组可有多个替代来源，组内OR。当前span scorer仅在同document/block的返回原文区间并集完整覆盖一个允许摘录时命中。选中的同事实跨报告替代关系先复核再冻结；不能拿只覆盖一个数值的切片冒充覆盖表头/单位等未标范围。

| 阶段 / 指标 | 计算方式 | 注意事项 |
| --- | --- | --- |
| Planner意图覆盖 | `保留的必需意图 / 标签必需意图`，先逐题再macro | 搜索措辞不做逐字匹配；合法辅助搜索不自动算新增幻觉 |
| 无依据新增目标率 | `经审核无依据的新增目标 / Planner提出的目标` | 未标但合理的目标先待判，不直接当错误 |
| 约束保留率 | `正确保留的显式公司/报告FY/指标期间/as_of/否定/确认约束 / 所有应保留约束` | 同时报至少一次重大范围漂移的题数；标签隐含条件不能算用户已知 |
| Evidence-group Recall@k | `前k候选中命中的组数 / |Gq|` | 固定报k=10/20/80；候选总池也单报。该指标不是相关chunk数量Recall；纯边界/澄清不计 |
| 粗排保留率 | `Top80已覆盖组 / 候选池已覆盖组` | 同时报Top80对全部gold的Recall；池里没有证据时该保留率N/A |
| 最终Context证据Recall | `实际交给生成器的context命中组 / |Gq|` | 必须评实际选取span，不能用原完整chunk或扩展前文本冒充 |
| MRR@k | 每题第一条相关结果排名r，取`1/r`；前k无相关为0，再平均 | “相关”需人工qrel；部分标注只能叫已标注证据的MRR，不声称完整相关性。深度k写入配置 |
| Precision@k（条件启用） | `前k中判为相关的结果数 / k`；返回不足k时未填名次贡献0，同时报返回数 | 按去重结果单位。未返回名次不同于已返回但未标注的chunk；后者不能当负例，判断不足不出完整Precision。按实际返回数作分母的比例另命名ReturnedPrecision |
| nDCG@k（条件启用） | `DCG/IDCG`；`DCG=Σ(2^rel_i−1)/log2(i+1)`，rel=0/1/2 | 只在明确的、已判候选池及给定qrels范围内计算，注明judgment coverage；IDCG=0则N/A |
| Context Recall（条件启用） | `被实际context充分支持的参考原子事实 / 适用参考原子事实` | 需要事实→来源支持判定，与严格span组Recall分开命名；不是自动声称已跑RAGAS |
| Context Precision（条件启用） | 对排序context标`v_i∈{0,1}`，计算`Σ(P@i×v_i)/Σv_i` | 这是已判context列表内的排序效用，另报有用context比例与重复率；不能替代事实找全程度 |
| Empty-result rate | `成功执行检索但候选为空的检索请求 / 成功完成检索的请求` | 不把SQL错误、未执行澄清或预算中止当空结果；另报最终空context率 |

当前qrels不穷尽相关结果，故首轮默认启用证据组Recall/阶段保留与人工诊断；Precision/nDCG/Context Precision不凭现有标签硬算。若排序问题成为主要瓶颈，再对固定Top-k池补相关性分级。条件指标未实现或未打标时明确N/A，不为填满看板增加无效模型调用。

### 5. 运行、Judge与Bad case

- 每例记录LLM调用、embedding/rerank外部调用、SQL实际attempt、结构修复、重试、补查、cache命中、token、已知费用和未结预留。`重试率=出现技术重试的执行数/E`；`修复成功率=修复后有效的次数/结构修复次数`，两者不混算。另报`技术失败率=技术异常终止的请求/E`，不把正常澄清/资料不足计入技术失败。
- 每例端到端耗时从接收到终态，含等待/资源初始化/修复；span用来拆解原因。`p95=排序后第ceil(0.95n)个耗时`。冷/暖、成功/错误分报；本轮n很小，只报经验分位和n，不当生产SLO/RPS验收。
- `每次成功任务费用=本批所有已知新增费用/S`，失败消耗也算；S=0则N/A。未结预留单报，金额不等于实际供应商账单。Judge/API费单列，不和被评系统费用混淆。
- Judge沿用五维rubric和逐项diagnostics。先用6份已保存回答校准，另加受控的漏答/错年/错单位/无支持引用版本检查敏感度；这些是评分器测试夹具，不冒充真实生成答案。固定版本、盲评顺序、精确摘录与hash，人工检查全部重大错误/分歧；同模型自评不作独立认证。报告人工与Judge分歧数；样本足够再估一致性统计。
- 所有运行失败、错误路由、重大错误、回归、Judge争议进入bad-case清单，另选少量成功对照。每条含case/run、期望与实际、受影响检查、首个可观察偏差、相关span/来源/代码、假设根因、离线验证办法、修复及回归结果。允许多个原因，不能仅凭一个低Recall就断言embedding有问题。标签缺陷与系统缺陷分开；经确认的标注修订版本化，不回填历史分数。
- 诊断顺序：资料是否发布且可得 → 范围/needs → 候选池 → Top80 → 精排/实际context → 生成/计算 → 引用/最终输出。冻结上游做对照重放才能加强因果判断；历史精简trace缺候选时直接写“证据不足无法归因”，不能补造。

### 6. Framework、Trace与交付

`已确认标签 → runner/replay → 本地真实trace → 阶段规则评分 + 数字/来源校验 + 离线Judge → 统一results → 配对比较/Bad-case复盘 → 回归`。

- 复用`finrag.evaluation`，以pytest验证确定性契约与故障路径。RAGAS作为可选指标适配；Trace平台不负责制定财务rubric或代替人工审核。
- 本地trace/Trace Studio是首轮事实记录与查看入口；新增评分和bad-case表链接同一run/span，不重建第二套可视化平台。完整I/O、真实模型/Prompt/config/index/source身份保留本地；新报告包括manifest、逐题results、汇总report与trace引用。
- **LangSmith决策：可选，非首轮前置依赖。** 官方支持LangGraph及其他SDK的trace、离线/在线评测和span级人工反馈。现有runner显式禁用云端tracing，且自定义DeepSeek HTTP/SQL并非开环境变量就全部自动记录；未来需设计可选span适配、ID映射和白名单脱敏。平台失败不得改变答案、触发模型重试或影响账本。[追踪](https://docs.langchain.com/langsmith/trace-with-langgraph) · [评测](https://docs.langchain.com/langsmith/evaluation-types) · [人工反馈](https://docs.langchain.com/langsmith/annotate-traces-inline) · [脱敏](https://docs.langchain.com/langsmith/mask-inputs-outputs)。
- 2026-11-09官方Developer标价$0/seat、含每月5k base traces；超量、保留及模型评测可能另计。未据此承诺总费用为零，不开Engine/自动Judge；未来有账户配置后再显式启用，当前不索要或上传凭证。[官方价格](https://www.langchain.com/pricing)。


## Historical evidence and existing implementation

The [atomic v3 draft](../data/evaluation/golden_v3/README.md) separates the 20 compound questions into 81 independently assessable intents, with scoped references and labels. All remain development data. Use its R0/R1/R2/R3 protocols to distinguish retrieval-only, planner-plus-retrieval, end-to-end and original-compound evaluation. Old aggregate scores below retain their original datasets and denominators; they are not v3 baseline results.

## Data contract

The current complex-question dataset has **20 development queries,225 required evidence groups and123 numeric checks**. Questions and revised references were reviewed during development; this is not an independent held-out benchmark. Same-intent oral variants remain in the same development split. The older60-question v1 evaluation is frozen and uses a different task mix.

- `data/evaluation/golden_v2/retrieval_queries.jsonl`: query-only input, including original background/cutoff. No gold evidence goes to the runtime.
- `golden.jsonl`: mandatory evidence groups, with AND across groups and OR across alternative excerpts.
- `rubrics.jsonl` and `numeric_checks.jsonl`: facts, boundaries, formula inputs, periods and tolerances.
- `reference_answers.md` and `evidence_catalog.jsonl`: human-readable reference/source audit material.

Span-based group recall measures whether mandatory source text was recovered; macro averages per question, micro counts groups. Candidate recall, Top80 recall and final-context recall describe different pipeline stages. They are not answer accuracy. Labels do not exhaustively judge all chunks, so unlabelled chunks cannot automatically be counted as irrelevant for Precision/nDCG.

## Historical controlled development comparison

The [experiment guide](experiments.md) covers v1 selection, context/rerank/focused-query studies and ANN conditions. [Public exports](../reports/public/experiments/README.md) include source hashes and per-question counts; `python scripts/verify_public_evidence.py` recomputes aggregate arithmetic without raw paid traces or DB credentials.

| Planner / coarse retrieval | Reranker | Candidate macro recall | Top80 recall | Final-context recall |
| --- | --- | ---: | ---: | ---: |
| Original dense | LLM | 94.47% | 80.95% | 67.66% |
| Dense + BM25 replacement | LLM | 94.77% | 83.87% | 71.53% |
| Evidence-objective regroup | LLM | 95.62% | 79.19% | 67.62% |
| Original dense | CrossEncoder | 94.47% | 80.95% | 59.20% |

Same development questions, selected chunks, Top20 per SQL job, Top80 reranking and matched context budgets;342 SQL jobs per arm. Controls reused saved plans/candidates and some paid reranker results. These are primarily exact-search, saved-plan comparisons, not20 independent cold end-to-end HNSW production requests. The best development arm was not automatically promoted: current serving remains dense+LLM. The separate69.81% focused-query result used a different experiment and should not be mixed into this table.

The diagnostic lesson is candidate→shortlist→context loss: changing only embedding/chunking is not justified when the full pool already contains most mandatory evidence. More complex planning also needs a coarse-rank allocation strategy; greater pool recall alone did not improve final context.

## ANN and engineering checks

The historical2,759-chunk corpus had59 scoped queries with mean HNSW/exact Top20 overlap98.98%, with actual index-plan checks. The later10k/30k/100k expansion used locally perturbed vectors, not new financial documents. Strong synthetic clusters caused an HNSW construction pathology. It demonstrates distribution/parameter sensitivity, not real financial-corpus recall or RPS. Large synthetic fixture tables were removed; recipes/results remain local.

The correctness update adds company-alias/FY counterexamples, typed confirmations, short/fat table preservation, pre-embedding conflict checks and exact reproduction of the original selected chunks. Its historical local DB-backed suite passed87 tests and clean-checkout Linux CI passed76 with11 skips; these receipts are preserved rather than overwritten. The newer guide/UI release passed101 local DB/corpus tests; see [current validation](../reports/public/project_guide_validation.json). DB tests require `FINRAG_INTEGRATION=1`.

## Still required before a quality claim

1. New natural questions and new intents from Alphabet/Amazon; reserve an unseen holdout before tuning.
2. Check scope/need decomposition, factual completeness, actual-value FY, units, numeric/formula accuracy and claim-level citation support.
3. Review no-answer/partial-answer behavior; a citation ID existing is not proof that the cited text supports the claim.
4. Compare cold/warm end-to-end latency/cost; test provider/SQL failures and concurrent publication/query behavior. No production p95/RPS claim is made.

RAGAS schemas and ID-based metrics assist evaluation. RAGAS question generation or an LLM judge has not independently certified this project. Current numeric checks verify reference arithmetic; they are not a production financial calculator.

## Offline answer-scoring pilot

The [answer evaluation specification](../specs/009-answer-evaluation/spec.md) and [replay guide](../specs/009-answer-evaluation/quickstart.md) describe the six-answer development pilot. An offline evaluator imports provisional judge judgments, checks excerpts against the saved answer and its citations, and compares mapped numeric observations with the frozen checks. A judge still identifies the metric, period and scope in free text; the numeric comparison itself is deterministic. Citation support is assessed for rubric facts, not every sentence in the answer.

The pilot uses historical traces and costs no API calls. A later current-default development run is described below. Human calibration and an independent holdout remain pending. Retrieval recall remains useful for locating evidence loss; answer scores determine whether a change improved the result.

The [whole-answer rubric](../specs/009-answer-evaluation/contracts/whole_answer_rubric.json) adds explicit 1–5 anchors for completeness, truthfulness, faithfulness, relevance and clarity. `export-judge` prepares reusable prompts; `score` imports reasoned verdicts without calling a model. Keep the five scores separate and use item-level checks to locate errors. An answer can be faithful to its context while citing the wrong excerpt, or truthful but incomplete.

Detailed local trace/HTML/paid-response files are excluded from the public repository. Compact public receipts live in `reports/public/`. Retired experimental drivers and the archive have been removed; historical results document their original conditions. Current runtime evaluation remains available through `python -m finrag.evaluation`.

## Current-default answer baseline (2026-11-07)

`python -m finrag.evaluation run --out reports/answer_eval/<new-run>` executes the same 20 query-only requests through the actual serving runtime. It preserves exact cache behavior, configuration/source fingerprints and individual attempts. Resume skips saved attempts, including failures; it does not rebill them. The optional `--stop-usd` overrides only this experiment's cumulative ledger stop and requires explicit budget authorization. Serving defaults are unchanged.

All 20 were attempted: **17 delivered answers, two SQL timeouts and one answer-schema rejection**. Newly estimated peak-list cost was **$0.4773**, within the authorized $2.20 cumulative stop. Document vectors were reused; the current catalog changed planner inputs, so historical planner/rerank caches did not match this run.

Using the same rubric on the same 17 delivered questions, completeness rose **2.71→3.41/5**, while truthfulness remained **3.53/5**. Numeric passes rose only **40/108→42/108**. Across all 20 attempts, including failed deliveries, numeric passes fell **50/147→42/147**. These are required-check coverage rates, not the accuracy of every number in the answer. Missing and failed answers remain in the denominator. Historical versus current comparisons are descriptive, not concurrent single-variable A/B tests.

U11 is the largest numeric regression: the answer had source values but omitted all requested absolute-growth calculations, reducing passes from 15 to zero. Other failures include a wrong trend summary, calculation after premature rounding, and calendar-year versus report-FY confusion. Better evidence coverage alone did not solve those generation errors. Provisional item and whole-answer judgments, exact excerpts and paired comparisons are saved locally under `reports/answer_eval/current_default_20/`; human calibration is still required.

## Six-case reliability and arithmetic follow-up

Only U01/U02/U04/U06/U11/U15 were rerun, twice, retaining both rounds. Both delivered 6/6 answers versus 3/6 in the default control; answer-structure repair was exercised on U15. The original SQL timeout was not reproduced in read-only hot-cache probes. A real PostgreSQL timeout injection verified rollback and one bounded recovery, not the original root cause.

The second arithmetic candidate used identical plans and evidence for U04/U06/U11. Numeric passes were U11 **0→17/20**, U04 **3→0/9**, U06 **1→3/16**. Across all six, including the three recovered deliveries, required numeric passes were **4→46/84**. That aggregate is strongly affected by delivery recovery and must not be described as uniform semantic improvement. U04 developed a new growth-rate summary error; U06 still confused cross-period accounting effects and an unsupported zero value. The first round also exposed a truncated worksheet and an inverted turnover-days derivation.

Default changes are limited to bounded SQL recovery/diagnostics and one answer-contract repair. The arithmetic tool and experimental generation prompt remain explicitly opt-in. Source-literal checks plus correct Decimal arithmetic do not prove financial operand/formula selection. No company or question-specific rules were introduced. Full local verdicts and paired controls are in `reports/answer_eval/targeted_fix_v2/`; frozen Golden values/tolerances and the original 20-question report were not changed.

## Raw query and rewrite evaluation

The 81 derived questions are **canonical intent cases**. They can exercise planner code and test scope/intent preservation, but already name companies, fiscal years and tasks clearly. Their scores cannot establish that rewriting improves real user input. The original 20 compound requests test decomposition and budget allocation; they are also curated development material, not organic production-query logs.

Maintain three linked views rather than replacing one dataset with another:

| View | Input | What it measures |
| --- | --- | --- |
| Canonical intent cases | One explicit task with local references/rubric | Controlled retrieval, context and answer failures |
| Raw-query paired cases (not yet built) | Human-written or clearly labelled mock input; trusted conversation context when applicable | Rewrite, ambiguity handling, constraint preservation and downstream utility |
| Original compound suite | Complete multi-intent request; child mapping used offline only | Task decomposition, shared budgets and end-to-end completeness |

For each raw case record `id`, provenance (`human_authored` / `synthetic_mock`), raw question, supplied context, disclosure cutoff, related intent/family, accepted intents and constraints, expected route (direct/rewrite/clarify/out_of_scope), and review status. Labels and canonical targets stay in judge-only files. A vague request can legitimately require clarification; do not invent a year/company merely to score retrieval. Any follow-up turn and user confirmation are separate recorded inputs.

Start with a small balanced set covering clear questions, colloquial references/paraphrases, exclusions/negative constraints, ambiguous company/year references, and genuinely unavailable material. Mock cases are useful development tests, but need their own label and cannot be claimed as user observations. Keep variants, parent questions and overlapping intent families in the same split. New Alphabet/Amazon intents can supply a holdout only if reserved before tuning; paraphrasing a tuned intent does not create one.

Run paired controls with the same index, company/date access scope, model, total SQL attempts, candidate/context caps and answer rubric:

1. **Raw direct:** retrieve using the raw query with only application-validated scope; no oracle child queries.
2. **Current planner:** the same request through current rewrite/decomposition and retrieval.
3. **Proposed agent:** only after equivalence migration, compare bounded feedback disabled/enabled on the same requests.

A fixed canonical-search-plan oracle is a diagnostic upper control, not an online baseline. Original+rewritten parallel search must share the same total search budget, rather than doubling it. Stratify cases needing clarification instead of forcing an arbitrary interpretation into a recall denominator.

Score intent coverage, unsupported intent additions, company/FY/as-of/exclusion preservation, and clarification correctness. Then compare candidate/context evidence recall and the unchanged answer rubric: completeness, truthfulness, faithfulness, relevance, clarity, numeric checks and citation support. Report regressions and cost/latency per case. Do not grade rewrite wording by exact string match or infer semantic quality solely from evidence recall. No raw-query robustness score or new paid evaluation was produced in this cleanup.

The full historical archive has been deleted. Compact answers/evidence and comparisons remain under `reports/current/`; old large-run paths cannot be restored. See [current result navigation](../reports/README.md).


### Execution controls in evaluation

The batch runner now calls the same `serving.runtime.query` lifecycle as CLI/API; it no longer wraps models in a separate signal deadline. Each result records effective `agent.usage.policy`, provider/search/repair counters, cost reservations, terminal outcome and setup-through-cleanup `duration_seconds`. Historical traces keep unknown fields unknown. Bad-case review must distinguish invalid output, budget/deadline/cancel stops and dependency failure from unsupported disclosure.

An explicitly authorized `--batch-usd` adds a cap in the **same persistent ledger**. Its identity is tied to the output directory; resume counts prior known spend and unknown reservations and rejects a changed batch limit. Existing manifests require a new output directory if code/config identity changed. This flag does not raise the cumulative stop or authorize a paid run. See [execution policy](rag-agent-refactor.md#6-orchestrator与执行策略). The offline tests use temporary ledgers and MockTransport; they measure controls, not answer quality.
