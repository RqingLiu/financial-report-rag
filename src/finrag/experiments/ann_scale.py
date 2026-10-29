"""Isolated ANN scale experiment. Synthetic vectors, cached real queries, zero APIs.

SQL-only timings and backend RSS are not financial evidence quality or service capacity.
"""

import argparse
import json
import math
import re
import struct
import subprocess
import threading
import time
from contextlib import contextmanager
from datetime import UTC, date, datetime
from pathlib import Path
from statistics import mean
from uuid import uuid4

import numpy as np
import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from pydantic import BaseModel, ConfigDict, Field

from ..chunk import config_id
from ..config import ROOT, settings
from ..files import atomic_json, digest
from ..planned_retrieval import prepare_searches
from ..planning import Plan
from ..serving.runtime import load_config, resources

VERSION = "ann-scale-v1"
SCHEMA_RE = re.compile(r"^finrag_ann_bench_[a-f0-9]{12}$")
COPY_HEADER = b"PGCOPY\n\xff\r\n\0" + struct.pack("!ii", 0, 0)
AS_OF = "2026-10-28"  # Synthetic publication date is fixed 2026-01-01; all are eligible.


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    method: str = Field(pattern="^(hnsw|ivfflat)$")
    ef_search: int = Field(default=100, ge=20, le=1000)
    max_scan: int = Field(default=20000, ge=100, le=100000)
    probes: int = Field(default=10, ge=1, le=1000)
    max_probes: int = Field(default=10000, ge=1, le=10000)

    def key(self):
        return (
            f"hnsw_ef{self.ef_search}_scan{self.max_scan}"
            if self.method == "hnsw"
            else f"ivf_probe{self.probes}_max{self.max_probes}"
        )


class BenchConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sizes: list[int] = Field(min_length=1, max_length=4)
    seed: int = 20261028
    noise_std: float = Field(default=0.008, gt=0, le=0.1)
    query_count: int = Field(default=24, ge=4, le=100)
    repeats: int = Field(default=2, ge=1, le=5)
    k: int = Field(default=20, ge=1, le=100)
    selectivities: list[int] = Field(default_factory=lambda: [100, 10, 1])
    maintenance_mb: int = Field(default=256, ge=32, le=512)
    work_mb: int = Field(default=8, ge=1, le=32)
    build_timeout_ms: int = Field(default=900000, ge=1000, le=1800000)
    query_timeout_ms: int = Field(default=30000, ge=100, le=60000)
    source_traces: str
    profiles: list[Profile] = Field(min_length=1, max_length=12)

    def validate_limits(self):
        if any(n < 1000 or n > 100000 for n in self.sizes) or len(set(self.sizes)) != len(
            self.sizes
        ):
            raise ValueError("benchmark_size_limit_100k")
        if set(self.selectivities) - {1, 10, 100} or len(set(self.selectivities)) != len(
            self.selectivities
        ):
            raise ValueError("benchmark_selectivity_limit")
        if len({p.key() for p in self.profiles}) != len(self.profiles):
            raise ValueError("duplicate_parameter_profile")
        return self


def connect(config):
    conn = psycopg.connect(
        settings().database_url.get_secret_value(),
        autocommit=True,
        row_factory=dict_row,
        connect_timeout=5,
    )
    for key, value in [
        ("maintenance_work_mem", f"{config.maintenance_mb}MB"),
        ("work_mem", f"{config.work_mb}MB"),
        ("max_parallel_maintenance_workers", "0"),
        ("max_parallel_workers_per_gather", "0"),
        ("statement_timeout", str(config.build_timeout_ms)),
    ]:
        conn.execute("SELECT set_config(%s,%s,false)", (key, value))
    return conn


def scope_documents(percent, query_index):
    if percent not in (1, 10, 100):
        raise ValueError("invalid_selectivity")
    start = (query_index * 17) % 100
    return [f"scope_{(start + i) % 100:02}" for i in range(percent)]


