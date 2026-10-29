"""Audit saved contexts against source spans, caps and fixed SQL budgets; no model calls."""

import json

from finrag.config import ROOT
from finrag.files import atomic_json
from finrag.planned_retrieval import prepare_searches
from finrag.planning import Plan
from finrag.serving.regroup import validate_regroup
from finrag.serving.runtime import load_config, resources, shared_budget

run = ROOT / "reports/serving/20261028_objective_v4"
cfg = load_config().model_copy(update={"sql_timeout_ms": 60000})  # offline full-payload audit only
checks = {"questions": 0, "contexts": 0, "source_spans": 0, "sql_total": {}, "answers": 0}
with resources(cfg, models=False) as (store, *_):
    catalog = store.catalog()
    for arm in ["wide_dense", "wide_hybrid", "regroup_dense"]:
        total = 0
        for path in sorted((run / arm).glob("U*.json")):
            d = json.loads(path.read_text())
            total += d["sql_job_count"]
            assert d["sql_job_count"] <= d["base_sql_job_count"]
            if arm == "regroup_dense":
                old = Plan(**d["answer_plan"])
                new = Plan(**d["plan"])
                validate_regroup(old, new.tasks, catalog, cfg.pipeline)
                assert len(prepare_searches(new, catalog, cfg.pipeline)) == d["sql_job_count"]
            for context in d["contexts"].values():
                checks["contexts"] += 1
                m = context["metadata"]
                assert m["evidence_tokens"] <= m["evidence_token_cap"]
                assert m["full_prompt_proxy_tokens"] <= m["full_prompt_cap"]
                assert m["selected_items"] <= 30
                for e in context["runtime_evidence"]:
                    f = catalog.by_id[e["document_id"]]
                    assert e["filed_at"] <= d["inputs"]["as_of"] and e["filed_at"] == f.filed_at
                    ids = list({s["block_id"] for s in e["source_spans"]})
                    blocks = {r["payload"]["id"]: r["payload"] for r in store.block_payloads(ids)}
                    for span in e["source_spans"]:
                        b = blocks[span["block_id"]]
                        assert b["document_id"] == e["document_id"]
                        assert b["start"] <= span["start"] < span["end"] <= b["end"]
                        text = b["text"][span["start"] - b["start"] : span["end"] - b["start"]]
                        assert text in e["text"]
                        checks["source_spans"] += 1
            checks["questions"] += 1
        checks["sql_total"][arm] = total
    for path in sorted((run / "answers").glob("*/*/*.json")):
        d = json.loads(path.read_text())
        assert d["status"] == "generated"
        expected = {n["id"] for n in d["plan"]["needs"]}
        assert {s["need_id"] for s in d["generation"]["structured_answer"]["sections"]} == expected
        checks["answers"] += 1
    checks["serving_documents"] = len(catalog.filings)
    checks["serving_chunks"] = store.connection.execute(
        "SELECT n FROM finrag_live_ready.indexes"
    ).fetchone()["n"]
    checks["frozen_chunks"] = store.connection.execute(
        "SELECT count(*) n FROM finrag.chunks"
    ).fetchone()["n"]
    checks["identical_frozen_chunks"] = store.connection.execute(
        "SELECT count(*) n FROM finrag_live_ready.chunks l "
        "JOIN finrag.chunks f ON f.id=l.id WHERE f.payload=l.payload AND f.embedding=l.embedding"
    ).fetchone()["n"]
    assert checks["serving_chunks"] == checks["identical_frozen_chunks"] == 2759
    assert checks["frozen_chunks"] == 11401
    checks["budget"] = shared_budget(cfg).snapshot()
    checks["scope"] = (
        "Saved context/source/caps/structure checks; not numeric or semantic answer correctness"
    )
atomic_json(ROOT / "reports/serving/validation.json", checks)
print(json.dumps(checks, indent=2))
