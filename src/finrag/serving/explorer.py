"""Read-only, allowlisted browser views of private diagnostic traces."""

import json
import re
from heapq import nlargest
from pathlib import Path

from fastapi import HTTPException

from ..config import ROOT

TRACE_DIR = ROOT / "logs/serving"
MAX_TRACE_BYTES = 32 * 1024 * 1024


def pick(row, keys):
    return {k: row[k] for k in keys.split() if k in row}


def catalog_view(catalog, as_of):
    """Current published DB catalog, kept separate from historical trace snapshots."""
    filings = []
    eligible = [f for f in catalog.filings if f.filed_at <= as_of]
    for filing in eligible[:500]:
        row = pick(
            filing.model_dump(),
            "id ticker fiscal_year form period_end filed_at source_url amends_document_id",
        )
        # Conventional managed raw-file location, not an arbitrary file endpoint.
        if re.fullmatch(r"[A-Za-z0-9_-]+", filing.id):
            raw = ROOT / "data/raw" / f"{filing.id}.html"
            if raw.is_file() and not raw.is_symlink():
                row["local_raw_path"] = f"data/raw/{filing.id}.html"
        filings.append(row)
    return {
        "source": "current_published_database",
        "as_of": as_of,
        "documents": len(eligible),
        "returned_documents": len(filings),
        "truncated": len(eligible) > len(filings),
        "filings": filings,
    }


def hit_view(hit, *, text_limit=4000):
    chunk = hit.get("chunk", {})
    text = chunk.get("text", "")
    return {
        **pick(hit, "score method"),
        "chunk": {
            **pick(chunk, "id document_id section tokens source_spans"),
            "text": text[:text_limit],
            "text_truncated": len(text) > text_limit,
        },
    }


def evidence_view(row):
    text = row.get("text", "")
    return {
        **pick(
            row,
            "citation document_id ticker fiscal_year period_end filed_at source_url "
            "chunk_id source_spans",
        ),
        "text": text[:64000],
        "text_truncated": len(text) > 64000,
    }


def generation_view(row):
    return pick(row, "answer structured_answer structural_validation finish_reason")


def model_input(inputs):
    """Project known business payloads; never forward system/raw messages."""
    purpose = inputs.get("purpose")
    allowed = {
        "query_planning": "request catalog",
        "candidate_rerank": "question reading_context confirmed_context as_of companies needs candidates",
        "planned_answer": "question reading_context confirmed_context as_of plan evidence",
    }
    if purpose not in allowed:
        return None
    for message in inputs.get("messages", []):
        if message.get("role") != "user":
            continue
        try:
            payload = json.loads(message.get("content", ""))
            if isinstance(payload, dict):
                return business_fields(pick(payload, allowed[purpose]))
        except (ValueError, TypeError):
            pass
    return None


BUSINESS_KEYS = frozenset(
    [
        "request",
        "catalog",
        "question",
        "original_question",
        "reading_context",
        "confirmed_context",
        "as_of",
        "ticker",
        "cik",
        "name",
        "aliases",
        "reports",
        "document_id",
        "fiscal_year",
        "period_end",
        "filed_at",
        "source_url",
        "companies",
        "source_mention",
        "report_years",
        "needs",
        "id",
        "description",
        "source_quote",
        "candidates",
        "i",
        "source",
        "report_fy",
        "line",
        "line_count",
        "lines",
        "plan",
        "evidence",
        "citation",
        "chunk_id",
        "source_spans",
        "text",
        "block_id",
        "start",
        "end",
        "section",
        "tasks",
        "need_ids",
        "tickers",
        "dense_queries",
        "keywords",
        "depends_on",
        "route",
        "action",
        "period_basis",
        "period_interpretation",
        "excluded_tickers",
        "limitations",
        "clarification_questions",
        "report_document_id",
        "date_precision",
        "exclude_later_filings",
    ]
)


def business_fields(value):
    """Drop unexpected nested provider/config keys, including inside user JSON."""
    if isinstance(value, dict):
        return {k: business_fields(v) for k, v in value.items() if k in BUSINESS_KEYS}
    if isinstance(value, list):
        return [business_fields(v) for v in value]
    return value


