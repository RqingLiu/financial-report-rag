"""Optional localhost adapter. Admission before worker dispatch, no ingestion over HTTP."""

import asyncio
import json
from contextlib import asynccontextmanager, contextmanager
from datetime import date
from pathlib import Path
from threading import BoundedSemaphore, Event
from urllib.parse import urlparse
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi import Request as HTTPRequest
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from finrag.agent.planner import Request
from finrag.serving.code_view import code_view, component_map
from finrag.serving.explorer import (
    agent_view,
    catalog_view,
    event_view,
    history,
    load_trace,
    trace_view,
)
from finrag.serving.runtime import query, resources


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
    @asynccontextmanager
    async def lifespan(app):
        try:
            yield
        finally:
            for signal in list(app.state.cancellations.values()):
                signal.set()
            # Never free admission while a synchronous provider call is still running.
            if app.state.workers:
                await asyncio.gather(*app.state.workers, return_exceptions=True)

    app = FastAPI(title="FinRAG local API", docs_url="/docs", lifespan=lifespan)
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["127.0.0.1", "localhost", "[::1]", "testserver"]
    )
    gate = Admission(config.max_inflight)
    app.state.admission = gate
    app.state.workers = set()
    app.state.cancellations = {}

    def finished(task):
        app.state.workers.discard(task)
        if not task.cancelled():
            task.exception()  # also consume failures after the HTTP waiter disconnected

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

    @app.get("/workflow")
    def workflow():
        from finrag.agent.graph import workflow_view

        return workflow_view(config)

    @app.get("/runs")
    def saved_runs():
        from finrag.serving.history import runs_view

        return runs_view()

    @app.get("/runs/{run_id}/cases/{case_id}")
    def saved_case(run_id: str, case_id: str):
        from finrag.serving.history import case_view

        return case_view(run_id, case_id)

    @app.get("/readiness")
    def readiness():
        from decimal import Decimal

        from finrag.core.config import ROOT
        from finrag.serving.resources import shared_budget

        try:
            if not (ROOT / "data/cache/baseline/budget.jsonl").is_file():
                return {"status": "unconfigured", "reason": "local_budget_not_initialized"}
            data = shared_budget(config).snapshot()
            used = Decimal(data["known_peak_list_cost_usd"]) + Decimal(
                data["unresolved_reserved_usd"]
            )
            blocked = data["halted"] or used >= Decimal(data["stop_usd"])
            return {
                "status": "blocked" if blocked else "available",
                "reason": "budget_stop_reached" if blocked else "budget_only_check",
                "known_usd": data["known_peak_list_cost_usd"],
                "held_usd": data["unresolved_reserved_usd"],
                "stop_usd": data["stop_usd"],
                "request_cap_usd": str(config.run_policy.max_request_usd),
            }
        except Exception:  # noqa: BLE001 — no credential or ledger error bodies
            return {"status": "unavailable", "reason": "budget_status_unavailable"}

    @app.get("/traces")
    def traces():
        return {"traces": history()}

    @app.get("/code/{component}")
    def component_code(component: str):
        return code_view(component)

    @app.get("/components")
    def components():
        return component_map()

    @app.get("/catalog")
    def catalog(as_of: date):
        try:
            with resources(config, models=False) as (store, *_):
                result = catalog_view(store.catalog(), str(as_of))
                result["index_id"] = store.index_id
            return result
        except Exception:  # noqa: BLE001 — no DB details in read-only browser errors
            raise HTTPException(503, "database_unavailable") from None

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
        cancel = Event()
        app.state.cancellations[qid] = cancel

        def enqueue(kind, payload):
            if disconnected:
                return
            if queue.full():
                queue.get_nowait()  # terminal snapshot remains authoritative
            queue.put_nowait((kind, payload))

        def on_event(kind, row):
            snapshot = event_view(kind, row)  # detach before the worker mutates observations
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
                    cancelled=cancel.is_set,
                )
                enqueue("result", trace_view(data))
            except Exception:  # noqa: BLE001 — no provider/DB exception text in SSE
                enqueue(
                    "failure",
                    {"query_id": qid, "status": "error", "error": {"code": "pipeline_unavailable"}},
                )
            finally:
                app.state.cancellations.pop(qid, None)
                gate.slots.release()  # held even if the browser disconnected

        task = asyncio.create_task(worker())
        app.state.workers.add(task)  # retain a strong reference beyond stream cancellation
        task.add_done_callback(finished)

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
                cancel.set()

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

    @app.post("/queries/{query_id}/cancel")
    async def cancel_query(query_id: str):
        signal = app.state.cancellations.get(query_id)
        if signal is None:
            raise HTTPException(404, "active_query_not_found")
        signal.set()
        return {"query_id": query_id, "status": "cancellation_requested"}

    @app.post("/query")
    async def run(request: Request, http_request: HTTPRequest):
        gate.acquire()
        qid, cancel = uuid4().hex, Event()
        app.state.cancellations[qid] = cancel

        async def worker():
            try:
                return await run_in_threadpool(
                    query, request, config, query_id=qid, cancelled=cancel.is_set
                )
            finally:
                app.state.cancellations.pop(qid, None)
                gate.slots.release()

        task = asyncio.create_task(worker())
        app.state.workers.add(task)
        task.add_done_callback(finished)

        async def watch_disconnect():
            while not task.done():
                if await http_request.is_disconnected():
                    cancel.set()
                    return
                await asyncio.sleep(0.1)

        watcher = asyncio.create_task(watch_disconnect())
        try:
            data = await asyncio.shield(task)
        except asyncio.CancelledError:
            cancel.set()
            raise
        except Exception:  # noqa: BLE001 — protect credentials in startup failures
            raise HTTPException(503, "pipeline_unavailable") from None
        finally:
            watcher.cancel()
            await asyncio.gather(watcher, return_exceptions=True)
        if data["status"] == "error":
            raise HTTPException(
                502,
                {
                    "query_id": data["query_id"],
                    "error": data["error"],
                    "agent": agent_view(data),
                    "fallback": data.get("fallback"),
                    "evidence": trace_view(data)["evidence"] if data.get("fallback") else [],
                },
            )
        return {
            "query_id": data["query_id"],
            "status": data["status"],
            "plan": data.get("plan"),
            "agent": agent_view(data),
            "fallback": data.get("fallback"),
            "generation": {
                "answer": data["generation"]["answer"],
                "sections": data["generation"]["structured_answer"],
            }
            if data.get("generation")
            else None,
            "evidence": data.get("runtime_evidence", []),
        }

    return app
