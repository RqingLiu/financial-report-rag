"""Browser contracts without a database or paid model calls."""

import asyncio
import json
from threading import Event

import pytest
from fastapi import HTTPException
from fastapi.concurrency import run_in_threadpool
from fastapi.testclient import TestClient

from finrag.planning import Request
from finrag.serving.api import create_app
from finrag.serving.config import ServingConfig
from finrag.serving.explorer import history, load_trace, trace_view
from finrag.tracing import Trace


def test_trace_sink_observes_nested_failure_without_changing_pipeline():
    events = []
    trace = Trace("id", {}, lambda kind, row: events.append((kind, row["name"], row["status"])))
    with trace.stage("parent"), pytest.raises(ValueError), trace.stage("child"):
        raise ValueError("private-provider-body")
    assert events == [
        ("stage_started", "parent", "running"),
        ("stage_started", "child", "running"),
        ("stage_finished", "child", "error"),
        ("stage_finished", "parent", "ok"),
    ]
    assert "private-provider-body" not in json.dumps(trace.data)
    assert trace.data["stages"][1]["parent_id"] == trace.data["stages"][0]["id"]
    trace.on_event = lambda *_: (_ for _ in ()).throw(RuntimeError("observer_failed"))
    with trace.stage("still_works"):
        pass
    assert trace.data["stages"][-1]["status"] == "ok"


def test_browser_projection_retains_evidence_but_excludes_private_payloads():
    trace = Trace("a" * 32, {"original_question": "revenue", "as_of": "2025-01-01"})
    with trace.stage(
        "llm_call", {"messages": [{"content": "PRIVATE_SYSTEM_PROMPT"}], "purpose": "query_plan"}
    ) as row:
        row["outputs"] = {
            "answer": "PRIVATE_MODEL_BODY",
            "usage": {"total_tokens": 30},
            "peak_list_cost_usd": ".001",
            "provider_response_id": "PRIVATE_ID",
        }
    with trace.stage("query_plan") as row:
        row["outputs"] = {
            "messages": "PRIVATE_PLAN_PROMPT",
            "api_result": "PRIVATE_BODY",
            "validated_plan": {"action": "clarify"},
            "cached": False,
        }
    with trace.stage("rerank") as row:
        row["outputs"] = {
            "scores": {"chunk": {"s": 4, "n": ["n1"]}},
            "event": [{"cached": True, "cache_key": "PRIVATE_CACHE"}],
        }
    trace.data.update(
        config={"api_key": "PRIVATE_KEY"},
        runtime_evidence=[
            {
                "citation": "E1",
                "text": "<script>source</script>",
                "source_url": "https://www.sec.gov/example",
            }
        ],
        generation={"answer": "revenue [E1]", "messages": "PRIVATE_PROMPT"},
    )
    view = trace_view(trace.data)
    assert "PRIVATE" not in json.dumps(view)
    assert view["evidence"][0]["text"] == "<script>source</script>"
    assert view["generation"]["answer"] == "revenue [E1]"
    assert view["stages"][0]["outputs"]["usage"]["total_tokens"] == 30
    assert view["stages"][2]["outputs"]["scores"]["chunk"]["s"] == 4


def test_history_only_reads_managed_bounded_files(tmp_path, monkeypatch):
    from finrag.serving import explorer

    qid = "a" * 32
    (tmp_path / f"{qid}.json").write_text(json.dumps({"query_id": qid, "stages": []}))
    (tmp_path / "other.json").write_text("not a trace")
    (tmp_path / f"{'b' * 32}.json").symlink_to(tmp_path / "other.json")
    assert [r["query_id"] for r in history(tmp_path)] == [qid]
    assert load_trace(qid, tmp_path)["query_id"] == qid
    for bad in ("../other", "other", "b" * 32, "c" * 32):
        with pytest.raises(HTTPException) as err:
            load_trace(bad, tmp_path)
        assert err.value.status_code == 404
    monkeypatch.setattr(explorer, "MAX_TRACE_BYTES", 2)
    with pytest.raises(HTTPException) as err:
        load_trace(qid, tmp_path)
    assert err.value.status_code == 413


def test_static_history_is_read_only_and_packaged(monkeypatch, tmp_path):
    qid = "d" * 32
    (tmp_path / f"{qid}.json").write_text(json.dumps({"query_id": qid, "stages": []}))
    monkeypatch.setattr("finrag.serving.explorer.TRACE_DIR", tmp_path)
    monkeypatch.setattr("finrag.serving.api.query", lambda *_: pytest.fail("read called model"))
    client = TestClient(create_app(ServingConfig()))
    page = client.get("/")
    assert page.status_code == 200 and "Trace Explorer" in page.text
    assert "script-src 'self'" in page.headers["content-security-policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/traces").json()["traces"][0]["query_id"] == qid
    assert client.get(f"/traces/{qid}").json()["query_id"] == qid
    assert client.get("/traces/not-an-id").status_code == 404


