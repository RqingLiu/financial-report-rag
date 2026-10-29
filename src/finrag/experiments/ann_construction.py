"""Follow-up construction controls for a pathological synthetic HNSW result.

Only add owned fixture tables/indexes. Never replace or rebuild a serving index.
"""

import argparse
import json
from pathlib import Path

from psycopg import sql

from ..files import atomic_json
from .ann_scale import (
    SCHEMA_RE,
    BenchConfig,
    Profile,
    benchmark_profile,
    connect,
    monitor,
    require_live_fixture,
    summary,
    table_name,
)


def construction(run, config, manifest, n, memory_mb, m):
    require_live_fixture(run)
    if (
        n != 100000
        or memory_mb != 512
        or m not in (16, 32)
        or not SCHEMA_RE.fullmatch(manifest["schema"])
    ):
        raise ValueError("construction_control_outside_bounded_design")
    label = f"hnsw_m{m}_mem{memory_mb}"
    target = run / "builds" / f"{n}_{label}.json"
    schema = manifest["schema"]
    table = sql.Identifier(schema, f"vectors_{n}_{label}")
    if target.exists():
        return table, json.loads(target.read_text()), label
    cfg = config.model_copy(update={"maintenance_mb": memory_mb})
    source = table_name(schema, n, "hnsw")
    table_reg = f"{schema}.vectors_{n}_{label}"
    index = f"ann_{n}_{label}"
    with connect(cfg) as conn:
        if conn.execute("SELECT to_regclass(%s) r", (table_reg,)).fetchone()["r"]:
            raise ValueError("partial_control_exists_use_new_control_label_not_overwrite")
        # Preserve vector bits and row insertion order; only build settings differ.
        with conn.transaction():
            conn.execute(
                sql.SQL("CREATE TABLE {}(LIKE {} INCLUDING DEFAULTS INCLUDING CONSTRAINTS)").format(
                    table, source
                )
            )
            conn.execute(
                sql.SQL("INSERT INTO {} SELECT * FROM {} ORDER BY id").format(table, source)
            )
            conn.execute(sql.SQL("ALTER TABLE {} ADD PRIMARY KEY(id)").format(table))
            conn.execute(
                sql.SQL("CREATE INDEX {} ON {}(index_id,document_id,filed_at)").format(
                    sql.Identifier(f"filter_{n}_{label}"), table
                )
            )
        notices = []
        conn.add_notice_handler(
            lambda d: notices.append({"message": d.message_primary, "detail": d.message_detail})
        )
        print("CONTROL BUILD", label, "start", flush=True)
        with monitor(conn) as resource:
            conn.execute(
                sql.SQL(
                    "CREATE INDEX {} ON {} USING hnsw(embedding vector_cosine_ops) "
                    "WITH(m={},ef_construction=64)"
                ).format(sql.Identifier(index), table, sql.Literal(m))
            )
        conn.execute(sql.SQL("ANALYZE {}").format(table))
        sizes = conn.execute(
            "SELECT pg_relation_size(%s) index_bytes,pg_total_relation_size(%s) total_bytes",
            (schema + "." + index, table_reg),
        ).fetchone()
    record = {
        "method": label,
        "rows": n,
        "index": index,
        "lists": None,
        "m": m,
        "ef_construction": 64,
        "maintenance_mb": memory_mb,
        "resource": resource,
        "sizes": sizes,
        "notices": notices,
        "source": "same vector bits copied from base fixture ORDER BY id; no re-embedding",
        "reason": "test memory-only control at m16; test link-density control m32 at same memory/ef_construction",
    }
    atomic_json(target, record)
    print("CONTROL BUILD", label, "done", round(resource["wall_seconds"], 2), "s", flush=True)
    return table, record, label


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--run", type=Path, required=True)
    p.add_argument("--m", default="16,32", help="subset of construction controls:16,32")
    p.add_argument("--efs", default="100,200", help="up to four query ef_search values:20..1000")
    args = p.parse_args()
    run = args.run.resolve()
    require_live_fixture(run)
    manifest = json.loads((run / "manifest.json").read_text())
    cfg = BenchConfig(**manifest["config"])
    queries = json.loads((run / "queries.json").read_text())
    exact = json.loads((run / "exact/100000.json").read_text())
    choices = sorted({int(value) for value in args.m.split(",")})
    efs = sorted({int(value) for value in args.efs.split(",")})
    if (
        set(choices) - {16, 32}
        or not choices
        or not 1 <= len(efs) <= 4
        or any(not 20 <= e <= 1000 for e in efs)
    ):
        raise ValueError("control_parameter_limit")
    for m in choices:
        table, record, label = construction(run, cfg, manifest, 100000, 512, m)
        for ef in efs:
            benchmark_profile(
                run,
                cfg,
                manifest,
                100000,
                Profile(method="hnsw", ef_search=ef, max_scan=20000),
                queries,
                exact,
                fixture_table=table,
                build_record=record,
                label=label,
            )
        summary(run)
    print("CONTROLS done; existing results preserved", flush=True)


if __name__ == "__main__":
    main()
