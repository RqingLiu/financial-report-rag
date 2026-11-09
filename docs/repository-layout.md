# 目录、模块和数据流

主入口只有一条：`serving → agent → retrieval / answering`。入库单独运行；离线评测不参与在线回答。README 展示总图，本页用于逐文件找代码。

## 文件职责

| 目录 | 文件 | 职责 |
| --- | --- | --- |
| `agent/` | `runner.py` | 建立一次请求、绑定 policy、调用图，转回原 API/trace 格式 |
| | `graph.py` | 编译 StateGraph；固定边、条件路由、节点记录及统一错误终止 |
| | `nodes.py` | catalog、plan、retrieve、fusion、context、gate、calculate、answer、validate 的函数适配 |
| | `state.py` | `RunState`、`RunContext`、工具回执与终态枚举 |
| | `policy.py` | 节点/模型调用上限，取消、deadline 与可选单请求金额检查 |
| | `planner.py` | Request / QueryPlan 契约、catalog、prompt、缓存、一次修复及计划校验 |
| | `scope.py` | 从原问与确认中提取财年/排除条件，不按固定公司词表工作 |
| | `regroup.py` | 可选证据目标重组，默认关闭 |
| | `reference.py` | 迁移期顺序流程对照/回退；默认不执行，验收后可评估移除 |
| `ingestion/` | `acquire.py` | SEC pinned manifest 下载及校验 |
| | `parse.py` | HTML → 文字/表格 block、DOM locator、规范字符区间 |
| | `chunk.py` | block → chunk、source spans、token proxy、稳定配置 ID |
| | `publish.py` | 原文身份/覆盖率预检、缓存 embedding、调用原子发布 |
| | `generalization.py` | 新公司 manifest 的 download / prepare / publish |
| `retrieval/` | `store.py` | PostgreSQL 表、catalog、原子发布、ANN/词法 SQL、过滤与受限超时恢复 |
| | `search.py` | QueryPlan → 搜索任务，query embedding、分组搜索、RRF 候选合并 |
| | `fusion.py` | 通用任务/分组交错；实际 RRF 实现在 `search.py:rank_records` |
| | `selection.py` | Top80 后选择 reranker，并串起 rerank 与 context 两个 trace 阶段 |
| | `rerank.py` | LLM 批次评分、来源行号、缓存与校验 |
| | `evidence.py` | 精排输入整理、原文去重/展开及最终证据选择 |
| | `context.py` | EvidenceStore、span 合并、表格/来源文本构建 |
| | `need_context.py` | 可选按 need 分配上下文的策略，默认配置未启用 |
| | `lexical.py` | BM25 postings/statistics 和同预算替换查询 |
| `answering/` | `generation.py` | 原问＋计划＋证据 → 回答；格式、need、引用 ID 校验及一次结构修复 |
| | `calculations.py` | 可选来源锚点＋有界 Decimal 表达式；默认关闭，尚非财务口径验证工具 |
| `providers/` | `llm.py` | DeepSeek、PaidClient、持久预留/结算账本、query embedding 基类 |
| | `embedding.py` | Voyage 缓存、批次与向量校验基础实现 |
| | `voyage.py` | 共用账本的 document/query embedding 和可选专用 CrossEncoder |
| | `traced.py` | 模型调用 span、请求级调用次数检查 |
| `core/` | `models.py` | Filing、Block、Chunk、Hit 及离线证据标签模型 |
| | `config.py` | 项目根目录与本地设置；密钥只从忽略的配置/环境读取 |
| | `files.py` | JSON/JSONL、hash、原子写文件 |
| | `tracing.py` | span、嵌套关系、时间与实际源码身份 |
| | `deadlines.py` | 串行离线实验的信号超时适配，不在 API 工作线程启用 |
| `serving/` | `cli.py` / `api.py` | 可信本地命令与 HTTP/SSE 入口、并发准入 |
| | `runtime.py` | 保持 `execute/query/resources` 调用面；编排已交给 agent |
| | `resources.py` / `config.py` | 创建每次请求的依赖、读取默认配置与共享账本 |
| | `errors.py` | 存储/provider 可公开的错误代码类型 |
| | `explorer.py` / `code_view.py` | 安全 trace 投影、固定代码白名单和当前行号 |
| | `static/` | 无需前端构建的 HTML/CSS/JS |
| `evaluation/` | `__main__.py` | 一个入口：check-data / build-intents / run / prepare-judge / export-judge / score |
| | `run.py` | 只接收 query-only 数据，调用当前 LangGraph；运行可能收费 |
| | `answers.py` | 保存回答的事实/数字/引用逐项评分及审核材料 |
| | `rubric.py` | 五维 Judge prompt 和导入判定的评分；不自动调用模型 |
| | `evidence.py` | 精确来源 span 的证据组 recall，无旧实验依赖 |
| 包根 | `cli.py` / `models.py` | 两个薄兼容入口，分别供已安装 CLI 和冻结数据构建器使用 |

