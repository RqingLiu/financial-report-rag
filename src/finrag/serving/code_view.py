"""Fixed implementation references, never a general file-reading endpoint."""

import ast
import hashlib
from pathlib import Path

from fastapi import HTTPException

SOURCE_ROOT = Path(__file__).resolve().parents[1]
# One registry serves the node labels, code map and bounded source viewer.
COMPONENTS = {
    "catalog_snapshot": [
        (
            "serving/store.py",
            "LiveStore.catalog",
            "读取已发布索引的年报元数据：documents JOIN publications",
        ),
        ("planning.py", "Catalog.metadata", "按披露截止日整理公司与报告财年"),
    ],
    "query_plan": [
        ("planning.py", "plan_request", "构造提示、调用模型、缓存与一次修复"),
        ("planning.py", "validate_plan", "校验公司、财年、证据需求与任务预算"),
        ("planning_scope.py", "report_year_constraints", "提取显式财年范围与排除条件"),
        ("generation.py", "DeepSeek.generate", "共享 DeepSeek API 适配与计费"),
    ],
    "evidence_regroup": [("serving/regroup.py", "regroup", "可选的证据目标任务重组")],
    "embed_queries": [
        (
            "planned_retrieval.py",
            "PlannedRetriever.search",
            "准备子查询、去重并调用 query embedding",
        ),
        (
            "serving/providers.py",
            "DocumentEmbedder._request",
            "Voyage embedding API、用量和维度校验",
        ),
    ],
    "retrieve": [
        ("serving/store.py", "LiveStore.search", "执行带文档与披露日期过滤的 pgvector / 词法检索"),
        (
            "planned_retrieval.py",
            "PlannedRetriever.search",
            "按 query × 公司 / 财年执行搜索并记录命中",
        ),
        ("planned_retrieval.py", "prepare_searches", "从 QueryPlan 编译实际搜索任务"),
    ],
    "fusion": [("planned_retrieval.py", "rank_records", "RRF 融合、去重与任务 / 分组交错排序")],
    "rerank": [
        ("reranking.py", "grade_candidates", "LLM 精排：分批提示、缓存、评分校验"),
        ("rerank_context.py", "candidates_for_rerank", "把候选原文整理为带来源与行号的精排输入"),
        ("serving/runtime.py", "select_context", "截取粗排 Top80，选择实际 reranker 分支"),
        ("generation.py", "DeepSeek.generate", "共享 DeepSeek API 适配；缓存未命中时真实请求"),
    ],
    "context_build": [
        ("rerank_context.py", "select_reranked", "按相关性、来源去重与 token 预算选证据"),
        ("serving/runtime.py", "select_context", "串联精排与上下文构建"),
    ],
    "generation": [
        ("answering.py", "generate_answer", "生成答案，校验 need 与引用结构"),
        ("answering.py", "answer_messages", "将问题、计划和最终证据构建成生成输入"),
        ("generation.py", "DeepSeek.generate", "共享 DeepSeek API 适配与计费"),
    ],
    "llm_call": [
        ("serving/runtime.py", "TracedModel.generate", "记录模型调用 span"),
        ("generation.py", "DeepSeek.generate", "发起真实模型请求并登记用量"),
    ],
    "crossencoder": [
        ("serving/providers.py", "CrossEncoder.rank", "可选的专用 Voyage reranker，默认未启用")
    ],
    "entry": [
        ("serving/api.py", "create_app", "浏览器 HTTP / SSE 入口"),
        ("serving/runtime.py", "query", "创建资源、执行查询并保存 trace"),
        ("serving/runtime.py", "execute", "八个阶段的总编排入口"),
        ("serving/cli.py", "main", "CLI 与本地服务启动入口"),
        ("tracing.py", "Trace.stage", "共享阶段耗时、嵌套关系与源码身份记录"),
    ],
    "ingestion": [
        ("serving/ingestion.py", "ingest_html", "可信 CLI：从 HTML 解析、切块到向量化和原子入库"),
        ("parse.py", "parse_html", "解析 HTML 段落、表格与原文位置"),
        ("chunk.py", "make_chunks", "结构感知切块与来源跨度"),
        ("serving/store.py", "LiveStore.publish", "原子发布文档、块、向量与词法索引"),
    ],
}


def code_view(component):
    if component not in COMPONENTS:
        raise HTTPException(404, "component_not_found")
    references = list(COMPONENTS[component])
    if component in {"catalog_snapshot", "query_plan", "evidence_regroup", "fusion", "generation"}:
        references.append(("serving/runtime.py", "execute", "总编排：调用该阶段"))
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