def fixture_batch(source, start, count, rng, noise_std):
    source = np.asarray(source, dtype=np.float32)
    ids = np.arange(start, start + count)
    vectors = source[ids % len(source)].copy()
    noise = rng.normal(0, noise_std, size=vectors.shape).astype(np.float32)
    # Keep one copy of the original vector set; perturb the appended rows to avoid replicas.
    noise[ids < len(source)] = 0
    vectors += noise
    norms = np.linalg.norm(vectors, axis=1, keepdims=True)
    if not np.isfinite(vectors).all() or np.any(norms <= 0):
        raise ValueError("invalid_generated_vectors")
    return (vectors / norms).astype(np.float32)


def binary_rows(vectors, start):
    """PostgreSQL binary COPY: id/int8, index/text, document/text, date/int4, pgvector."""
    days = (date(2026, 1, 1) - date(2000, 1, 1)).days
    result = bytearray()
    for offset, vector in enumerate(vectors):
        identifier = start + offset
        fields = [
            struct.pack("!q", identifier),
            b"fixture",
            f"scope_{identifier % 100:02}".encode(),
            struct.pack("!i", days),
            struct.pack("!hh", len(vector), 0) + vector.astype(">f4").tobytes(),
        ]
        result.extend(struct.pack("!h", len(fields)))
        for value in fields:
            result.extend(struct.pack("!i", len(value)))
            result.extend(value)
    return bytes(result)


def cpu_seconds(value):
    parts = value.strip().split(":")
    return sum(float(part) * 60**i for i, part in enumerate(reversed(parts)))


def process_sample(pid):
    # Inspect only this owned PostgreSQL backend; no process arguments or other services.
    try:
        output = subprocess.check_output(
            ["ps", "-o", "rss=", "-o", "time=", "-p", str(pid)],
            text=True,
            stderr=subprocess.DEVNULL,
        ).split()
        return int(output[0]) * 1024, cpu_seconds(output[1])
    except (OSError, subprocess.SubprocessError, ValueError, IndexError):
        return None, None


@contextmanager
def monitor(conn):
    pid = conn.execute("SELECT pg_backend_pid() pid").fetchone()["pid"]
    initial, cpu = process_sample(pid)
    state = {
        "pid": pid,
        "rss_before_bytes": initial,
        "sampled_peak_backend_rss_bytes": initial,
        "sample_interval_seconds": 0.5,
    }
    done = threading.Event()

    def collect():
        while not done.wait(0.5):
            rss, _ = process_sample(pid)
            if rss is not None:
                state["sampled_peak_backend_rss_bytes"] = max(
                    state["sampled_peak_backend_rss_bytes"] or 0, rss
                )

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    started = time.perf_counter()
    try:
        yield state
    finally:
        done.set()
        thread.join(timeout=1)
        rss, after_cpu = process_sample(pid)
        if rss is not None:
            state["sampled_peak_backend_rss_bytes"] = max(
                state["sampled_peak_backend_rss_bytes"] or 0, rss
            )
        state.update(
            wall_seconds=time.perf_counter() - started,
            backend_cpu_seconds=after_cpu - cpu
            if after_cpu is not None and cpu is not None
            else None,
        )


def source_snapshot():
    with resources(load_config(), models=False) as (store, *_):
        index_id = config_id(store.index_config)
        snap = store.connection.execute(
            sql.SQL(
                "SELECT count(*) n, md5(string_agg("
                "md5(id||embedding::text),'|' ORDER BY id)) fingerprint FROM {} WHERE index_id=%s"
            ).format(store.table("chunks")),
            (index_id,),
        ).fetchone()
        return {"namespace": store.config.namespace, "index_id": index_id, **snap}