def test_browser_rejects_foreign_origins_and_rebinding_hosts():
    client = TestClient(create_app(ServingConfig()))
    assert client.get("/", headers={"host": "attacker.example"}).status_code == 400
    for origin in ("https://attacker.example", "null"):
        assert (
            client.post(
                "/query/stream",
                headers={"origin": origin},
                json={"question": "q", "as_of": "2025-01-01"},
            ).status_code
            == 403
        )
    page = client.get("/", headers={"origin": "http://127.0.0.1:8000"})
    assert page.status_code == 200 and page.headers["cache-control"] == "no-store"


def test_stream_emits_real_stages_and_terminal_snapshot(monkeypatch):
    def fake_query(request, config, *, query_id, on_event, do_generate):
        assert do_generate is False
        trace = Trace(query_id, {"original_question": request.question}, on_event)
        with trace.stage("catalog_snapshot") as row:
            row["outputs"] = {"documents": 1}
        with trace.stage("query_plan") as row:
            row["outputs"] = {
                "cached": True,
                "messages": "PRIVATE",
                "validated_plan": {"action": "clarify"},
            }
        trace.data.update(status="clarify", plan={"action": "clarify"})
        return trace.data

    monkeypatch.setattr("finrag.serving.api.query", fake_query)
    with TestClient(create_app(ServingConfig())) as client:
        response = client.post(
            "/query/stream?generate=false",
            json={"question": "which company?", "as_of": "2025-01-01"},
        )
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    blocks = response.text.strip().split("\n\n")
    assert [b.splitlines()[0] for b in blocks] == [
        "event: accepted",
        "event: stage_started",
        "event: stage_finished",
        "event: stage_started",
        "event: stage_finished",
        "event: result",
    ]
    assert "PRIVATE" not in response.text
    final = json.loads(blocks[-1].split("data: ", 1)[1])
    assert final["status"] == "clarify" and len(final["stages"]) == 2