def stage_view(row):
    """Never recursively expose generic provider events/messages/configuration."""
    name = row["name"]
    inputs, outputs = row.get("inputs", {}), row.get("outputs", {})
    out = pick(row, "id parent_id name status started_at ended_at duration_seconds error_type")
    source = row.get("source")
    if isinstance(source, dict):
        path = source.get("path", "")
        if path.startswith(("src/finrag/", "tests/")) and ".." not in path.split("/"):
            out["source"] = pick(source, "path function line sha256")
    out["inputs"] = pick(
        inputs,
        "purpose max_tokens json_object method candidates evidence_cap prompt_cap "
        "queries input_type model jobs task_id group documents query k variants "
        "rrf_c coarse_policy lexical_weight index_id request as_of candidate_ids need_ids "
        "evidence_ids search_count",
    )
    visible = {}
    if name == "catalog_snapshot":
        visible = pick(outputs, "documents fingerprint catalog")
    elif name in ("query_plan", "evidence_regroup"):
        visible = pick(outputs, "cached attempts validated_plan")
    elif name == "llm_call":
        business = model_input(inputs)
        if business is not None:
            out["inputs"]["business_payload"] = business
        visible = pick(
            outputs, "requested_model response_model usage peak_list_cost_usd finish_reason"
        )
    elif name == "embed_queries":
        visible = {
            "vectors_logged": False,
            "usage_events": [
                pick(e, "model input_type tokens peak_list_cost_usd cached")
                for e in outputs.get("usage_events", [])
            ],
        }
    elif name == "retrieve":
        visible = pick(outputs, "completed_searches hit_count unique_chunks")
    elif name.startswith("retrieve."):
        visible = {"hits": [hit_view(h, text_limit=1200) for h in outputs.get("hits", [])]}
    elif name == "fusion":
        visible = pick(outputs, "raw_candidates retained provenance")
        visible["ranked_hits"] = [hit_view(h) for h in outputs.get("ranked_hits", [])]
    elif name == "rerank":
        visible = pick(outputs, "scores")
        event = outputs.get("event", [])
        events = event if isinstance(event, list) else [event]
        visible["calls"] = [pick(e, "cached attempts method model costs_usd") for e in events]
    elif name == "context_build":
        visible = pick(
            outputs,
            "evidence_tokens evidence_token_cap full_prompt_proxy_tokens "
            "full_prompt_cap selected_items decisions semantic_need_judgments_are",
        )
        visible["evidence"] = [evidence_view(e) for e in outputs.get("evidence", [])]
    elif name == "generation":
        visible = generation_view(outputs)
    out["outputs"] = visible
    return out


def trace_view(data):
    retrieval = data.get("retrieval", {})
    return {
        **pick(data, "query_id created_at status error plan original_plan"),
        "inputs": pick(
            data.get("inputs", {}), "original_question reading_context confirmed_context as_of"
        ),
        "stages": [stage_view(s) for s in data.get("stages", [])],
        "search_records": [
            {
                **pick(r, "task_id group documents method query k variants duration_seconds"),
                "hits": [hit_view(h, text_limit=1200) for h in r.get("hits", [])],
            }
            for r in data.get("search_records", [])
        ],
        "retrieval": {
            "ranked_hits": [hit_view(h) for h in retrieval.get("ranked_hits", [])],
            "metadata": pick(
                retrieval.get("metadata", {}),
                "evidence_tokens evidence_token_cap full_prompt_proxy_tokens "
                "full_prompt_cap selected_items decisions semantic_need_judgments_are",
            ),
        },
        "evidence": [evidence_view(e) for e in data.get("runtime_evidence", [])],
        "generation": generation_view(data["generation"]) if data.get("generation") else None,
    }


def history(directory=None):
    directory = Path(directory or TRACE_DIR)
    # Do not parse dozens of full provider traces to populate the selector.
    paths = nlargest(
        30,
        (
            p
            for p in directory.glob("*.json")
            if re.fullmatch(r"[0-9a-f]{32}", p.stem) and not p.is_symlink()
        ),
        key=lambda p: p.stat().st_mtime,
    )
    return [
        {"query_id": p.stem, "modified_at": p.stat().st_mtime, "bytes": p.stat().st_size}
        for p in paths
    ]


def load_trace(query_id, directory=None):
    if not re.fullmatch(r"[0-9a-f]{32}", query_id):
        raise HTTPException(404, "trace_not_found")
    directory = Path(directory or TRACE_DIR)
    path = directory / f"{query_id}.json"
    if path.is_symlink() or not path.is_file():
        raise HTTPException(404, "trace_not_found")
    if path.stat().st_size > MAX_TRACE_BYTES:
        raise HTTPException(413, "trace_too_large_for_browser")
    try:
        with path.open("rb") as f:
            raw = f.read(MAX_TRACE_BYTES + 1)
        if len(raw) > MAX_TRACE_BYTES:
            raise HTTPException(413, "trace_too_large_for_browser")
        data = json.loads(raw)
        if data.get("query_id") != query_id:
            raise ValueError("trace_id_mismatch")
        return trace_view(data)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise HTTPException(422, "trace_unreadable") from None
