"""Bounded query-plan execution against existing indexes; no issuer regex or glossary."""

from collections import defaultdict
from time import perf_counter

from .chunk import config_id
from .context import EvidenceStore, build_context
from .models import Hit
from .planning import PipelineConfig, PlanRejected
from .ranking import interleave


def prepare_searches(plan, catalog, config):
    scopes = {s.ticker: s for s in plan.companies}
    jobs = []
    for task in plan.tasks:
        grouped = defaultdict(list)
        for ticker in task.tickers:
            for doc_id in catalog.documents(scopes[ticker], plan.as_of):
                f = catalog.by_id[doc_id]
                grouped[(ticker, f.fiscal_year)].append(f.id)
        if len(grouped) > config.max_groups_per_task:
            raise PlanRejected("scope_group_resource_limit")
        for (ticker, year), docs in sorted(grouped.items()):
            for query in task.dense_queries:
                jobs.append(
                    {
                        "task_id": task.id,
                        "group": [ticker, year],
                        "documents": docs,
                        "method": "dense",
                        "query": query,
                        "k": config.dense_k,
                        "variants": len(task.dense_queries),
                    }
                )
            if config.fts_weight > 0 or config.collect_fts_for_ablation:
                jobs.append(
                    {
                        "task_id": task.id,
                        "group": [ticker, year],
                        "documents": docs,
                        "method": "fts",
                        "query": " ".join(task.keywords),
                        "k": config.fts_k,
                        "variants": 1,
                    }
                )
    if len(jobs) > config.max_search_calls:
        raise PlanRejected("search_call_resource_limit")
    if not jobs:
        raise PlanRejected("no_available_scope")
    return jobs


def rank_records(records, config, mode="weighted_rrf"):
    by_group, hits = {}, {}
    for r in records:
        key = (r["task_id"], tuple(r["group"]))
        scores = by_group.setdefault(key, {})
        method = r["method"]
        if mode == "dense" and method != "dense" or mode == "fts" and method != "fts":
            continue
        weight = config.dense_weight if method == "dense" else config.fts_weight
        if mode in ("equal_rrf", "dense", "fts"):
            weight = 1
        weight /= r["variants"]
        if weight <= 0:
            continue
        for rank, raw in enumerate(r["hits"], 1):
            h = Hit(**raw)
            hits[h.chunk.id] = h
            scores[h.chunk.id] = scores.get(h.chunk.id, 0) + weight / (config.rrf_c + rank)
    by_task = defaultdict(list)
    for (task, group), values in by_group.items():
        order = sorted(values, key=lambda key: (-values[key], key))
        ranking = [
            hits[key].model_copy(update={"score": values[key], "method": mode}) for key in order
        ]
        by_task[task].append(ranking)
    task_lists, provenance = [], defaultdict(list)
    for task, groups in by_task.items():
        ranking = interleave(groups)
        task_lists.append(ranking)
        for rank, h in enumerate(ranking, 1):
            provenance[h.chunk.id].append({"task_id": task, "task_rank": rank})
    ranked = interleave(task_lists)
    return ranked, dict(provenance)


class PlannedRetriever:
    def __init__(self, repository, embedder, catalog, index_config, config=None):
        self.repository, self.embedder, self.catalog = repository, embedder, catalog
        if (
            index_config.embedding_model != embedder.model
            or index_config.dimension != embedder.dimension
        ):
            raise ValueError("query_embedding_does_not_match_index")
        self.index_id = config_id(index_config)
        if hasattr(repository, "indexed_documents"):
            rows = repository.indexed_documents(self.index_id)
        else:
            rows = repository.connection.execute(
                "SELECT document_id, count(*) n FROM finrag.chunks WHERE index_id=%s GROUP BY document_id",
                (self.index_id,),
            ).fetchall()
        self.indexed_documents = {r["document_id"] for r in rows if r["n"] > 0}
        if not self.indexed_documents:
            raise ValueError("requested_index_is_empty")
        config = config or PipelineConfig()
        self.store = EvidenceStore(
            repository, config.source_cache_blocks, config.source_cache_characters
        )

    def search(self, plan, config, trace):
        jobs = prepare_searches(plan, self.catalog, config)
        if hasattr(self.repository, "prepare_jobs"):
            jobs = self.repository.prepare_jobs(jobs, plan)
        if {d for j in jobs for d in j["documents"]} - self.indexed_documents:
            raise PlanRejected("requested_document_not_indexed")
        queries = list(dict.fromkeys(j["query"] for j in jobs if j["method"] == "dense"))
        with trace.stage(
            "embed_queries",
            {"queries": queries, "input_type": "query", "model": self.embedder.model},
        ) as s:
            before = len(self.embedder.events)
            vectors = dict(
                zip(queries, self.embedder.embed(queries, input_type="query"), strict=True)
            )
            s["outputs"] = {"usage_events": self.embedder.events[before:], "vectors_logged": False}
        records = []
        with trace.stage(
            "retrieve", {"jobs": len(jobs), "index_id": self.index_id, "as_of": str(plan.as_of)}
        ) as parent:
            for job in jobs:
                with trace.stage("retrieve." + job["method"], job) as s:
                    started = perf_counter()
                    found = self.repository.search(
                        self.index_id,
                        job["documents"],
                        str(plan.as_of),
                        job["k"],
                        vector=vectors[job["query"]] if job["method"] == "dense" else None,
                        query=job["query"] if job["method"] == "fts" else None,
                    )
                    record = {
                        **job,
                        "hits": [h.model_dump() for h in found],
                        "duration_seconds": perf_counter() - started,
                    }
                    records.append(record)
                    s["outputs"] = {"hits": record["hits"]}
            parent["outputs"] = {
                "completed_searches": len(records),
                "hit_count": sum(len(r["hits"]) for r in records),
                "unique_chunks": len({h["chunk"]["id"] for r in records for h in r["hits"]}),
            }
        return records

    def context(self, records, config, trace, mode="weighted_rrf", *, plan=None):
        with trace.stage(
            "fusion",
            {
                "mode": mode,
                "rrf_c": config.rrf_c,
                "dense_weight": config.dense_weight,
                "fts_weight": config.fts_weight,
            },
        ) as s:
            ranked, provenance = rank_records(records, config, mode)
            raw_count = len(ranked)
            ranked = ranked[: config.max_unique_candidates]
            s["outputs"] = {
                "raw_unique_candidates": raw_count,
                "retained_candidates": len(ranked),
                "capacity_truncated": raw_count > len(ranked),
                "ranked_hits": [h.model_dump() for h in ranked],
                "provenance": provenance,
            }
        with trace.stage(
            "context_build",
            {
                "strategy": config.context_strategy,
                "k": config.context_k,
                "token_budget": config.context_tokens,
                "expand_tables": config.expand_tables,
            },
        ) as s:
            selected, texts, metadata = build_context(
                ranked,
                provenance,
                self.store,
                self.catalog.filings,
                config,
                plan=plan,
                search_records=records,
            )
            s["outputs"] = {**metadata, "selected_hits": [h.model_dump() for h in selected]}
        return ranked, selected, texts, metadata