def test_stream_failure_redacts_exception_and_releases_slot(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_PASSWORD")

    monkeypatch.setattr("finrag.serving.api.query", fail)
    with TestClient(create_app(ServingConfig(max_inflight=1))) as client:
        for _ in range(2):
            r = client.post("/query/stream", json={"question": "q", "as_of": "2025-01-01"})
            assert "event: failure" in r.text and "PRIVATE" not in r.text


def test_disconnect_keeps_admission_until_real_worker_finishes(monkeypatch):
    started, release = Event(), Event()

    def slow(*args, query_id, **kwargs):
        started.set()
        assert release.wait(5)
        return {"query_id": query_id, "status": "clarify", "stages": []}

    monkeypatch.setattr("finrag.serving.api.query", slow)

    async def scenario():
        app = create_app(ServingConfig(max_inflight=1))
        endpoint = next(r.endpoint for r in app.routes if r.path == "/query/stream")
        response = await endpoint(Request(question="q", as_of="2025-01-01"), generate=False)
        iterator = response.body_iterator
        assert "accepted" in await anext(iterator)
        assert await run_in_threadpool(started.wait, 3)
        await iterator.aclose()  # browser disconnects, but paid work is still active
        try:
            with pytest.raises(HTTPException) as err:
                await endpoint(Request(question="q", as_of="2025-01-01"), generate=False)
            assert err.value.status_code == 429 and len(app.state.workers) == 1
        finally:
            release.set()
        await asyncio.gather(*app.state.workers)
        with app.state.admission.enter():
            pass

    asyncio.run(scenario())


def test_code_registry_is_bounded_and_rejects_arbitrary_paths():
    from finrag.serving.code_view import COMPONENTS

    client = TestClient(create_app(ServingConfig()))
    for component in COMPONENTS:
        response = client.get(f"/code/{component}")
        assert response.status_code == 200
        payload = response.json()
        assert payload["version"] == "current_checkout"
        for snippet in payload["snippets"]:
            assert snippet["path"].startswith("src/finrag/")
            assert len(snippet["sha256"]) == 64
            assert len(snippet["text"].splitlines()) <= 140
            assert snippet["start_line"] <= snippet["end_line"]
    for name in (".env", "config", "unknown", "..%2F.env"):
        assert client.get(f"/code/{name}").status_code == 404


def test_new_span_has_real_callsite_and_legacy_is_not_reconstructed():
    from hashlib import sha256
    from pathlib import Path

    trace = Trace("a" * 32, {})
    with trace.stage("catalog_snapshot"):
        pass
    source = trace.data["stages"][0]["source"]
    assert source["path"] == "tests/test_explorer.py"
    assert source["function"] == "test_new_span_has_real_callsite_and_legacy_is_not_reconstructed"
    content = Path(__file__).read_bytes()
    assert source["sha256"] == sha256(content).hexdigest()
    assert 'trace.stage("catalog_snapshot")' in content.decode().splitlines()[source["line"] - 1]
    assert trace_view(trace.data)["stages"][0]["source"] == source
    del trace.data["stages"][0]["source"]
    assert "source" not in trace_view(trace.data)["stages"][0]


def test_known_model_business_payload_omits_unexpected_nested_fields():
    payload = {
        "request": {"question": "Revenue?", "api_key": "PRIVATE_KEY"},
        "catalog": [{"ticker": "ANY", "headers": "PRIVATE_HEADER"}],
        "response_contract": "PRIVATE_SCHEMA",
    }
    trace = Trace("a" * 32, {})
    with trace.stage(
        "llm_call",
        {
            "purpose": "query_planning",
            "messages": [
                {"role": "system", "content": "PRIVATE_PROMPT"},
                {"role": "user", "content": json.dumps(payload)},
            ],
        },
    ) as row:
        row["outputs"] = {"answer": "PRIVATE_RESPONSE", "usage": {"total_tokens": 20}}
    view = trace_view(trace.data)
    business = view["stages"][0]["inputs"]["business_payload"]
    assert business == {"request": {"question": "Revenue?"}, "catalog": [{"ticker": "ANY"}]}
    assert "PRIVATE" not in json.dumps(view)


def test_component_map_matches_allowlisted_code_and_explains_shared_calls():
    client = TestClient(create_app(ServingConfig()))
    components = client.get("/components").json()["components"]
    assert {
        "catalog_snapshot",
        "query_plan",
        "retrieve",
        "rerank",
        "entry",
        "ingestion",
    } <= components.keys()
    for component, refs in components.items():
        snippets = client.get(f"/code/{component}").json()["snippets"]
        assert len(refs) == len(snippets)
        for ref, snippet in zip(refs, snippets, strict=True):
            assert "text" not in ref and ref["role"]
            assert all(ref[k] == snippet[k] for k in ref)
    assert any(r["symbol"] == "DeepSeek.generate" for r in components["rerank"])
    assert any(r["symbol"] == "execute" for r in components["entry"])


def test_current_catalog_is_published_read_only_and_filters_asof(monkeypatch, tmp_path):
    from contextlib import contextmanager
    from types import SimpleNamespace

    from finrag.models import Filing
    from finrag.planning import Catalog

    def filing(doc, filed):
        return Filing(
            id=doc,
            ticker="ANY",
            cik=1,
            fiscal_year=2024,
            form="10-K",
            accession=doc,
            period_end="2024-12-31",
            filed_at=filed,
            source_url="https://www.sec.gov/example",
        )

    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    (raw / "ANY_FY2024.html").write_text("local original")
    monkeypatch.setattr("finrag.serving.explorer.ROOT", tmp_path)

    @contextmanager
    def resources(config, *, models):
        assert models is False
        yield (
            SimpleNamespace(
                index_id="index-test",
                catalog=lambda: Catalog(
                    [filing("ANY_FY2024", "2025-02-01"), filing("ANY_FY2025", "2026-02-01")]
                ),
            ),
            None,
            None,
            None,
        )

    monkeypatch.setattr("finrag.serving.api.resources", resources)
    client = TestClient(create_app(ServingConfig()))
    result = client.get("/catalog?as_of=2025-02-01").json()
    assert result["source"] == "current_published_database"
    assert result["index_id"] == "index-test" and result["documents"] == 1
    assert result["filings"][0]["local_raw_path"] == "data/raw/ANY_FY2024.html"
    assert result["filings"][0]["source_url"] == "https://www.sec.gov/example"
    assert result["truncated"] is False
    assert client.get("/catalog").status_code == 422
    assert client.get("/catalog?as_of=invalid").status_code == 422


def test_catalog_failure_does_not_expose_database_details(monkeypatch):
    def fail(*args, **kwargs):
        raise RuntimeError("PRIVATE_DSN")

    monkeypatch.setattr("finrag.serving.api.resources", fail)
    response = TestClient(create_app(ServingConfig())).get("/catalog?as_of=2025-02-01")
    assert response.status_code == 503
    assert response.json() == {"detail": "database_unavailable"}
