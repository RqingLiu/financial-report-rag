"""Bounded business-state observations; never serialize live dependency objects."""

from enum import Enum

# Shared capture/browser allowlist. A trace file is not trusted input.
FIELDS = frozenset(
    [
        "searches",
        "candidates",
        "query_id",
        "request",
        "question",
        "reading_context",
        "confirmed_context",
        "as_of",
        "ticker",
        "companies",
        "report_years",
        "report_document_id",
        "excluded_tickers",
        "date_precision",
        "exclude_later_filings",
        "original_plan",
        "plan",
        "action",
        "source_mention",
        "period_basis",
        "needs",
        "id",
        "description",
        "source_quote",
        "tasks",
        "need_ids",
        "tickers",
        "dense_queries",
        "keywords",
        "depends_on",
        "route",
        "clarification_questions",
        "unavailable_entities",
        "limitations",
        "period_interpretation",
        "catalog_fingerprint",
        "records",
        "ranked",
        "selected",
        "evidence",
        "context_metadata",
        "evidence_status",
        "generation",
        "task_id",
        "documents",
        "status",
        "outcome",
        "error",
        "type",
        "code",
        "total",
        "items",
        "truncated",
        "ids",
        "document_id",
        "group",
        "method",
        "query",
        "k",
        "hits",
        "citation",
        "chunk_id",
        "source_spans",
        "block_id",
        "start",
        "end",
        "section",
        "answer",
        "structured_answer",
        "sections",
        "need_id",
        "citations",
        "missing_evidence",
        "structural_validation",
        "finish_reason",
        "evidence_tokens",
        "evidence_token_cap",
        "full_prompt_proxy_tokens",
        "full_prompt_cap",
        "selected_items",
        "calculation_results",
        "available",
        "tools",
        "tool",
        "operation_id",
        "output_fields",
        "engine",
        "duration_seconds",
        "capture_version",
        "before",
        "after",
        "changed_fields",
    ]
)


def bounded(value, depth=0):
    """Bounded allowlisted JSON; indicate clipping instead of hiding it."""
    if depth > 12:
        return {"truncated": True}
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="json")
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {k: bounded(v, depth + 1) for k, v in value.items() if k in FIELDS}
    if isinstance(value, (list, tuple)):
        items = [bounded(v, depth + 1) for v in value[:80]]
        return (
            {"items": items, "total": len(value), "truncated": True} if len(value) > 80 else items
        )
    if isinstance(value, str):
        return value if len(value) <= 16000 else {"answer": value[:16000], "truncated": True}
    if value is None or isinstance(value, (bool, int, float)):
        return value
    return {"available": False}


def _snapshot(state):
    out = {}
    for key in (
        "request",
        "plan",
        "catalog_fingerprint",
        "status",
        "outcome",
        "evidence_status",
        "error",
    ):
        if key in state:
            out[key] = bounded(state[key])
    for key in ("ranked", "selected"):
        if key in state:
            rows = state[key]
            out[key] = {
                "total": len(rows),
                "ids": [h.chunk.id for h in rows[:80]],
                "truncated": len(rows) > 80,
            }
    if "records" in state:
        rows = state["records"]
        out["records"] = {
            "total": len(rows),
            "truncated": len(rows) > 40,
            "items": [
                {
                    **{
                        k: r[k]
                        for k in ("task_id", "group", "documents", "method", "query", "k")
                        if k in r
                    },
                    "hits": len(r.get("hits", [])),
                }
                for r in rows[:40]
            ],
        }
    if "evidence" in state:
        out["evidence"] = [
            {k: r[k] for k in ("citation", "document_id", "chunk_id", "source_spans") if k in r}
            for r in state["evidence"][:30]
        ]
    if "context_metadata" in state:
        out["context_metadata"] = {
            k: state["context_metadata"][k]
            for k in (
                "evidence_tokens",
                "evidence_token_cap",
                "full_prompt_proxy_tokens",
                "full_prompt_cap",
                "selected_items",
            )
            if k in state["context_metadata"]
        }
    if "generation" in state:
        out["generation"] = bounded(
            {
                k: state["generation"][k]
                for k in ("answer", "structured_answer", "finish_reason")
                if k in state["generation"]
            }
        )
    if "calculation_results" in state:
        out["calculation_results"] = {"available": bool(state["calculation_results"])}
    return bounded(out)


def snapshot(state):
    try:
        return _snapshot(state)
    except Exception:  # noqa: BLE001 — state observation cannot alter execution
        return {"available": False}
