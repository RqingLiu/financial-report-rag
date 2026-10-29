import json
from statistics import mean
from time import perf_counter

from finrag.config import ROOT
from finrag.files import atomic_json, digest
from finrag.planned_retrieval import prepare_searches
from finrag.planning import Plan
from finrag.serving.runtime import load_config, resources

base = ROOT / "reports/planner/20261027T034153Z_198f65/traces"
config = load_config().model_copy(update={"vector_search": "exact"})
rows = []
with resources(config, models=False) as (store, *_):
    cat = store.catalog()
    for p in sorted(base.glob("U*.json")):
        old = json.loads(p.read_text())
        jobs = prepare_searches(Plan(**old["plan"]), cat, config.pipeline)
        # Up to three real query/FY scopes per original question, cached query-role embeddings.
        for job in jobs[:: max(1, len(jobs) // 3)][:3]:
            q = job["query"]
            key = digest(
                json.dumps(
                    [store.index_config.embedding_model, store.index_config.dimension, "query", q]
                )
            )
            path = ROOT / "data/cache/embeddings" / f"{key}.json"
            vector = json.loads(path.read_text())
            store.config = config
            t = perf_counter()
            exact = store.search(
                store.index_id, job["documents"], old["plan"]["as_of"], 20, vector=vector
            )
            exacttime = perf_counter() - t
            store.config = config.model_copy(update={"vector_search": "hnsw"})
            t = perf_counter()
            ann = store.search(
                store.index_id, job["documents"], old["plan"]["as_of"], 20, vector=vector
            )
            anntime = perf_counter() - t
            explanation = store.search(
                store.index_id,
                job["documents"],
                old["plan"]["as_of"],
                20,
                vector=vector,
                explain=True,
            )
            a = {h.chunk.id for h in ann}
            e = {h.chunk.id for h in exact}
            rows.append(
                {
                    "question": p.stem,
                    "group": job["group"],
                    "query": q,
                    "overlap_at20": len(a & e) / len(e) if e else 1,
                    "exact_n": len(exact),
                    "ann_n": len(ann),
                    "exact_seconds": exacttime,
                    "ann_seconds": anntime,
                    "actual_hnsw_index": "chunks_hnsw" in str(explanation),
                    "explain": explanation,
                }
            )
    frozen = store.connection.execute("SELECT count(*) n FROM finrag.chunks").fetchone()
    equality = store.connection.execute(
        "SELECT count(*) n FROM finrag_live.chunks l JOIN finrag.chunks f ON l.id=f.id "
        "WHERE l.payload=f.payload AND l.embedding=f.embedding"
    ).fetchone()
result = {
    "n": len(rows),
    "mean_overlap_at20": mean(r["overlap_at20"] for r in rows),
    "ann_index_used": sum(r["actual_hnsw_index"] for r in rows),
    "exact_mean_ms": 1000 * mean(r["exact_seconds"] for r in rows),
    "ann_mean_ms": 1000 * mean(r["ann_seconds"] for r in rows),
    "frozen_chunks": frozen,
    "identical_copied_chunks": equality,
    "scope": "small 2759-chunk corpus; filtered real cached queries, no API; warm small-corpus timings do not establish scale benefit",
    "rows": rows,
}
atomic_json(ROOT / "reports/serving/ann_benchmark.json", result)
print(json.dumps({k: v for k, v in result.items() if k != "rows"}, indent=2))