def inputs(config):
    with resources(load_config(), models=False) as (store, *_):
        rows = store.connection.execute(
            sql.SQL(
                "SELECT id,embedding::text vector FROM {} WHERE index_id=%s ORDER BY id"
            ).format(store.table("chunks")),
            (store.index_id,),
        ).fetchall()
        source = np.asarray([json.loads(r["vector"]) for r in rows], dtype=np.float32)
        model, dim = store.index_config.embedding_model, store.index_config.dimension
        catalog = store.catalog()
        by_question = []
        trace_dir = (ROOT / config.source_traces).resolve()
        if not trace_dir.is_relative_to(ROOT):
            raise ValueError("source_trace_path_outside_project")
        for path in sorted(trace_dir.glob("U*.json")):
            data = json.loads(path.read_text())
            queries = list(
                dict.fromkeys(
                    j["query"]
                    for j in prepare_searches(Plan(**data["plan"]), catalog, load_config().pipeline)
                    if j["method"] == "dense"
                )
            )
            by_question.append((path.stem, queries))
        selected = []
        for pos in range(max(len(qs) for _, qs in by_question)):
            for qid, qs in by_question:
                if pos >= len(qs):
                    continue
                text = qs[pos]
                key = digest(json.dumps([model, dim, "query", text]))
                path = ROOT / "data/cache/embeddings" / f"{key}.json"
                vector = json.loads(path.read_text())
                if len(vector) != dim or not all(math.isfinite(x) for x in vector):
                    raise ValueError("query_cache_vector_invalid")
                selected.append(
                    {
                        "id": f"{qid}_{pos}",
                        "question_id": qid,
                        "query": text,
                        "vector": vector,
                        "cache_key": key,
                        "cache_sha256": digest(path.read_bytes()),
                    }
                )
                if len(selected) == config.query_count:
                    break
            if len(selected) == config.query_count:
                break
        if len(selected) != config.query_count or source.shape[1] != dim:
            raise ValueError("incomplete_benchmark_inputs")
        return (
            source,
            selected,
            {
                "model": model,
                "dimension": dim,
                "source_rows": len(source),
                "source_vector_sha256": digest(source.tobytes()),
                "source_ids_sha256": digest(json.dumps([r["id"] for r in rows])),
            },
        )


def table_name(schema, n, method):
    if not SCHEMA_RE.fullmatch(schema) or method not in ("hnsw", "ivfflat") or not 1 <= n <= 100000:
        raise ValueError("invalid_fixture_target")
    return sql.Identifier(schema, f"vectors_{n}_{method}")


def require_live_fixture(run):
    if (run / "cleanup.json").exists():
        raise ValueError("benchmark_fixture_cleaned_create_new_run; saved summary remains available")


def prepare(run, config):
    require_live_fixture(run)
    manifest_path = run / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        if manifest["config"] != config.model_dump() or manifest["version"] != VERSION:
            raise ValueError("config_changed_create_new_run")
        return manifest
    source, queries, meta = inputs(config)
    schema = "finrag_ann_bench_" + uuid4().hex[:12]
    with connect(config) as conn:
        conn.execute(sql.SQL("CREATE SCHEMA {}").format(sql.Identifier(schema)))
        conn.execute(
            sql.SQL("COMMENT ON SCHEMA {} IS {}").format(
                sql.Identifier(schema), sql.Literal("FinRAG synthetic ANN fixture; run " + str(run))
            )
        )
        pg = conn.execute(
            "SELECT version() postgres,(SELECT extversion FROM pg_extension WHERE extname='vector') pgvector"
        ).fetchone()
    atomic_json(run / "queries.json", queries)
    # Small source matrix only, no synthetic 100k matrix held in Python memory.
    np.save(run / "source_vectors.npy", source, allow_pickle=False)
    manifest = {
        "version": VERSION,
        "created_at": datetime.now(UTC).isoformat(),
        "schema": schema,
        "config": config.model_dump(),
        "source": meta,
        "source_before": source_snapshot(),
        "query_sha256": digest((run / "queries.json").read_bytes()),
        "database": pg,
        "recipe": "source clusters + seeded Gaussian std .008 (configurable), unit normalization; "
        "synthetic independent 100 document buckets; no new real reports",
        "limits": "single client; parallel workers0; no global settings/cache flush; SQL-only timings",
        "code_sha256": digest(Path(__file__).read_bytes()),
    }
    atomic_json(manifest_path, manifest)
    return manifest


