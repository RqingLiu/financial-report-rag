import json
import os
import struct
from uuid import uuid4

import numpy as np
import pytest
from psycopg import sql

from finrag.experiments.ann_scale import (
    BenchConfig,
    Profile,
    benchmark_profile,
    binary_rows,
    build,
    connect,
    exact_reference,
    fixture_batch,
    metrics,
    prepare,
    require_live_fixture,
    scope_documents,
    table_name,
)


def test_synthetic_generation_reproducible_finite_distinct_and_bounded():
    source = np.random.default_rng(7).normal(size=(10, 8)).astype(np.float32)
    source /= np.linalg.norm(source, axis=1, keepdims=True)
    one = fixture_batch(source, 0, 40, np.random.default_rng(1), 0.008)
    two = fixture_batch(source, 0, 40, np.random.default_rng(1), 0.008)
    assert np.array_equal(one, two)
    assert np.allclose(np.linalg.norm(one, axis=1), 1)
    assert not np.array_equal(one[0], one[10])
    assert np.allclose(one[:10], source)
    assert struct.unpack("!h", binary_rows(one[:1], 0)[:2])[0] == 5
    assert len(scope_documents(1, 8)) == 1 and len(set(scope_documents(100, 8))) == 100
    with pytest.raises(ValueError):
        table_name("finrag_live_ready", 1000, "hnsw")
    with pytest.raises(ValueError):
        BenchConfig(
            sizes=[1000000], source_traces="x", profiles=[Profile(method="hnsw")]
        ).validate_limits()


def test_metrics_distinguish_neighbor_identity_ties_and_underfill():
    expected = [{"id": 1, "distance": 0.1}, {"id": 2, "distance": 0.2}]
    found = [{"id": 3, "distance": 0.2}]
    result = metrics(expected, found, 2)
    assert result == {"strict_overlap": 0, "boundary_equivalent": 0.5, "underfill": True}
    assert metrics([], [], 2)["strict_overlap"] is None


def test_cleaned_run_rejects_resume_before_source_reads(tmp_path):
    require_live_fixture(tmp_path)
    (tmp_path / "cleanup.json").write_text('{"status":"completed"}')
    cfg = BenchConfig(sizes=[1000], source_traces="unused", profiles=[Profile(method="hnsw")])
    with pytest.raises(ValueError, match="cleaned_create_new_run"):
        prepare(tmp_path, cfg)
    with pytest.raises(ValueError, match="cleaned_create_new_run"):
        build(tmp_path, cfg, {}, 1000, "hnsw")
    from finrag.experiments.ann_construction import construction

    with pytest.raises(ValueError, match="cleaned_create_new_run"):
        construction(tmp_path, cfg, {}, 100000, 512, 16)


@pytest.mark.skipif(os.getenv("FINRAG_INTEGRATION") != "1", reason="opt-in local PostgreSQL")
def test_real_binary_copy_exact_and_both_ann_paths(tmp_path):
    cfg = BenchConfig(
        sizes=[1000],
        query_count=4,
        repeats=1,
        k=5,
        source_traces="unused",
        profiles=[Profile(method="hnsw"), Profile(method="ivfflat", probes=2)],
    )
    schema = "finrag_ann_bench_" + uuid4().hex[:12]
    source = np.random.default_rng(7).normal(size=(17, 8)).astype(np.float32)
    source /= np.linalg.norm(source, axis=1, keepdims=True)
    np.save(tmp_path / "source_vectors.npy", source)
    manifest = {"schema": schema, "source": {"source_vector_sha256": "test"}}
    queries = [{"id": str(i), "vector": v.tolist()} for i, v in enumerate(source[:4])]
    with connect(cfg) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
    try:
        build(tmp_path, cfg, manifest, 1000, "hnsw")
        exact = exact_reference(tmp_path, cfg, manifest, 1000, queries)
        for profile in cfg.profiles:
            result = benchmark_profile(tmp_path, cfg, manifest, 1000, profile, queries, exact)
            assert all(s["status"] == "ok" for s in result["samples"])
            assert all(s["returned"] == 5 for s in result["samples"])
            assert all(0 <= s["strict_overlap"] <= 1 for s in result["samples"])
        assert json.loads((tmp_path / "fixtures/1000_hnsw.json").read_text())["checks"]["n"] == 1000
    finally:
        # Only this test's freshly created random fixture namespace, never an existing schema.
        with connect(cfg) as conn:
            conn.execute(sql.SQL("DROP SCHEMA {} CASCADE").format(sql.Identifier(schema)))


def test_construction_controls_reject_serving_namespace_before_connect(tmp_path):
    from finrag.experiments.ann_construction import construction

    cfg = BenchConfig(sizes=[1000], source_traces="unused", profiles=[Profile(method="hnsw")])
    with pytest.raises(ValueError, match="bounded_design"):
        construction(tmp_path, cfg, {"schema": "finrag_live_ready"}, 100000, 512, 16)
