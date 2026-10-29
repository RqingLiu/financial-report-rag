"""Read-only audit of completed ANN fixtures/measurements; no APIs or serving writes."""

import json
import platform
from pathlib import Path

import numpy as np
from psycopg import sql

from finrag.config import ROOT
from finrag.experiments.ann_scale import BenchConfig, connect, plans_contain, source_snapshot
from finrag.files import atomic_json, digest
from finrag.serving.runtime import load_config, shared_budget

run = ROOT / "reports/ann_scale/20261028_scale_v1"
if (run / "cleanup.json").exists():
    raise SystemExit(
        "Fixture cleaned: see cleanup.json for deletion checks and validation.json for the "
        "historical live-fixture audit. Rebuild into a NEW_RUN for another live audit."
    )
manifest = json.loads((run / "manifest.json").read_text())
config = BenchConfig(**manifest["config"])
result = {
    "host": {
        "platform": platform.platform(),
        "python": platform.python_version(),
        "physical_memory_bytes_preflight": 17179869184,
        "logical_cpus_preflight": 10,
    },
    "measurement_files": 0,
    "samples": 0,
    "errors": 0,
    "representative_ann_plans_verified": 0,
}
for size in config.sizes:
    expected = json.loads((run / "exact" / f"{size}.json").read_text())
    assert len(expected["samples"]) == config.query_count * config.repeats * len(
        config.selectivities
    )
    for pct in config.selectivities:
        assert not plans_contain(expected["plans"][str(pct)], f"ann_{size}_hnsw")
    for p in sorted((run / "measurements" / str(size)).glob("*.json")):
        d = json.loads(p.read_text())
        result["measurement_files"] += 1
        assert len(d["samples"]) == config.query_count * config.repeats * len(config.selectivities)
        for s in d["samples"]:
            result["samples"] += 1
            if s["status"] == "error":
                result["errors"] += 1
                continue
            assert 0 <= s["strict_overlap"] <= 1 and 0 <= s["boundary_equivalent"] <= 1
            assert 0 <= s["returned"] <= config.k and s["latency_ms"] > 0
        for pct, plan in d["plans"].items():
            assert any(
                plans_contain(plan, b["index"])
                for b in json.loads((run / "summary.json").read_text())["builds"]
            )
            result["representative_ann_plans_verified"] += 1
with connect(config) as conn:
    tables = conn.execute(
        "SELECT t.relname,pg_total_relation_size(t.oid) bytes FROM pg_class t "
        "JOIN pg_namespace n ON n.oid=t.relnamespace WHERE n.nspname=%s AND t.relkind='r' ORDER BY t.relname",
        (manifest["schema"],),
    ).fetchall()
    result["retained_fixture_tables"] = tables
    result["retained_fixture_bytes"] = sum(t["bytes"] for t in tables)
    pairs = []
    for n in config.sizes:
        # Verify source bits at a deterministic sample of IDs between both full-size copies.
        ids = np.random.default_rng(config.seed + n).choice(n, size=64, replace=False).tolist()
        left = sql.Identifier(manifest["schema"], f"vectors_{n}_hnsw")
        right = sql.Identifier(manifest["schema"], f"vectors_{n}_ivfflat")
        row = conn.execute(
            sql.SQL(
                "SELECT count(*) n,bool_and(l.embedding=r.embedding AND "
                "l.document_id=r.document_id AND l.filed_at=r.filed_at) same FROM {} l JOIN {} r USING(id) "
                "WHERE l.id=ANY(%s)"
            ).format(left, right),
            (ids,),
        ).fetchone()
        assert row["n"] == 64 and row["same"]
        pairs.append({"rows": n, "sample_equal": 64})
    result["paired_copy_checks"] = pairs
    for memory_m in (16, 32):
        row = conn.execute(
            sql.SQL("SELECT count(*) n FROM {}").format(
                sql.Identifier(manifest["schema"], f"vectors_100000_hnsw_m{memory_m}_mem512")
            )
        ).fetchone()
        assert row["n"] == 100000
result["source_unchanged"] = source_snapshot() == manifest["source_before"]
assert result["source_unchanged"] and result["errors"] == 0
result["paid_budget"] = shared_budget(load_config()).snapshot()
result["new_api_calls"] = 0
result["code_sha256"] = {
    str(p.relative_to(ROOT)): digest(p.read_bytes())
    for p in [
        ROOT / "src/finrag/experiments/ann_scale.py",
        ROOT / "src/finrag/experiments/ann_construction.py",
        ROOT / "tests/test_ann_scale.py",
        Path(__file__).resolve(),
    ]
}
old = json.loads(
    (ROOT / "reports/serving/20261028_objective_v4/final_source_manifest.json").read_text()
)
result["previous_configs_unchanged"] = all(
    digest((ROOT / p).read_bytes()) == h for p, h in old["config_sha256"].items()
)
assert result["previous_configs_unchanged"]
atomic_json(run / "validation.json", result)
print(
    json.dumps(
        {
            k: v
            for k, v in result.items()
            if k not in ["code_sha256", "retained_fixture_tables", "paid_budget"]
        },
        indent=2,
    )
)
