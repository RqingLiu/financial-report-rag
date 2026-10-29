# Implementation Plan: 可审计开发基线
**Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

## Technical Context / Decisions
复用Python3.12、httpx、Pydantic、PostgreSQL、Voyage及既有Retriever。新入口 `python -m finrag.baseline`，不改旧检索源码以保护冻结回放指纹。Repository代理记录真实dense/fts搜索；Retriever子类仅捕获super._search输出，复用原RRF/interleave重建排序诊断。保存所有候选payload用于离线span评分；实际生成只拿super.retrieve(k=10)的返回。

新模块 `tracing.py`（本地JSON stage层级）、`generation.py`（DeepSeek与跨服务预算）、`baseline.py`（query-only适配、观测、评测、Markdown/HTML复核）。`tests/test_baseline.py`覆盖语义重要契约。无云账户凭证时显式local_only，不隐式开通服务。未来可以把同一trace映射至LangSmith。

## Contracts
- query-only文件 → 原问+阅读背景；U14使用confirmed_context，冲突拒绝。不得从gold.documents或证据group生成过滤条件。相同合法输入用于检索和生成；corpus_scope仅解释可用材料，不把所有公司拼成过滤条件。
- stage: id,parent_id,name,start/end/duration,status,inputs,outputs。不自动序列化客户端/Settings/header/异常正文。每题trace单独原子保存。
- 三种score：候选并集、未限上下文的融合top5/10/20、真实最终context。前两者为诊断；不冒充线上top20。评分在检索与生成结束后加载gold，不改变运行时。
- 数值/事实/引用语义默认pending_human；可给引用ID/日期的结构检查，不能当faithfulness。生成可给原文与公式，未执行确定性计算需说明未验证。
- budget: fcntl锁保护JSONL事件，reserve→settle；未决预留永久占用直到人工对账。固定共享路径，最高新请求停止阈值4.5美元。请求前以UTF8字节+固定封装余量估算输入上界，按max_tokens预留输出。DeepSeek峰时未命中价0.30/1.20美元每百万作为保守估计；Voyage4-lite0.02。返回usage后记保守列表价，不冒充时段/优惠后的发票。未知响应/超时不重试，保留预留；已知未发出的连接失败可释放。未知usage终止付费批次。
- DeepSeek模型deepseek-flash，thinking disabled，temperature0，max_tokens4096，串行，httpx超时60秒，0自动重试；无Search/Fetch。模型响应名/ID和finish_reason记录。
- 复用嵌入缓存；仅query缺失调用，跨服务共享预算；不重建任何文档embedding。
- 每次实验唯一目录；断点通过已完成query trace复用，明确reused。可只跑retrieval，或只对既有trace生成，避免重复检索。

## Constitution Check
来源/财年/截止日显式；gold隔离；新独立模块不改变冻结行为；无新后台服务；费用与单次调用有界；错误不伪装证据不足；本地秘密忽略；验收不宣称答案已人工通过。全部符合。

## Execution / Evidence
先离线契约与既有回归、gold --check；只读DB连通性；20题检索诊断；6题生成pilot（U02/U03/U06/U09/U12/U14）；核对真实usage与截断后完成余14题。保存manifest/trace/scores/review/summary。观察后报告根因，不在本轮调检索参数。新API价格核对来源：DeepSeek官方pricing与chat API、Voyage官方pricing（2026-10-26）。
