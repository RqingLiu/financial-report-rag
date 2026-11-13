"""Live observations and managed replay; no database/provider calls."""

import json
from pathlib import Path

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from test_agent_graph import setup_receipts

from finrag.agent.graph import workflow_view
from finrag.agent.runner import execute
from finrag.core.observations import bounded, snapshot
from finrag.core.tracing import Trace
from finrag.serving import history as managed
from finrag.serving.api import create_app
from finrag.serving.config import ServingConfig
from finrag.serving.explorer import event_view, trace_view


def test_graph_state_and_nested_events_reach_browser_without_behavior_change(monkeypatch, tmp_path):
    req, store, model = setup_receipts(monkeypatch, tmp_path)
    events = []
    result = execute(
        req,
        ServingConfig(),
        store,
        model(),
        None,
        on_event=lambda kind, row: events.append(event_view(kind, row)),
    )
    assert result["status"] == "generated"
    sequences = [e["sequence"] for e in events]
    assert sequences == list(range(1, len(events) + 1))
    finished = [e for e in events if e["kind"] == "node_finished"]
    assert len(finished) == 8
    planner = next(e for e in finished if e["node"] == "plan")
    assert planner["state_before"]["request"]["question"] == req.question
    assert planner["state_after"]["plan"]["needs"][0]["id"] == "n1"
    assert "plan" in planner["changed_fields"]
    assert planner["source"]["path"] == "src/finrag/agent/nodes.py"
    assert planner["started_at"] <= planner["ended_at"]
    calls = [e for e in events if e["kind"] == "stage_finished" and e["name"] == "llm_call"]
    assert calls and all(e["operation_id"] for e in calls)
    last = trace_view(result)["agent"]["transitions"][-1]
    assert last["state_after"]["outcome"] == "answered"


def test_stream_keeps_node_identity_state_and_terminal_snapshot(monkeypatch, tmp_path):
    req, store, model = setup_receipts(monkeypatch, tmp_path)

    def fake_query(request, config, *, query_id, on_event, **kwargs):
        return execute(request, config, store, model(), None, query_id=query_id, on_event=on_event)

    monkeypatch.setattr("finrag.serving.api.query", fake_query)
    with TestClient(create_app(ServingConfig())) as client:
        response = client.post("/query/stream", json=req.model_dump(mode="json"))
    assert response.status_code == 200
    assert "event: node_started" in response.text
    assert "event: node_finished" in response.text
    assert '"state_after"' in response.text and '"changed_fields"' in response.text
    blocks = response.text.strip().split("\n\n")
    assert blocks[-1].startswith("event: result")
    data = json.loads(blocks[-1].split("data: ", 1)[1])
    assert data["generation"]["answer"]


def test_state_projection_is_bounded_and_removes_unexpected_data():
    unsafe = {
        "plan": {
            "needs": [{"id": "n1", "api_key": "PRIVATE"}],
            "password": "PRIVATE",
            "clients": object(),
        },
        "provider": object(),
    }
    value = snapshot(unsafe)
    assert "PRIVATE" not in json.dumps(value)
    assert "provider" not in value
    rows = bounded({"ids": list(range(1000)), "headers": "PRIVATE"})
    assert rows["ids"]["total"] == 1000 and len(rows["ids"]["items"]) == 80
    assert rows["ids"]["truncated"] is True
    long = bounded({"answer": "x" * 17000})
    assert long["answer"]["truncated"] is True


def test_observation_exception_is_not_a_query_failure():
    def broken(*args):
        raise RuntimeError("observer failed")

    trace = Trace("id", {}, broken)
    with trace.stage("noop"):
        pass
    assert trace.data["stages"][0]["status"] == "ok"


def test_legacy_state_is_not_invented_and_untrusted_plan_keys_are_removed():
    view = trace_view(
        {
            "agent": {
                "transitions": [
                    {
                        "node": "plan",
                        "status": "ok",
                        "input": {"needs": 0},
                        "output": {"needs": 1, "candidates": 3},
                    }
                ]
            },
            "plan": {"action": "retrieve", "api_key": "PRIVATE"},
        }
    )
    assert "state_after" not in view["agent"]["transitions"][0]
    assert view["agent"]["transitions"][0]["output"]["candidates"] == 3
    assert "PRIVATE" not in json.dumps(view)


