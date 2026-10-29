"""Optional localhost adapter. Admission before worker dispatch, no ingestion over HTTP."""

import asyncio
import json
from contextlib import contextmanager
from pathlib import Path
from threading import BoundedSemaphore
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi import Request as HTTPRequest
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from ..planning import Request
from .explorer import history, load_trace, stage_view, trace_view
from .runtime import query, resources


class Admission:
    def __init__(self, limit):
        self.slots = BoundedSemaphore(limit)

    @contextmanager
    def enter(self):
        self.acquire()
        try:
            yield
        finally:
            self.slots.release()

    def acquire(self):
        if not self.slots.acquire(blocking=False):
            raise HTTPException(429, "server_busy_retry_later")


def create_app(config):
    app = FastAPI(title="FinRAG local API", docs_url="/docs")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )
    gate = Admission(config.max_inflight)
    app.state.admission = gate
    app.state.workers = set()
    static = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static), name="static")

    @app.get("/", include_in_schema=False)
    def explorer():
        return FileResponse(
            static / "index.html",
            headers={
                "Content-Security-Policy": "default-src 'self'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; "
                "frame-ancestors 'none'; base-uri 'none'",
                "X-Content-Type-Options": "nosniff",
            },
        )

    @app.get("/traces")
    def traces():
        return {"traces": history()}

    @app.get("/traces/{query_id}")
    def trace(query_id: str):
        return load_trace(query_id)

    @app.post("/query/stream")
    async def stream(request: Request, generate: bool = True):
        gate.acquire()  # reject before dispatch, not after starting a paid worker
        loop = asyncio.get_running_loop()
        queue = asyncio.Queue(maxsize=1024)
        disconnected = False
        qid = uuid4().hex

        def enqueue(kind, payload):
            if disconnected:
                return
            if queue.full():
                queue.get_nowait()  # terminal snapshot remains authoritative
            queue.put_nowait((kind, payload))

        def on_event(kind, row):
            snapshot = stage_view(row)  # snapshot before the worker mutates the span again
            loop.call_soon_threadsafe(enqueue, kind, snapshot)

        async def worker():
            try:
                data = await run_in_threadpool(
                    query,
                    request,
                    config,
                    do_generate=generate,
                    query_id=qid,
                    on_event=on_event,
                )
                enqueue("result", trace_view(data))
            except Exception:  # noqa: BLE001 — no provider/DB exception text in SSE
                enqueue(
                    "failure",
                    {"query_id": qid, "status": "error", "error": {"code": "pipeline_unavailable"}},
                )
            finally:
                gate.slots.release()  # held even if the browser disconnected

        task = asyncio.create_task(worker())
        app.state.workers.add(task)  # retain a strong reference beyond stream cancellation
        task.add_done_callback(app.state.workers.discard)

        async def events():
            nonlocal disconnected
            try:
                yield "event: accepted\ndata: " + json.dumps({"query_id": qid}) + "\n\n"
                while True:
                    try:
                        kind, payload = await asyncio.wait_for(queue.get(), timeout=15)
                    except TimeoutError:
                        yield ": keepalive\n\n"
                        continue
                    yield f"event: {kind}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
                    if kind in ("result", "failure"):
                        break
            finally:
                disconnected = True

        return StreamingResponse(
            events(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-store",
                "X-Accel-Buffering": "no",
            },
        )

    @app.middleware("http")
    async def bounded_body(req: HTTPRequest, call_next):
        origin = req.headers.get("origin")
        if origin and urlparse(origin).hostname not in ("127.0.0.1", "localhost", "::1"):
            from fastapi.responses import JSONResponse

            return JSONResponse({"detail": "local_origin_required"}, status_code=403)
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
        response = await call_next(req)
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        return response

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
