# FinRAG 开发入口

本文件适用于本项目及子目录，用户当前指令优先。

- 在 financial-report-rag 目录工作；上层学习目录的 Git 根与本项目 Spec Kit 根不同。
- 先读 [README](README.md)、[当前架构](docs/architecture.md)和[章程](.specify/memory/constitution.md)。
- 当前增量是[本地查询与Trace界面](specs/006-trace-explorer/spec.md)；当前日常入口`python -m finrag.serving.cli`。历史规格001–005与旧CLI保留，用于回归和实验复现；`finrag.pipeline`是上一版入口，不是当前默认。
  [开发/代码地图](docs/development.md)、[评测边界](docs/evaluation.md)、[数据入库](docs/data-and-ingestion.md)是公开说明；完整本地历史README/trace不提交Git。安装工具或编写规格不等于授权执行整个 implement 工作流。
- 新功能读对应 spec，再更新 plan/tasks；执行代码使用 `.venv/bin/python`。
- 需要 Spec Kit 工作流时读取 `.agents/skills/speckit-<step>/SKILL.md`。
- 当前功能由 `.specify/feature.json` 指定，不从 Git 分支推断。
- 不覆盖冻结配置、标注或发布标记；不为纯文档改动启动付费评测。
- 适当的离线回归为 `.venv/bin/python -m pytest -q`，DB 测试按 README 显式开启。
- Notion 保留总体路线图，功能执行规格随代码版本化，不复制整份计划书。
- 修改 QueryPlan 契约、模型、召回 Top-k、融合、reranker 接入状态或上下文预算时，同次更新 docs/architecture.md 和 Notion §5.10 的当前流程图、参数与核对日期；保留历史实验配置/结果，文档不自动同步。纯文档更新不启动付费评测。
- 公开提交前运行`python scripts/check_publication.py`扫描实际Git index；忽略.env/原文/缓存/本地trace，保留小型reports/public回执。不得把公开repo等同于生产验收。
