<!--
Sync Impact Report
2026-10-26: 1.0.0 -> 1.0.1 status-only baseline correction; core principles unchanged.
Version: template -> 1.0.0 (initial adoption, 2026-10-25).
Principles: source/period integrity; evidence-based evaluation; bounded changes;
deterministic operations; simple reproducible engineering.
Added: baseline, document ownership, workflow, governance.
Removed: unused examples and placeholder rules.
Templates: spec-template.md, plan-template.md, tasks-template.md updated.
Installed skills retained upstream; no extension hooks installed.
Runtime guidance: AGENTS.md and README.md updated.
Deferred placeholders: none; existing features are not retrospectively specified.
-->
# Financial Report RAG Constitution

## Core Principles

### I. 来源与期间必须可核验

事实、段落和表格必须保留公司、document/accession、实际期间、申报时点及原文定位。
报告财年与事实期间分别处理，`filed_at <= as_of` 是披露时点约束。
改写不得改变用户确认的公司、期间、否定条件或比较范围。
关键歧义必须澄清；缺资料返回缺项，不得猜数、混用版本或悄悄放宽过滤。

### II. 能力声明必须有对应证据

明确区分已实现、设计草稿和已验证。Recall@k 是检索证据覆盖，不代表答案正确率。
冻结数据、发布标记和实验结果不得为新功能选型而覆盖或删除。
新评测记录数据/配置/代码版本、划分、评分与成本；同意图及变体归入同一划分。
gold/参考答案不得进入运行时查询、索引或工具输入；Mock 不证明真实检索和财务分析质量。

### III. 用边界明确的规格控制变更

新功能或改变行为的改动先定义目标、范围、非目标、兼容边界、需求 ID 和验收条件。
语义变更先更新 spec，再检查设计、任务和验证；不得只改代码或降低断言消除差异。
冲突依据用户意图解决并记录；常规实现细节在已授权范围内自主决定。
安装开发工具不等于授权实施所有候选能力；历史代码不必一次性补写规格。

### IV. 数字计算与执行权限有明确边界

财务数值先核验指标、单位、币种、期间及口径，再由确定性代码计算，保留输入来源与公式。
LLM 解释、用户假设和情景估计须与申报事实分开。
数据库操作使用受控参数；模型输出不能成为任意 SQL、Shell 或代码执行权限。
规划只能选择已声明可用的能力；查询变体、子任务、补查、调用和费用均有预算。
工具缺项和服务故障须明确返回，不得伪装执行成功或无限重试。

### V. 保持轻量、可复现的单项目架构

复用 Python CLI/Service、PostgreSQL + pgvector、既有元数据和来源关系。
单主 Agent 是后续默认编排目标；检索、规划、Skills 和计算函数不自动成为独立 Agent。
只有明确需求才引入额外服务、数据库、队列、框架或 Subagent。
记录实际模型/提示词/配置和依赖版本；密钥只在本机受忽略配置中保存。
测试针对受影响的契约、边界和结果，不为文档或低影响改动新增镜像测试。

## Current Baseline and Document Ownership

当前实现以 README、代码、配置和测试为证据：SEC HTML 采集、解析、切块、Voyage 向量化、
混合检索、证据导出及冻结检索评测；含基础规则过滤和固定中英术语扩展。
2026-10-26新增显式实验路径：元数据catalog QueryPlan、有界检索/来源表格组装、在线逐项生成及本地trace；旧路径保留用于复现。2026-10-27新增隔离服务路径：文档级原子入库、数据库catalog、ANN/BM25、精排接入生成及localhost API；证据目标planner与CrossEncoder为可选配置。财务事实层、确定性计算、预测/估值、自主Agent循环、独立语义验收和规模负载验收仍属后续。

- Notion 保留总体路线图、调研和技术图，不整份复制到仓库。
- README 说明当前代码；本章程约束开发；功能 `spec.md` 是执行契约。
- `plan.md` 记录技术设计，`tasks.md` 追踪实施。Notion 候选方案进入功能范围后才成为承诺。
- 用户最新指令优先；资料冲突记录影响并协调，规划文档不作为实现证明。

来源：[Notion v0.9 第 5.3、5.4、6、7 节，读取于 2026-10-25](https://app.notion.com/p/Agent-3f6fda5b0ede808b9b60cee10e298cee)，
README 第 5、8、9、10 节。

## Development Workflow and Quality Gates

1. 从一个可独立审查的改动开始，记录规格与兼容边界；必要时澄清。
2. 设计检查本章程，复用实际模块，区分本次实现与未来依赖。
3. 任务关联需求 ID 和验收方式；实施前检查 spec/plan/tasks 一致性。
4. 完成适当的离线/契约验证；需要数据库或付费 API 时明确说明依赖和成本。
5. 交付列出实现、验证证据和未完成项；发布测试冻结，后续选型另建版本。
6. 功能规格采用 living contract：修改保留 Git 历史，同步下游设计/任务/验证。

## Governance

语义版本：原则删除或不兼容重定义升主版本，新增约束升次版本，文字澄清升修订版本。
修订说明原因、影响和必要迁移，并同步相关模板与功能文档；不增加单独审批平台。
重要偏离在设计中说明理由、替代方案和验证，不得无记录绕过。
工具版本以 `.specify/integration.json` 为准；升级时审查模板与 Skills 差异，保留项目定制。

**Version**: 1.0.1 | **Ratified**: 2026-10-25 | **Last Amended**: 2026-10-26