def register(tmp_path, monkeypatch):
    monkeypatch.setattr(managed, "ROOT", tmp_path)
    run = tmp_path / "reports/current/accepted_run"
    traces = run / "traces"
    traces.mkdir(parents=True)
    (run / "manifest.json").write_text(json.dumps({"identity": {"selected_ids": ["U01.01"]}}))
    (traces / "U01.01.json").write_text(
        json.dumps(
            {
                "query_id": "U01.01",
                "stages": [],
                "config": {"secret": "PRIVATE"},
                "generation": {"answer": "saved answer"},
            }
        )
    )
    return run


def test_managed_history_reads_evaluation_ids_without_querying_providers(monkeypatch, tmp_path):
    run = register(tmp_path, monkeypatch)
    monkeypatch.setattr("finrag.serving.api.query", lambda *a: pytest.fail("paid query"))
    rows = managed.runs_view()["runs"]
    entry = next(r for r in rows if r["kind"] == "evaluation")
    assert str(tmp_path) not in json.dumps(rows)
    value = managed.case_view(entry["id"], "U01.01")
    assert value["generation"]["answer"] == "saved answer"
    assert "PRIVATE" not in json.dumps(value)
    with TestClient(create_app(ServingConfig())) as client:
        assert client.get(f"/runs/{entry['id']}/cases/U01.01").status_code == 200
        assert client.get("/traces/U01.01").status_code == 404
    for run_id, case in [
        (entry["id"], "../manifest"),
        (entry["id"], "unregistered"),
        ("bad", "U01.01"),
    ]:
        with pytest.raises(HTTPException):
            managed.case_view(run_id, case)
    original = run / "traces/U01.01.json"
    original.unlink()
    original.symlink_to(run / "manifest.json")
    with pytest.raises(HTTPException):
        managed.case_view(entry["id"], "U01.01")


def test_history_does_not_follow_parent_symlinks(monkeypatch, tmp_path):
    run = register(tmp_path, monkeypatch)
    outside = tmp_path / "outside"
    (run / "traces").rename(outside)
    (run / "traces").symlink_to(outside, target_is_directory=True)
    assert not any(r["kind"] == "evaluation" for r in managed.runs_view()["runs"])


def test_workflow_uses_actual_graph_and_code_symbols():
    result = workflow_view(ServingConfig())
    assert len(result["nodes"]) == 10
    assert sum(n["enabled"] for n in result["nodes"]) == 8
    assert any(e["source"] == "plan" and e["target"] == "__end__" for e in result["edges"])
    assert all(n["source"]["path"] == "src/finrag/agent/nodes.py" for n in result["nodes"])
    with TestClient(create_app(ServingConfig())) as client:
        for n in result["nodes"]:
            value = client.get("/code/node_" + n["id"])
            assert value.status_code == 200
            assert value.json()["snippets"][0]["symbol"] == n["source"]["function"]


def test_modular_assets_are_served_with_no_models(monkeypatch):
    monkeypatch.setattr("finrag.serving.api.query", lambda *a: pytest.fail("paid query"))
    root = Path(__file__).parents[1] / "src/finrag/serving/static"
    with TestClient(create_app(ServingConfig())) as client:
        assert 'type="module"' in client.get("/").text
        for asset in [*root.glob("js/*.js"), *root.glob("css/*.css")]:
            assert client.get("/static/" + asset.relative_to(root).as_posix()).status_code == 200


def test_readiness_uses_corrected_stop_without_spending(monkeypatch, tmp_path):
    from finrag.providers.llm import Budget

    monkeypatch.setattr("finrag.core.config.ROOT", tmp_path)
    monkeypatch.setattr("finrag.serving.resources.ROOT", tmp_path)
    monkeypatch.setattr("finrag.serving.api.query", lambda *a: pytest.fail("paid query"))
    ledger = Budget(tmp_path / "data/cache/baseline/budget.jsonl", "5")
    rid = ledger.reserve("3.01", "deepseek", "historical")
    ledger.settle(rid, "3.00418038", {})
    ledger.reserve("0.0093642", "deepseek", "unknown_usage")
    before = ledger.path.read_bytes()
    for stop, expected in [(1.6, "blocked"), (4.9, "available")]:
        with TestClient(create_app(ServingConfig(stop_usd=stop))) as client:
            value = client.get("/readiness").json()
            assert value["status"] == expected
            assert value["request_cap_usd"] == "0.15"
            assert value["known_usd"] == "3.00418038"
            assert value["held_usd"] == "0.0093642"
    assert ledger.path.read_bytes() == before