def load_fixture(run, config, manifest, n, method):
    require_live_fixture(run)
    target = run / "fixtures" / f"{n}_{method}.json"
    if target.exists():
        return json.loads(target.read_text())
    source = np.load(run / "source_vectors.npy", allow_pickle=False)
    schema = manifest["schema"]
    table = table_name(schema, n, method)
    with connect(config) as conn:
        exists = conn.execute(
            "SELECT to_regclass(%s) relation", (f"{schema}.vectors_{n}_{method}",)
        ).fetchone()["relation"]
        if exists:
            raise ValueError("unfinished_fixture_exists_use_new_run_not_overwrite")
        with monitor(conn) as resource, conn.transaction():
            conn.execute(
                sql.SQL(
                    "CREATE TABLE {}(id bigint PRIMARY KEY,index_id text NOT NULL,"
                    "document_id text NOT NULL,filed_at date NOT NULL,embedding vector({}) NOT NULL)"
                ).format(table, sql.Literal(source.shape[1]))
            )
            rng = np.random.default_rng(config.seed)
            with conn.cursor().copy(
                sql.SQL("COPY {} FROM STDIN (FORMAT BINARY)").format(table)
            ) as cp:
                cp.write(COPY_HEADER)
                for start in range(0, n, 512):
                    batch = fixture_batch(source, start, min(512, n - start), rng, config.noise_std)
                    cp.write(binary_rows(batch, start))
                cp.write(struct.pack("!h", -1))
            conn.execute(
                sql.SQL("CREATE INDEX {} ON {}(index_id,document_id,filed_at)").format(
                    sql.Identifier(f"filter_{n}_{method}"), table
                )
            )
        conn.execute(sql.SQL("ANALYZE {}").format(table))
        check = conn.execute(
            sql.SQL("SELECT count(*) n,avg(vector_norm(embedding)) avg_norm FROM {}").format(table)
        ).fetchone()
        size = conn.execute(
            "SELECT pg_total_relation_size(%s) bytes", (f"{schema}.vectors_{n}_{method}",)
        ).fetchone()["bytes"]
    record = {
        "rows": n,
        "method": method,
        "source_matrix": manifest["source"]["source_vector_sha256"],
        "checks": check,
        "heap_toast_and_btree_bytes_before_ann": size,
        "load_resource": resource,
    }
    atomic_json(target, record)
    return record