## 一次 query 怎么串起来

| 顺序 / LangGraph 节点 | 输入 → 输出 | 实际代码 |
| --- | --- | --- |
| 接入 | question / as_of / confirmed scope → Request | `serving/cli.py` 或 `api.py`，`agent/planner.py:Request` |
| 建立 run | Request＋资源 → state / trace / control | `serving/runtime.py:query` → `agent/runner.py:execute` |
| `catalog` | 已发布文档＋截止日 → catalog fingerprint | `agent/nodes.py:catalog` → `retrieval/store.py:catalog` |
| `plan` | 原问＋catalog → needs/tasks/search queries | `agent/nodes.py:plan` → `agent/planner.py:plan_request` |
| 路由 | retrieve / clarify / insufficient | `agent/graph.py:after_plan`；后两项直接结束 |
| `regroup`（可选） | 原计划 → 目标重组计划 | `agent/regroup.py`，默认不走 |
| `retrieve` | 计划 → 带原文来源的搜索记录 | `retrieval/search.py` → `providers/voyage.py` / `retrieval/store.py` |
| `fusion` | 搜索记录 → 去重/交错候选 | `retrieval/search.py:rank_records`，最多 512 候选 |
| `context` | Top80＋needs → 精排结果和 evidence pack | `retrieval/selection.py` → `rerank.py` / `evidence.py` |
| `evidence_gate` | evidence pack → 有/无证据 | `agent/nodes.py:evidence_gate`；空证据或 retrieve-only 结束 |
| `calculate`（可选） | 来源操作数 → 表达式执行结果 | `answering/calculations.py`，默认关闭 |
| `answer` / `validate` | 原问＋计划＋实际证据 → 引用答案与终态 | `answering/generation.py`；validate 沿用已有结构校验结果，不增加 Judge 调用 |
| 返回 | 原 API status＋新增 agent 元数据 | runner → runtime 保存 trace → CLI / API / UI |

一个图节点不等于一次 API 调用，也不等于一个 subagent。`retrieve` 内部会有 query embedding 和多次 SQL；`context` 内部有 rerank 与 context_build 两种 span。详细输入输出仍在原 trace，节点层另记录输入输出数量、耗时、operation ID 和终态。

## 入库如何连接查询

`acquire → parse → chunk → publish.ingest_html → Voyage embedding → LiveStore.publish`。发布事务同时写入 documents、blocks、chunks、publications、postings、term_stats 和 index statistics。查询从 catalog / chunks / blocks 读取，不在每个问题中重新解析 HTML。新财报继续用 `scripts/ingest_manifest.py` 或 CLI `ingest`。

只保留 `finrag_live_ready`：16 份财报、4,961 个 chunk、一个切块配置。前一轮删除两套旧 schema 释放约 593 MiB，历史报告压缩净减约 1 GiB；[清理回执](../reports/public/cleanup.json)为历史记录。本轮没有重新入库或改写向量。

## 状态、预算和环境

- `RunState` 是单次运行的业务状态；live client / 连接不进入状态，放在请求独立的 `RunContext`。
- 图默认最多 16 次节点执行、32 次模型调用；原有 ≤192 SQL 尝试、Top80、8K / 24K 和累计计费停止线不变。金额预留与结算仍只有原 ledger 一套，新增 run/operation 归属。
- `run_policy.deadline_seconds` 与 `max_request_usd` 默认不额外设置；配置后在节点和外部调用前后检查。deadline 不会强行中断已在执行的 HTTP/SQL，原 provider/SQL timeout 仍有效。
- 没有自动付费重试、证据补查循环、持久 checkpoint 或跨请求记忆。`available_unverified` 表示有证据，不表示语义已经验证。
- 本机运行环境为 `.venv-migrate`，原 `.venv` 未替换。`requirements.lock` 为运行/开发依赖；`requirements-evaluation.lock` 包含完整评测依赖。官方 PyPI 的 LangGraph 1.2.20 与已验证的 RAGAS/community 组合已锁定。

[真实 StateGraph 导出](agent-workflow.mmd) · [迁移状态和下一步](rag-agent-refactor.md) · [源文件迁移记录](module-moves.json)。

图执行显式关闭 LangSmith 自动上报，继续使用本地 trace；没有新接入云端观测账户。

## 当前保留的脚本

`README.zh-CN.md` 的“scripts 里每个文件是什么”列出全部六个脚本、输入输出、命令和费用。它们是两个仍在用的数据配方、manifest 入库、只读 SQL 检查、暂存区安全扫描和公开结果校验。旧实验驱动、synthetic benchmark、vendor 树检索、prompts 和整个 archive 已删除；当前运行和测试不依赖它们。
