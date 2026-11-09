# RAG Agent 迁移状态

2026-11-08：**已完成首轮等价 LangGraph 迁移**。`configs/serving.json` 默认 `engine=langgraph`；顺序对照仅保留为 `engine=sequential` 的迁移回退。没有启用证据驱动补查，也没有新跑 20 题。

已实施：模块按职责分层；RunState / RunContext / RunPolicy；实际 StateGraph 节点和条件边；原检索/精排/context/生成适配；统一终态、节点轨迹、调用上限和可选请求预算；原持久账本继续预留/结算；API/CLI 共用一套内核。原问、披露日、财年过滤和原文 span 保留。

迁移使用 LangGraph 1.2.20。干净环境测试发现 RAGAS 0.4.3 无法导入新版 community 删除的 VertexAI 旧适配器，因此评测 extra 固定 `langchain-community==0.3.31`；该版本与已解析的新 core 能同时通过导入、ID metric 和依赖检查。没有直接升级原 `.venv`；本机已验证环境是 `.venv-migrate`。运行与完整评测各有一份 lock。

设计沿用课程第 10、11 章：一个协调工作流，明确 State / Decision / Action，工具由应用校验和执行。LangGraph 管理节点与路由，provider 适配和账本负责调用/计费。工具不是各自一个 Agent；首轮没有自由 ReAct、Supervisor、长期记忆或 checkpoint 平台。[官方 Graph API](https://docs.langchain.com/oss/python/langgraph/graph-api)。

目前 evidence gate 仅判断最终上下文是否为空；格式/引用 ID 校验仍不能证明数字、财年或语义支持正确。迁移等价测试使用确定性工具回执，不能当作财报回答分数。

下一步顺序：

1. 复核规范意图草案，建立有来源标签的 raw-query 配对集；规整的 81 子题不能证明口语改写效果。
2. 用获授权的小样本验证真实服务端到端对照；固定模型、索引、总 SQL、context 预算及 rubric。
3. 单独设计并测试最多一次的证据缺口补查；目前没有该循环。默认关闭，证实收益和退步情况后才决定推广。
4. 财务工具另做期间、单位、符号、口径契约；算术实验不默认开启。持久恢复、多 Agent、预测和估值继续延期。

[完整文件/节点地图](repository-layout.md) · [当前架构](architecture.md) · [Spec 012](../specs/012-rag-agent-workflow/spec.md) · [评测边界](evaluation.md#raw-query-and-rewrite-evaluation)。