def build(run, config, manifest, n, method):
    require_live_fixture(run)
    target = run / "builds" / f"{n}_{method}.json"
    if target.exists():
        return json.loads(target.read_text())
    load_fixture(run, config, manifest, n, method)
    schema = manifest["schema"]
    table = table_name(schema, n, method)
    name = f"ann_{n}_{method}"
    lists = max(10, n // 1000)
    options = (
        sql.SQL("WITH(m=16,ef_construction=64)")
        if method == "hnsw"
        else sql.SQL("WITH(lists={})").format(sql.Literal(lists))
    )
    with connect(config) as conn:
        notices = []
        conn.add_notice_handler(
            lambda d: notices.append({"message": d.message_primary, "detail": d.message_detail})
        )
        exists = conn.execute("SELECT to_regclass(%s) relation", (schema + "." + name,)).fetchone()[
            "relation"
        ]
        if exists:
            raise ValueError("unfinished_index_exists_use_new_run_not_overwrite")
        print("BUILD", n, method, "start", flush=True)
        with monitor(conn) as resource:
            conn.execute(
                sql.SQL("CREATE INDEX {} ON {} USING {}(embedding vector_cosine_ops) {}").format(
                    sql.Identifier(name), table, sql.SQL(method), options
                )
            )
        conn.execute(sql.SQL("ANALYZE {}").format(table))
        sizes = conn.execute(
            "SELECT pg_relation_size(%s) index_bytes,pg_total_relation_size(%s) total_bytes",
            (schema + "." + name, f"{schema}.vectors_{n}_{method}"),
        ).fetchone()
    result = {
        "method": method,
        "rows": n,
        "index": name,
        "lists": lists if method == "ivfflat" else None,
        "m": 16 if method == "hnsw" else None,
        "ef_construction": 64 if method == "hnsw" else None,
        "resource": resource,
        "sizes": sizes,
        "notices": notices,
    }
    atomic_json(target, result)
    print("BUILD", n, method, "done", round(resource["wall_seconds"], 2), "s", flush=True)
    return result


def query_statement(table, exact=False, explain=False):
    ordering = sql.SQL("(embedding <=> %s::vector)+0,id") if exact else sql.SQL("distance")
    statement = sql.SQL(
        "WITH nearest AS MATERIALIZED (SELECT id,embedding <=> %s::vector distance "
        "FROM {} WHERE index_id=%s AND document_id=ANY(%s) AND filed_at<=%s "
        "ORDER BY {} LIMIT %s) SELECT id,distance FROM nearest ORDER BY distance+0,id"
    ).format(table, ordering)
    return (sql.SQL("EXPLAIN(ANALYZE,BUFFERS,FORMAT JSON) ") + statement) if explain else statement


def execute(conn, table, vector, docs, k, exact=False, explain=False):
    encoded = json.dumps(vector)
    params = [encoded, "fixture", docs, AS_OF]
    if exact:
        params.append(encoded)
    params.append(k)
    start = time.perf_counter()
    result = conn.execute(query_statement(table, exact, explain), params).fetchall()
    return result, (time.perf_counter() - start) * 1000


def search_settings(conn, config, profile=None, lists=10):
    conn.execute("SELECT set_config('statement_timeout',%s,true)", (str(config.query_timeout_ms),))
    if profile is None:
        return
    conn.execute("SET LOCAL enable_seqscan=off")
    conn.execute("SET LOCAL enable_bitmapscan=off")
    conn.execute("SET LOCAL enable_sort=off")
    if profile.method == "hnsw":
        pairs = [
            ("hnsw.ef_search", profile.ef_search),
            ("hnsw.max_scan_tuples", profile.max_scan),
            ("hnsw.iterative_scan", "strict_order"),
        ]
    else:
        pairs = [
            ("ivfflat.probes", min(profile.probes, max(1, lists - 1))),
            ("ivfflat.max_probes", min(profile.max_probes, lists)),
            ("ivfflat.iterative_scan", "relaxed_order"),
        ]
    for key, value in pairs:
        conn.execute("SELECT set_config(%s,%s,true)", (key, str(value)))


def metrics(expected, found, k, tolerance=1e-7):
    n = len(expected)
    if n == 0:
        return {"strict_overlap": None, "boundary_equivalent": None, "underfill": False}
    expected_ids = {r["id"] for r in expected}
    threshold = max(r["distance"] for r in expected)
    return {
        "strict_overlap": len(expected_ids & {r["id"] for r in found}) / n,
        "boundary_equivalent": sum(r["distance"] <= threshold + tolerance for r in found) / n,
        "underfill": len(found) < min(k, n),
    }


def plans_contain(plan, index_name):
    if isinstance(plan, list):
        return any(plans_contain(p, index_name) for p in plan)
    if not isinstance(plan, dict):
        return False
    return plan.get("Index Name") == index_name or any(
        plans_contain(v, index_name) for v in plan.values() if isinstance(v, (dict, list))
    )


def exact_reference(run, config, manifest, n, queries):
    target = run / "exact" / f"{n}.json"
    if target.exists():
        return json.loads(target.read_text())
    table = table_name(manifest["schema"], n, "hnsw")
    results = {}
    samples = []
    plans = {}
    with connect(config) as conn, monitor(conn) as resource:
        for percent in config.selectivities:
            with conn.transaction():
                search_settings(conn, config)
                execute(
                    conn,
                    table,
                    queries[0]["vector"],
                    scope_documents(percent, 0),
                    config.k,
                    exact=True,
                )
            for qi, q in enumerate(queries):
                docs = scope_documents(percent, qi)
                expected = None
                for repeat in range(config.repeats):
                    with conn.transaction():
                        search_settings(conn, config)
                        found, ms = execute(conn, table, q["vector"], docs, config.k, exact=True)
                    if expected is not None and [r["id"] for r in expected] != [
                        r["id"] for r in found
                    ]:
                        raise ValueError("exact_results_changed")
                    expected = found
                    samples.append(
                        {
                            "query_id": q["id"],
                            "selectivity_percent": percent,
                            "repeat": repeat,
                            "latency_ms": ms,
                        }
                    )
                results[f"{percent}:{q['id']}"] = expected
            with conn.transaction():
                search_settings(conn, config)
                rows, _ = execute(
                    conn,
                    table,
                    queries[0]["vector"],
                    scope_documents(percent, 0),
                    config.k,
                    exact=True,
                    explain=True,
                )
                plan = rows[0]["QUERY PLAN"]
                plans[str(percent)] = plan
                if plans_contain(plan, f"ann_{n}_hnsw"):
                    raise ValueError("exact_reference_used_ann")
    result = {"neighbors": results, "samples": samples, "resource": resource, "plans": plans}
    atomic_json(target, result)
    return result


def benchmark_profile(
    run,
    config,
    manifest,
    n,
    profile,
    queries,
    exact,
    *,
    fixture_table=None,
    build_record=None,
    label=None,
):
    name = f"{label}_{profile.key()}" if label else profile.key()
    target = run / "measurements" / str(n) / f"{name}.json"
    if target.exists():
        return json.loads(target.read_text())
    build_info = build_record or build(run, config, manifest, n, profile.method)
    table = fixture_table or table_name(manifest["schema"], n, profile.method)
    samples = []
    plans = {}
    with connect(config) as conn, monitor(conn) as resource:
        for percent in config.selectivities:
            with conn.transaction():
                search_settings(conn, config, profile, build_info["lists"] or 10)
                execute(conn, table, queries[0]["vector"], scope_documents(percent, 0), config.k)
            order = np.random.default_rng(config.seed + percent).permutation(len(queries))
            for repeat in range(config.repeats):
                for qi in order:
                    qi = int(qi)
                    q = queries[qi]
                    docs = scope_documents(percent, qi)
                    try:
                        with conn.transaction():
                            search_settings(conn, config, profile, build_info["lists"] or 10)
                            found, ms = execute(conn, table, q["vector"], docs, config.k)
                        expected = exact["neighbors"][f"{percent}:{q['id']}"]
                        if len({r["id"] for r in found}) != len(found):
                            raise ValueError("duplicate_ann_id")
                        if any(f"scope_{r['id'] % 100:02}" not in docs for r in found):
                            raise ValueError("filter_leak")
                        samples.append(
                            {
                                "query_id": q["id"],
                                "selectivity_percent": percent,
                                "repeat": repeat,
                                "latency_ms": ms,
                                "returned": len(found),
                                "status": "ok",
                                **metrics(expected, found, config.k),
                            }
                        )
                    except Exception as exc:  # noqa: BLE001 — preserve safe typed measurement failure
                        samples.append(
                            {
                                "query_id": q["id"],
                                "selectivity_percent": percent,
                                "repeat": repeat,
                                "status": "error",
                                "type": type(exc).__name__,
                            }
                        )
            with conn.transaction():
                search_settings(conn, config, profile, build_info["lists"] or 10)
                rows, _ = execute(
                    conn,
                    table,
                    queries[0]["vector"],
                    scope_documents(percent, 0),
                    config.k,
                    explain=True,
                )
                plans[str(percent)] = rows[0]["QUERY PLAN"]
                if not plans_contain(plans[str(percent)], build_info["index"]):
                    raise ValueError("requested_ann_not_used")
    result = {
        "rows": n,
        "profile": profile.model_dump(),
        "actual_probes": min(profile.probes, max(1, build_info["lists"] - 1))
        if profile.method == "ivfflat"
        else None,
        "lists": build_info["lists"],
        "samples": samples,
        "plans": plans,
        "resource": resource,
    }
    atomic_json(target, result)
    print("MEASURE", n, profile.key(), "done", flush=True)
    return result


def summary(run):
    manifest = json.loads((run / "manifest.json").read_text())
    config = BenchConfig(**manifest["config"])
    output = []
    for n in config.sizes:
        reference = run / "exact" / f"{n}.json"
        if not reference.exists():
            continue
        exact = json.loads(reference.read_text())
        for percent in config.selectivities:
            values = [
                s["latency_ms"] for s in exact["samples"] if s["selectivity_percent"] == percent
            ]
            output.append(
                {
                    "rows": n,
                    "profile": "exact",
                    "selectivity_percent": percent,
                    "samples": len(values),
                    "recall": 1.0,
                    "underfill_rate": 0.0,
                    "p50_ms": float(np.percentile(values, 50)),
                    "p95_ms": float(np.percentile(values, 95)),
                    "mean_ms": mean(values),
                    "errors": 0,
                }
            )
        for path in sorted((run / "measurements" / str(n)).glob("*.json")):
            data = json.loads(path.read_text())
            for percent in config.selectivities:
                rows = [s for s in data["samples"] if s["selectivity_percent"] == percent]
                ok = [s for s in rows if s["status"] == "ok"]
                values = [s["latency_ms"] for s in ok]
                output.append(
                    {
                        "rows": n,
                        "profile": path.stem,
                        "selectivity_percent": percent,
                        "samples": len(rows),
                        "recall": mean(s["strict_overlap"] for s in ok) if ok else None,
                        "boundary_equivalent": mean(s["boundary_equivalent"] for s in ok)
                        if ok
                        else None,
                        "min_recall": min(s["strict_overlap"] for s in ok) if ok else None,
                        "underfill_rate": mean(s["underfill"] for s in ok) if ok else None,
                        "p50_ms": float(np.percentile(values, 50)) if ok else None,
                        "p95_ms": float(np.percentile(values, 95)) if ok else None,
                        "mean_ms": mean(values) if ok else None,
                        "errors": len(rows) - len(ok),
                    }
                )
    builds = [json.loads(p.read_text()) for p in sorted((run / "builds").glob("*.json"))]
    after = source_snapshot()
    result = {
        "metrics": output,
        "builds": builds,
        "source_unchanged": after == manifest["source_before"],
        "source_after": after,
        "limits": "synthetic clustered vectors, 24 fixed cached real queries, "
        "2 repeats (not 48 independent intents); single client SQL-only warm/uncontrolled OS-cache. "
        "RSS sampled backend resident memory includes shared mappings, not private or total PostgreSQL RAM. "
        "No financial evidence accuracy, concurrency or service RPS claim.",
    }
    if not result["source_unchanged"]:
        raise ValueError("serving_source_changed")
    atomic_json(run / "summary.json", result)
    lines = [
        "# ANN规模实验：合成扩容，非真实财报质量验收",
        "",
        result["limits"],
        "",
        "| rows | profile | filter % | neighbor recall@20 | p50 ms | p95 ms | underfill | errors |",
        "| --- | --- | --- | --- | --- | --- | --- | --- |",
    ]

    def fmt(value, pattern):
        return format(value, pattern) if value is not None else "-"

    for r in output:
        lines.append(
            f"| {r['rows']} | {r['profile']} | {r['selectivity_percent']} | {fmt(r['recall'], '.4f')} | {fmt(r['p50_ms'], '.2f')} | {fmt(r['p95_ms'], '.2f')} | {fmt(r['underfill_rate'], '.2%')} | {r['errors']} |"
        )
    (run / "results.md").write_text("\n".join(lines) + "\n")
    print("SUMMARY", str(run / "results.md"), flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["run", "summary"])
    parser.add_argument("--config", type=Path, default=ROOT / "configs/ann_scale.json")
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--sizes", default="", help="subset of configured sizes, safe stage resume")
    args = parser.parse_args()
    run = args.run.resolve()
    run.mkdir(parents=True, exist_ok=True)
    config = BenchConfig(**json.loads(args.config.read_text())).validate_limits()
    if args.command == "summary":
        summary(run)
        return
    manifest = prepare(run, config)
    queries = json.loads((run / "queries.json").read_text())
    if digest((run / "queries.json").read_bytes()) != manifest["query_sha256"]:
        raise ValueError("query_inputs_changed")
    selected = {int(s) for s in args.sizes.split(",") if s} or set(config.sizes)
    if selected - set(config.sizes):
        raise ValueError("size_not_in_manifest")
    for n in config.sizes:
        if n not in selected:
            continue
        build(run, config, manifest, n, "hnsw")
        exact = exact_reference(run, config, manifest, n, queries)
        for profile in config.profiles:
            benchmark_profile(run, config, manifest, n, profile, queries, exact)
        summary(run)
    print("DONE zero API calls; fixtures retained in", manifest["schema"], flush=True)


if __name__ == "__main__":
    main()
