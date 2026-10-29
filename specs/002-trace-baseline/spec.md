# Feature Specification: 可审计的20题开发基线

**Feature Directory**: `specs/002-trace-baseline`
**Created**: 2026-10-26
**Status**: Implemented and baseline measured — 20题尝试、15题生成、5题路由误澄清；答案语义评分待复核
**Input**: 对已发布20题开发集运行当前检索与答案生成，保存完整执行证据，先分析再调优。

## User Scenarios & Testing

### User Story 1 - 看见证据在哪一步丢失 (Priority: P1)
开发者逐题查看输入、生效范围、候选、融合排名和实际上下文。
**Why this priority**: 总召回分数不能解释失败原因。
**Independent Test**: 同一输入的观测路径与既有检索路径输出相同；候选有证据而上下文没有时可定位。
**Acceptance Scenarios**:
1. **Given** 已确认阅读背景与截止日，**When** 跑基线，**Then** 记录原问和实际查询，不使用答案或证据标签改变检索。
2. **Given** 预算裁剪，**When** 查看记录，**Then** 可区分候选未命中、排名靠后、上下文丢失。

### User Story 2 - 受预算约束生成并保存答案 (Priority: P1)
开发者用同一生成配置跑少量试题，通过后扩展到20题。
**Why this priority**: 把检索质量与答案质量分开，避免不可控费用。
**Independent Test**: 模拟超预算、网络错误、截断和缺usage，验证不再提交超限请求且错误可追溯。
**Acceptance Scenarios**:
1. **Given** 费用预留达到停止阈值，**When** 新请求，**Then** 调用前拒绝；不以花完预算为目标。
2. **Given** 未知是否计费的超时，**When** 记录结果，**Then** 保留预留且不自动重试。
3. **Given** 生成答案，**When** 复核，**Then** 保存实际证据、答案和可读视图，数学结果不被描述为确定性工具验证。

### User Story 3 - 复现、重评分与扩展观测 (Priority: P2)
开发者不重复付费就能浏览既有记录和重算确定性检索指标；云端凭证缺失不阻断本地实验。
**Why this priority**: 保留审计依据与后续对照基础。
**Independent Test**: 离线重评分不访问模型；既有冻结产物哈希不变。
**Acceptance Scenarios**:
1. **Given** 保存的执行输出，**When** 重评分，**Then** 不重新检索或生成。
2. **Given** 没有观测平台凭证，**When** 实验，**Then** 明确标注仅本地trace，不声称云端已接入。

### Edge Cases
空证据、截止日前无可用文档、显式确认与参数冲突、部分可回答、无效/空/截断响应、服务失败、重复执行、并发费用预留、候选截断与上下文限额、凭证泄露。

## Scope and Change Boundaries
- **In scope**: 20题dev适配、分阶段观测、固定检索生成基线、费用账本、逐题复核与确定性重评分。
- **Out of scope**: QueryPlan/动态改写、reranker、新切块、预测估值、完整财务计算工具、独立holdout、完整自动语义评分、多Agent、自动创建云账户。
- **Existing behavior to preserve**: 旧CLI/源码检索行为、默认配置、v1/v2发布数据和历史测试结果。旧QueryPlan草稿保持独立，不能将本轮当其验收。
- **Sources**: 用户2026-10-26本轮指令；README §5/8；golden_v2/README；前轮评测讨论。

## Requirements
### Functional Requirements
- **FR-001**: 运行时只接收已发布query输入中的原问、阅读背景、已确认上下文、截止日及可用语料范围；gold仅进入离线评分。
- **FR-002**: 每题记录唯一执行ID、生效范围、查询、各路候选及排名、融合排名、实际上下文、答案或明确错误。
- **FR-003**: 记录阶段关系与耗时、输入输出、数据/代码/提示词/模型配置版本；不记录凭证。
- **FR-004**: 保持原检索行为，区分无上下文预算的排名诊断与实际10条/8K代理token上下文。
- **FR-005**: 复用原文span评分，报告证据组macro/micro召回、全证据完整率、各阶段缺项。
- **FR-006**: 数值、事实、引用支持度与边界语义评分状态明确；未人工核验不能伪装为自动满分；仅引用ID存在不等于支持主张。
- **FR-007**: 生成调用有输出上限/超时/费用预留，失败明确且无隐式重试；保存usage和计费估计依据。
- **FR-008**: 新增付费调用共享持久账本，含查询向量与生成；总授权5美元，默认4.5美元停止新调用，保留0.5缓冲；允许更早停止。
- **FR-009**: 未知计费保留预留；并发预留原子化；不能以缺失usage当免费；费用不冒充实际发票。
- **FR-010**: 已有执行可离线重评分；新运行不覆盖既有结果；无云端凭证时保留完整本地记录。

### Key Entities
Request、Trace/Stage、Evidence、Experiment、BudgetReservation、Evaluation/Review。

## Success Criteria
### Measurable Outcomes
- **SC-001**: 所有尝试题均有完整成功记录或明确失败记录；能追溯实际送入回答模型的全部证据。
- **SC-002**: 观测与原路径在相同输入/配置下返回证据一致；历史保护产物哈希不变。
- **SC-003**: 费用超限/缺usage/未知超时测试全部阻止不受控后续调用；实际花费不以预算上限为目标。
- **SC-004**: 试跑6题后，在接口正常且费用充足时完成20题；输出逐题证据覆盖与失败根因，未核验答案分数明确待审。

## Acceptance Traceability
| Requirement | Scenario / criterion | Verification evidence |
| --- | --- | --- |
| FR-001,004 | US1 / SC-002 | 输入隔离、约束与原路径一致性测试 |
| FR-002,003,005 | US1 / SC-001 | 分阶段trace和逐题评分 |
| FR-006 | US2 / SC-004 | 复核视图与待审标记 |
| FR-007,008,009 | US2 / SC-003 | 离线故障/预算测试与账本 |
| FR-010 | US3 / SC-002 | 重评分与保护哈希 |

## Assumptions
当前本机数据库与已保存模型凭证可用；外部失败也属于可交付观察。首轮无云凭证则先本地；语义评分与财务计算工具不因接入生成就自动完成。全部20题仍是dev，不用于泛化声明。
