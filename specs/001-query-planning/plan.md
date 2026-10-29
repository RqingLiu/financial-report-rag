# Implementation Plan: 元数据驱动QueryPlan与有界RAG
Date: 2026-10-26 | Spec: [spec.md](spec.md)

## 2026-10-27：固定chunk/index的聚焦子查询对照（FR026–029 / SC009）

- 先隔离任务内query formulation：不重新识别scope或增任务，每个任务返回与原来相同数量的英文查询，各自说明对应need IDs、证据目标及table/narrative/both倾向；这些说明不变成新的SQL过滤，不扩大原需求。优先一个查询对应一类可独立取证目标；同槽内平衡数值与解释，不把所有财务项、风险和比较口径混为长串关键词。提示词不含具体公司/题号/金标准示例。
- focused_query.py独立契约/缓存/有界修复，复制原plan只替换dense_queries；wide使用原trace；focused用全部新查询；mixed固定原首条+聚焦首条、单查询任务同focused。各任务查询数、公司财年组与dense_k20固定，prepare_searches的任务/组/documents/k签名一致才调用。原粗排规则不变，Top80无来源启发式新奖励。
- 显式focus_experiment分phase：只读PG核验索引；全部refine/retrieve/shortlist保存后再进行候选评分；随后使用原问/needs给Top80新候选评分、旧同源候选复用旧评分，保留原表和逐题双预算，再离线评gold。全组context保存后才作最终离线评分；候选/Top80诊断与最终context分开，不将服务失败计作正常覆盖。没有生成答案。
- 本轮Budget(stop_usd=1.60)，原known约0.942、未知约0.009保留；DeepSeek/Voyage均走共享适配器，LLM串行绝对60秒上限。先U19/U14/U17检查调用契约，提示词固定后扩至20题；可续用已完成、与源/代码/prompt hash一致的题和评分缓存，不把对照失败后新prompt当原实验结果。
- 不自动启用，不新增依赖。按公司/财年/原文保持来源，读PG不写PG；文档需同步当前独立实验入口和所有结果。若纯聚焦牺牲上下文/解释，mixed作为预声明对照用于检验，不在看到gold后再发明新策略。

Pilot契约故障（未读gold）：v1 refiner在U19两次给2-slot任务输出3条查询，Pydantic拦截且未执行其检索；保留`reports/focused_queries/20261028T022135Z_6cc13c/`及付费响应。固定为v2-explicit-slots：请求显式列每任务exact_query_count，强调多need可共用slot，schema错误反馈具体字段与期望配额；不放宽查询/SQL预算。新run记录版本，旧pilot不伪装全20题结果。

三组检索完成后，wide context严格重放检查暴露共享chunk被新查询的distance字段覆盖；实际文本一致，但Hit.score不再字节一致，已拦截。修复为wide优先的canonical Hit映射并增加回归，不改变候选排名、精排评分或原文；新run复用相同refiner/embedding/已成功精排缓存，不改提示词、不重付有效调用，原run保留。

执行记录：主run`reports/focused_queries/20261028T022730Z_78c0ce/`（UTC，本地10月27日）。focused的Top80宏Recall82.24%、最终context69.81%，分别较原提高1.29和2.15个百分点；最终U02/U15改善、其余持平。mixed为66.78%且U19/U20退步，不推广。原全池focused少1组，U19宽需求仍未充分拆开，下一步应在同SQL预算下单独验证按证据类型重组任务，不把本轮任务内措辞改写当完整planner已优化。56项测试通过、1跳过；60份context/6759跨度及双预算、过滤/slot/SQL/索引/保护hash通过。本轮费用含pilot US$0.03394216，70个Top80新候选评分，旧未知预留保留，无生成答案、独立holdout或默认切换；README §8.10与Notion §5.12记录完整对照。

## 2026-10-27：Top80 粗排离线实验（FR023–025 / SC008）

- 新增独立 coarse_ranking / coarse_experiment 模块，不修改 pipeline 默认或旧融合函数。固定8组策略、Top80：current、global_rrf、current_dedup、global_rrf_dedup、quota_rrf_dedup、lexical_rrf_dedup、quota_lexical_rrf_dedup、cosine_dedup。RRF常数60；局部BM25固定k1=1.2、b=0.75，按任务/公司财年局部词项相关性与原dense列表排名等权融合，不做参数网格。只用通用Unicode词项，不引入公司/财务术语表。
- quota为每个runtime任务/公司财年组先取1个候选，其余名额按全局相关性；同一候选可满足多个组的候选表示，仅是配额代理。来源去重用现有span_overlap、阈值0.9，记录被跳过候选，禁止语义改写或混淆报告FY/事实期间。
- phase1：从query-only字段、原search_records构造所有shortlist并落盘。phase2：显式加载已保存DeepSeek评分，以原select_reranked、compact=false/balanced=false和相同逐题证据+完整prompt实际预算构建真实context；从processed Blocks读取原文，与保存的候选原文逐行比对，不连DB、不初始化API客户端。phase3：读取gold评分，独立比较shortlist与最终context，不把块级模型代理当gold。
- 报告包含输入/代码hash、保护hash、各题差异、选取原因/耗时、来源/预算校验与数据集差异。旧v1仅做标注结构/任务分布汇总，不用其test做本轮选型；20题v2全是dev，复杂度/单题证据要求差异单列。若没有同时改善最终覆盖与关键退步，不默认推广。现有精排分数跨批复用只供筛查，不作真实服务验收。

