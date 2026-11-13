"""Fixed implementation references, never a general file-reading endpoint."""

import ast
import hashlib
from pathlib import Path

from fastapi import HTTPException

SOURCE_ROOT = Path(__file__).resolve().parents[1]
# One registry serves the node labels, code map and bounded source viewer.
COMPONENTS = {
    "resource_setup": [
        ("serving/runtime.py", "query", "图外资源初始化、清理和失败终态"),
        ("serving/resources.py", "resources", "创建并最终关闭数据库及模型客户端"),
    ],
    "execution_policy": [
        ("agent/policy.py", "RunControl", "全请求预算、attempt、deadline与取消"),
        ("providers/llm.py", "Budget.reserve", "唯一账本中的请求/批次/累计金额及答案预留"),
        ("providers/llm.py", "PaidClient.post", "付费尝试、HTTP时限和保守结算"),
    ],
    "catalog_snapshot": [
        (
            "retrieval/store.py",
            "LiveStore.catalog",
            "读取已发布索引的年报元数据：documents JOIN publications",
        ),
        ("agent/planner.py", "Catalog.metadata", "按披露截止日整理公司与报告财年"),
    ],
    "query_plan": [
        ("agent/planner.py", "plan_request", "构造提示、调用模型、缓存与一次修复"),
        ("agent/planner.py", "validate_plan", "校验公司、财年、证据需求与任务预算"),
        ("agent/scope.py", "report_year_constraints", "提取显式财年范围与排除条件"),
        ("providers/llm.py", "DeepSeek.generate", "共享 DeepSeek API 适配与计费"),
    ],
    "evidence_regroup": [("agent/regroup.py", "regroup", "可选的证据目标任务重组")],
    "embed_queries": [
        (
            "retrieval/search.py",
            "PlannedRetriever.search",
            "准备子查询、去重并调用 query embedding",
        ),
        (
            "providers/voyage.py",
            "DocumentEmbedder._request",
            "Voyage embedding API、用量和维度校验",
        ),
    ],
    "retrieve": [
        (
            "retrieval/store.py",
            "LiveStore.search",
            "执行带文档与披露日期过滤的 pgvector / 词法检索",
        ),
        (
            "retrieval/search.py",
            "PlannedRetriever.search",
            "按 query × 公司 / 财年执行搜索并记录命中",
        ),
        ("retrieval/search.py", "prepare_searches", "从 QueryPlan 编译实际搜索任务"),
    ],
    "fusion": [("retrieval/search.py", "rank_records", "RRF 融合、去重与任务 / 分组交错排序")],
    "rerank": [
        ("retrieval/rerank.py", "grade_candidates", "LLM 精排：分批提示、缓存、评分校验"),
        (
            "retrieval/evidence.py",
            "candidates_for_rerank",
            "把候选原文整理为带来源与行号的精排输入",
        ),
        ("retrieval/selection.py", "select_context", "截取粗排 Top80，选择实际 reranker 分支"),
        ("providers/llm.py", "DeepSeek.generate", "共享 DeepSeek API 适配；缓存未命中时真实请求"),
    ],
    "context_build": [
        ("retrieval/evidence.py", "select_reranked", "按相关性、来源去重与 token 预算选证据"),
        ("retrieval/selection.py", "select_context", "串联精排与上下文构建"),
    ],
    "generation": [
        ("answering/generation.py", "generate_answer", "生成答案，校验 need 与引用结构"),
        ("answering/generation.py", "answer_messages", "将问题、计划和最终证据构建成生成输入"),
        ("providers/llm.py", "DeepSeek.generate", "共享 DeepSeek API 适配与计费"),
    ],
    "llm_call": [
        ("providers/traced.py", "TracedModel.generate", "记录模型调用 span"),
        ("providers/llm.py", "DeepSeek.generate", "发起真实模型请求并登记用量"),
    ],
    "crossencoder": [
        ("providers/voyage.py", "CrossEncoder.rank", "可选的专用 Voyage reranker，默认未启用")
    ],
    "agent_state": [
        ("agent/state.py", "RunState", "每次请求的业务状态"),
        ("agent/policy.py", "RunControl", "节点、调用、费用及取消检查"),
        ("agent/graph.py", "build_graph", "LangGraph 节点与条件边"),
    ],
    "entry": [
        ("serving/api.py", "create_app", "浏览器 HTTP / SSE 入口"),
        ("serving/runtime.py", "query", "创建资源、执行查询并保存 trace"),
        ("agent/runner.py", "execute", "请求生命周期与 LangGraph 调用入口"),
        ("serving/cli.py", "main", "CLI 与本地服务启动入口"),
        ("core/tracing.py", "Trace.stage", "共享阶段耗时、嵌套关系与源码身份记录"),
    ],
    "ingestion": [
        ("ingestion/publish.py", "ingest_html", "可信 CLI：从 HTML 解析、切块到向量化和原子入库"),
        ("ingestion/parse.py", "parse_html", "解析 HTML 段落、表格与原文位置"),
        ("ingestion/chunk.py", "make_chunks", "结构感知切块与来源跨度"),
        ("retrieval/store.py", "LiveStore.publish", "原子发布文档、块、向量与词法索引"),
    ],
}


