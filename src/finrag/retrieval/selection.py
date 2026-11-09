"""One bounded pipeline for real queries and the optional HTTP API; no gold imports."""

import json

from finrag.agent.planner import PlanRejected
from finrag.core.config import ROOT
from finrag.retrieval.evidence import candidates_for_rerank, fetch_blocks, select_reranked
from finrag.retrieval.rerank import grade_candidates


def select_context(data, plan, ranked, store, catalog, config, llm, ce, trace):
    shortlist = ranked[: config.pipeline.context_candidate_limit]
    if len(shortlist) > 80 and config.reranker == "crossencoder":
        raise PlanRejected("crossencoder_limit80")
    blocks = fetch_blocks(shortlist, store)
    grades, priorities = {}, None
    with trace.stage(
        "rerank",
        {
            "method": config.reranker,
            "candidates": len(shortlist),
            "candidate_ids": [h.chunk.id for h in shortlist],
            "need_ids": [n.id for n in plan.needs],
        },
    ) as stage:
        if config.reranker == "llm":
            candidates = candidates_for_rerank(shortlist, blocks, catalog.by_id)
            logs = ROOT / "logs/serving_rerank" / data["query_id"]
            logs.mkdir(parents=True, exist_ok=True)
            grades, event = grade_candidates(
                data["inputs"],
                plan.model_dump(mode="json"),
                candidates,
                llm,
                ROOT / "data/cache/rerank",
                logs,
            )
        elif config.reranker == "crossencoder":
            query = json.dumps(
                {
                    "question": data["inputs"]["original_question"],
                    "reading_context": data["inputs"]["reading_context"],
                    "confirmed_context": data["inputs"]["confirmed_context"],
                    "as_of": data["inputs"]["as_of"],
                },
                ensure_ascii=False,
            )
            scores, event = ce.rank(query, [h.chunk.embedding_text for h in shortlist])
            priorities = {h.chunk.id: scores[i] for i, h in enumerate(shortlist)}
        else:
            priorities = {h.chunk.id: -i for i, h in enumerate(shortlist)}
            event = {"method": "coarse_order_only"}
        if priorities is not None:
            grades = {h.chunk.id: {"s": 1, "n": [], "l": []} for h in shortlist}
        stage["outputs"] = {
            "event": event,
            "scores": priorities if priorities is not None else grades,
        }
    with trace.stage(
        "context_build",
        {
            "evidence_cap": config.evidence_tokens,
            "prompt_cap": config.full_prompt_tokens,
            "candidate_ids": [h.chunk.id for h in shortlist],
        },
    ) as stage:
        selected, texts, evidence, metadata = select_reranked(
            shortlist,
            grades,
            blocks,
            store,
            catalog.by_id,
            config.pipeline,
            data,
            config.evidence_tokens,
            config.full_prompt_tokens,
            priority_scores=priorities,
            max_items=config.max_context_items,
        )
        stage["outputs"] = {**metadata, "evidence": evidence}
    return selected, texts, evidence, metadata
