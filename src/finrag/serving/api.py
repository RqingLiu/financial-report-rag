"""Optional localhost adapter. Admission before worker dispatch, no ingestion over HTTP."""

from contextlib import contextmanager
from threading import BoundedSemaphore

from fastapi import FastAPI, HTTPException
from fastapi import Request as HTTPRequest
from fastapi.concurrency import run_in_threadpool

from ..planning import Request
from .runtime import query, resources


class Admission:
    def __init__(self, limit):
        self.slots = BoundedSemaphore(limit)

    @contextmanager
    def enter(self):
        if not self.slots.acquire(blocking=False):
            raise HTTPException(429, "server_busy_retry_later")
        try:
            yield
        finally:
            self.slots.release()


def create_app(config):
    app = FastAPI(title="FinRAG local API", docs_url="/docs")
    gate = Admission(config.max_inflight)
    app.state.admission = gate

    @app.middleware("http")
    async def bounded_body(req: HTTPRequest, call_next):
        # Enforce streamed actual bytes too, not only a client-controlled Content-Length.
        chunks = []
        size = 0
        async for part in req.stream():
            size += len(part)
            if size > 100000:
                from fastapi.responses import JSONResponse

                return JSONResponse({"detail": "request_body_limit"}, status_code=413)
            chunks.append(part)
        req._body = b"".join(chunks)
        return await call_next(req)

    @app.get("/health")
    def health():
        try:
            with resources(config, models=False) as (store, *_):
                count = len(store.indexed_documents(store.index_id))
                ann = store.ann_kind()
            return {"status": "ok", "published_documents": count, "ann": ann}
        except Exception:  # noqa: BLE001 — readiness must not leak DB details
            raise HTTPException(503, "database_unavailable") from None

    @app.post("/query")
    async def run(request: Request):
        try:
            # Admission happens before entering the worker queue. AnyIO's default thread
            # cancellation shielding keeps the slot held until the real work finishes.
            with gate.enter():
                data = await run_in_threadpool(query, request, config)
        except HTTPException:
            raise
        except Exception:  # noqa: BLE001 — protect credentials in startup failures
            raise HTTPException(503, "pipeline_unavailable") from None
        if data["status"] == "error":
            raise HTTPException(502, {"query_id": data["query_id"], "error": data["error"]})
        return {
            "query_id": data["query_id"],
            "status": data["status"],
            "plan": data.get("plan"),
            "generation": {
                "answer": data["generation"]["answer"],
                "sections": data["generation"]["structured_answer"],
            }
            if data.get("generation")
            else None,
            "evidence": data.get("runtime_evidence", []),
        }

    return app