NODE_COMPONENTS = {
    "catalog": ("catalog", "catalog_snapshot"),
    "plan": ("plan", "query_plan"),
    "regroup": ("regroup_plan", "evidence_regroup"),
    "retrieve": ("retrieve", "retrieve"),
    "fusion": ("fuse", "fusion"),
    "context": ("context", "context_build"),
    "evidence_gate": ("evidence_gate", None),
    "calculate": ("calculate", None),
    "answer": ("answer", "generation"),
    "validate": ("validate", None),
}
for _node, (_function, _stage) in NODE_COMPONENTS.items():
    COMPONENTS["node_" + _node] = [
        ("agent/nodes.py", _function, "实际图节点适配器"),
        ("agent/graph.py", "build_graph", "图结构与条件边"),
        *COMPONENTS.get(_stage, []),
    ]


def code_view(component):
    if component not in COMPONENTS:
        raise HTTPException(404, "component_not_found")
    references = list(COMPONENTS[component])
    if component in {"catalog_snapshot", "query_plan", "evidence_regroup", "fusion", "generation"}:
        references.append(
            (
                "agent/nodes.py",
                {
                    "catalog_snapshot": "catalog",
                    "query_plan": "plan",
                    "evidence_regroup": "regroup_plan",
                    "fusion": "fuse",
                    "generation": "answer",
                }[component],
                "节点适配：调用该实现",
            )
        )
    snippets = []
    for relative, symbol, role in references:
        path = SOURCE_ROOT / relative
        if path.is_symlink() or not path.resolve().is_relative_to(SOURCE_ROOT):
            raise HTTPException(404, "source_unavailable")
        content = path.read_bytes()
        node = ast.parse(content)
        for part in symbol.split("."):
            node = next(n for n in node.body if getattr(n, "name", None) == part)
        lines = content.decode().splitlines()
        end = min(node.end_lineno, node.lineno + 139)
        snippets.append(
            {
                "path": f"src/finrag/{relative}",
                "symbol": symbol,
                "role": role,
                "start_line": node.lineno,
                "end_line": end,
                "sha256": hashlib.sha256(content).hexdigest(),
                "text": "\n".join(lines[node.lineno - 1 : end]),
                "truncated": end < node.end_lineno,
            }
        )
    return {"component": component, "version": "current_checkout", "snippets": snippets}


def component_map():
    return {
        "version": "current_checkout",
        "components": {
            component: [
                {k: v for k, v in s.items() if k not in {"text", "truncated"}}
                for s in code_view(component)["snippets"]
            ]
            for component in COMPONENTS
        },
    }