执行记录：`reports/coarse_rank/20261028T014418Z_b5443e/`，8组预声明策略全部完成，新增API/费用0。全局RRF的Top80覆盖82.18%、最终context68.77%，仅较原67.66%小幅改善且U14/U17退步，默认保持。原16组候选缺项均未召回目标Block，未命中同块缺行；其中U19占10组，下一轮应单独验证聚焦查询/表格路由，不将该诊断冒充原因已确定。50项测试通过、1项旧DB跳过；160份context双预算/来源/as_of与保护哈希通过，README §8.9 / Notion §5.11记录全部结果，§3.4 / §5.10流程图增加独立离线分支。

## 本次设计
- `planning.py`：Pydantic请求/实体/need/task/plan契约、来自source manifest与SEC submissions/可选registry的公司catalog、通用ASCII边界校验、LLM planner JSON及业务校验。未知别名交给模型映射，规则只做验证和确认范围保护，不用财务词表。材料截止日/实际事实年与报告年分开。
- `planned_retrieval.py`：直接调用既有参数化PG Repository.search，使用受校验doc IDs；不调用旧公司regex/glossary。不加载全部Blocks/树；需要时按ID批量取Block。每任务最多2向量变体、分组候选、可配置全局配额。缓存真实query向量。
- `context.py`：来源span去重、按任务/期间覆盖的预算选择；紧凑表格可扩展同源原表，保留原文span并按真实token重新预算，10条/8K上限不变。大表保留行块，行/列理解与OCR不是已解决问题。
- `pipeline.py`：新显式CLI/service，先保存计划→检索→原始候选；同候选离线对照dense、等权RRF、加权RRF及上下文策略。保留旧baseline目录字节，所有新运行唯一目录；JSON trace复用现有浏览器/评分器。
- `answering.py`：按运行时needs生成结构化逐项答案，引用可验证ID、缺项仅指当前context、不把检索失败写成年报没披露；完整性/引用/截断校验。财务计算工具仍后续，模型计算不得标为已验证。
- `generation.py`：在已有预算客户端上增加受控json_object/purpose选项，默认baseline兼容。结构/业务校验失败最多一次有trace的JSON修复；服务错误不重试；仍非法则明确error，不放宽条件降级。保留usage与价格依据。
- `configs/companies.json`：把采集公司的CIK/name/可选aliases移出代码；新公司注册无需编辑算法。新财年/报告公司从metadata自动进入catalog。不会自动证明新公司的财年标签与表头已正确解析。

## 固定参数与可扩展性
config独立于冻结best.json：max_tasks4、max_variants2、max_task_company_year_groups12、max_search_calls192、max_unique_candidates512、dense_k20/fts_k20、max_context_items10、8K代理tokens、max_table_tokens1200。超限在调用前报告resource_limit，不悄悄截掉公司或财年。catalog过大超过6K代理token先要求缩小范围；本轮不是大规模压测。

## 对照顺序 / 启用规则
1. 记录旧20题结果及dense/fts/RRF离线对照，审查硬编码/复杂度。
2. 单独校验catalog/约束；跑planner+同索引候选，不触碰gold；同候选对照dense/等权/加权RRF。默认候选dense权重1、fts0.35是实验参数，不声称普遍最优。
3. 同候选、同10/8K比较rank-only与任务覆盖/同源表格组装。先检索20题，再生成6题；无接口/预算问题可扩至20题。
4. 首轮推荐依据dev宏召回与全证据完整率（完整率不低于原baseline）；报告各题退步。没有独立holdout，不替换旧默认生产入口。精排后续先做候选标注，再测reranker，与现有查询/融合解耦。

## Constitution / Tests
复用PG/索引、gold执行后评分、不改冻结hash清单内核心文件；受校验计划只能检索；所有新调用共用4.5美元停止/5美元总授权，未知计费保留。测试新公司、中文连写、排除/期间/as_of、JSON非法、依赖/资源超限、来源扩展确实进入context、缺项与引用结构。原回归继续运行，真实DB只读集成，固定语料未做压力测试。

