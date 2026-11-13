"""Managed local run discovery, never an arbitrary filesystem API."""

import hashlib
import json
import re

from fastapi import HTTPException

from finrag.core.config import ROOT
from finrag.serving.explorer import MAX_TRACE_BYTES, history, load_trace, trace_view

CASE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}")


def _safe(path):
    try:
        relative = path.relative_to(ROOT)
    except ValueError:
        return False
    cursor = ROOT
    for part in relative.parts:
        cursor /= part
        if cursor.is_symlink():
            return False
    return True


def _registered():
    base = ROOT / "reports/current"
    if not _safe(base) or not base.is_dir():
        return []
    result = []
    # Discovery reads small manifests only, never every multi-MB trace.
    for folder in sorted(base.iterdir(), key=lambda p: p.name, reverse=True):
        if len(result) >= 50:
            break
        manifest = folder / "manifest.json"
        traces = folder / "traces"
        if not _safe(manifest) or not _safe(traces) or not traces.is_dir():
            continue
        if not manifest.is_file() or manifest.stat().st_size > 1024 * 1024:
            continue
        try:
            ids = json.loads(manifest.read_text())["identity"]["selected_ids"]
            if not isinstance(ids, list) or not ids or len(ids) > 1000:
                continue
            if any(not isinstance(i, str) or not CASE.fullmatch(i) or ".." in i for i in ids):
                continue
        except (ValueError, KeyError, TypeError, OSError):
            continue
        result.append((hashlib.sha256(folder.name.encode()).hexdigest()[:20], folder, ids))
    return result


def runs_view():
    live = history()
    return {
        "runs": [
            {
                "id": "live",
                "label": "本地查询",
                "kind": "live",
                "cases": [{"id": r["query_id"], "modified_at": r["modified_at"]} for r in live],
            },
            *[
                {
                    "id": key,
                    "label": folder.name,
                    "kind": "evaluation",
                    "cases": [{"id": i} for i in ids],
                }
                for key, folder, ids in _registered()
            ],
        ]
    }


def case_view(run_id, case_id):
    if run_id == "live":
        return {**load_trace(case_id), "view_mode": "saved", "record_kind": "live"}
    for key, folder, ids in _registered():
        if run_id != key:
            continue
        if case_id not in ids:
            break
        path = folder / "traces" / f"{case_id}.json"
        if not _safe(path) or not path.is_file():
            break
        if path.stat().st_size > MAX_TRACE_BYTES:
            raise HTTPException(413, "trace_too_large_for_browser")
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_TRACE_BYTES + 1)
            if len(raw) > MAX_TRACE_BYTES:
                raise HTTPException(413, "trace_too_large_for_browser")
            data = json.loads(raw)
            if data.get("query_id") != case_id:
                raise ValueError("wrong trace")
            return {**trace_view(data), "view_mode": "saved", "record_kind": "evaluation"}
        except (ValueError, KeyError, TypeError, AttributeError):
            raise HTTPException(422, "trace_unreadable") from None
    raise HTTPException(404, "managed_trace_not_found")