## 2026-10-27：上下文预算离线增量（FR018–019）
- 固定`20261027T034153Z_198f65`的20份plan/dense候选、80候选窗口、8K代理token、原表扩展和去重；不调用planner/embedding/generation。对照rank10、rank30、need_budget10、need_budget30，条数是安全上限而非必须填满。
- `need_budget`：根据plan里need→task关系对任务分配权重，候选的任务/来源排名为相关性代理；对同一需求/来源的累计贡献使用递减收益、按token成本归一，单块可服务多个需求。报告财年来源仅用于分散来源，不作为实际事实财年的证明；无语义判定不称需求已满足。
- 新策略独立模块/显式配置，旧rank/coverage行为不变。所有真实文本和span预算后才计覆盖；选择记录增益/成本与关联需求，来源仍按需从PG只读批取。
- 新replay命令独立于在线API资源初始化；只导入选择器及只读PG，不要求DeepSeek客户端，不写DB。唯一新报告目录含manifest、逐题上下文与追踪、结果/对照表；选择阶段结束后才读取gold。
- 主要验收：同条数对照分离选择器收益与放宽条数收益；报告宏/微Recall、全证据齐全、token/条数/耗时和逐题退步，所有20题仍属dev。未实施补检索/分层LLM提取/财务工具，不推断答案正确性。

实际结果见`reports/context_budget/20261027T072215Z_6c99b5/`：rank30同8K比rank10提升10.75个百分点且无逐题退步，平均实际输入从4,326增至7,957；need30为45.16%，未胜rank30的47.34%，有关键财务表格退步，不默认启用。条数与token变化不等价于相同实际成本。42项测试通过、1项旧可选DB跳过；新增模型费用0，Notion §5.8同步。

## 2026-10-27：固定实际上下文成本的精排（FR020–022 / SC007）
- 对全部原候选（29–573/题）用已有DeepSeek Flash做批量语义精排，不先截80；使用原问/plan的needs、来源元数据和原文行。模型返回每候选0–4相关性、支持need IDs、原文行范围；每批≤32候选、候选序列化≤16K代理tokens，完整prompt另含问题/needs/系统指令，JSON校验，最多一次schema修复，费用共享原5美元账本。单轮先pilot，再全20题；额外精排费用单列，不另接服务/本地模型。
- ablation：原rank30、原80内LLM排序、全候选LLM排序、全候选LLM排序+原文压缩；复用同份评分缓存，不重复付费。所有选择在gold读取之前完成；脚本运行时不导入标签。
- 每题证据token上限取上一轮rank30实际使用值（平均7,956.75，均≤8K）；完整答案输入通过复用answer消息构造计算，不能超过该题rank30同提示词序列化代理token数。仍保留≤30条安全限制。另可零额外API按原rank10实际用量重放，避免把4.3K→8K当同成本收益。
- 原文行压缩来源为PG Block实际slice，表格保留来源表头/邻近短标题单位上下文；正文不由模型改写。新上下文Hit以实际span重建、保留parent chunk lineage，禁止原Hit跨度与压缩正文不一致。维持现有表头启发式局限，不声称事实库/列语义已解决。
- 只读PG核验当前626个table blocks，structured rows/source_rows/raw_html均在库；历史Block另在库，非本轮删除范围。正常检索仍对渲染文本做dense，本次不升级成结构化指标SQL。
- 不更改生产默认、不重切/重嵌入、不接Agent框架/计算工具、不生成最终答案。最终选证据达70%与否如实记录；费用、约束/原文一致性、逐题进退和独立holdout缺失同时报告。
- 实测异常：普通HTTP read timeout无法约束持续返回空白等情况下的总等待；中断最后悬挂请求，保留US$0.0093642未知计费预留。新增serial POSIX CLI的60秒absolute deadline，计费未知仍保留预留；验证输入/selector/prompt hash后复用19题完成结果与成功批次，人工控制的一次续跑仅新增最后1个候选的请求，不自动重试成功批次。Windows/多线程不能直接使用此signal wrapper。

实测结论：前80内精排67.66%，全候选精排71.45%（17题改善/3持平/0退步）达到70%dev宏Recall目标；保留原表版本为更稳妥候选。原文选择+need分配75.24%但U12丢利息/净利润行。每题双实际预算未增，平均证据7956.75→7826.75，完整输入17428.15→16518.40；不拿更早4.3K实际预算的56.95%混报。主结果`reports/rerank/20261027T170703Z_9a25db/`，47项测试通过/1跳过，新增usage列表价估算0.76523250美元、另0.0093642未知预留。README §8.8 / Notion §5.9同步；无新答案、独立holdout或默认替换。
