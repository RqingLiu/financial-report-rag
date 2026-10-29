"""Source-span recall. Labels stay outside retrieval; all mandatory groups are scored."""

import json
import time
from collections import defaultdict
from datetime import UTC, datetime
from statistics import mean, median

from ragas.dataset_schema import SingleTurnSample
from ragas.metrics import IDBasedContextRecall

from .chunk import token_count
from .dataset import load_questions
from .files import atomic_json, digest, write_jsonl
from .models import RetrievalConfig


def covers(evidence, hits):
    intervals = sorted(
        (max(s["start"], evidence.start), min(s["end"], evidence.end))
        for hit in hits
        if hit.chunk.document_id == evidence.document_id
        for s in [*hit.chunk.spans, *hit.expanded_spans]
        if s["block_id"] == evidence.block_id
        and s["start"] < evidence.end
        and s["end"] > evidence.start
    )
    cursor = evidence.start
    for start, end in intervals:
        if start > cursor:
            return False
        cursor = max(cursor, end)
    return cursor >= evidence.end


def score(question, hits):
    if not question.evidence_groups:
        raise ValueError("Boundary questions have no reference evidence; do not score as recall=1")
    found = [
        i for i, group in enumerate(question.evidence_groups) if any(covers(e, hits) for e in group)
    ]
    refs = [f"{question.id}:g{i}" for i in range(len(question.evidence_groups))]
    retrieved = [f"{question.id}:g{i}" for i in found]
    sample = SingleTurnSample(
        user_input=question.question, reference_context_ids=refs, retrieved_context_ids=retrieved
    )
    value = IDBasedContextRecall().single_turn_score(sample)
    return {
        "recall": value,
        "groups_found": len(found),
        "groups_required": len(refs),
        "missing_groups": [i for i in range(len(refs)) if i not in found],
        "complete": len(found) == len(refs),
    }


def evaluate(root, retriever, config, split):
    questions = [q for q in load_questions(root, split) if q.outcome == "answer"]
    rows = []
    for q in questions:
        started = time.perf_counter()
        hits, meta = retriever.retrieve(
            q.question, config, k=20, question_en=q.question_en, as_of=q.as_of
        )
        row = {
            "id": q.id,
            "category": q.category,
            "question": q.question,
            "latency_seconds": time.perf_counter() - started,
            "meta": meta,
            "hit_ids": [h.chunk.id for h in hits],
            "hit_documents": [h.chunk.document_id for h in hits],
            "context_proxy_tokens": sum(token_count(retriever.context_text(h)) for h in hits),
            "at": {str(k): score(q, hits[:k]) for k in [5, 10, 20]},
        }
        rows.append(row)
    result = {
        "config": config.model_dump(),
        "split": split,
        "answer_questions": len(rows),
        "evaluated_at": datetime.now(UTC).isoformat(),
        "metric": "RAGAS IDBasedContextRecall; IDs assigned only after exact source-span coverage",
        "at": {
            str(k): {
                "macro_recall": mean(r["at"][str(k)]["recall"] for r in rows),
                "micro_recall": sum(r["at"][str(k)]["groups_found"] for r in rows)
                / sum(r["at"][str(k)]["groups_required"] for r in rows),
                "complete_question_rate": mean(r["at"][str(k)]["complete"] for r in rows),
            }
            for k in [5, 10, 20]
        },
        "median_latency_seconds": median(r["latency_seconds"] for r in rows),
        "mean_context_proxy_tokens": mean(r["context_proxy_tokens"] for r in rows),
    }
    cats = defaultdict(list)
    for row in rows:
        cats[row["category"]].append(row)
    result["by_category_at10"] = {
        c: {"n": len(rs), "macro_recall": mean(r["at"]["10"]["recall"] for r in rs)}
        for c, rs in cats.items()
    }
    run_id = f"{split}_{config.name}"
    write_jsonl(root / f"reports/{run_id}.questions.jsonl", rows)
    atomic_json(root / f"reports/{run_id}.json", result)
    retriever.repository.save_run(run_id, "retrieval_eval", config.model_dump(), result)
    print(
        f"{run_id}: R@5={result['at']['5']['macro_recall']:.3f} "
        f"R@10={result['at']['10']['macro_recall']:.3f} "
        f"R@20={result['at']['20']['macro_recall']:.3f}",
        flush=True,
    )
    return result


def run_dev(root, retriever):
    if (root / "reports/test_release.json").exists():
        raise ValueError("Selection is frozen after test release; create a new independent holdout")
    configs_path = root / "configs/experiments.json"
    results = [
        evaluate(root, retriever, RetrievalConfig(**c), "dev")
        for c in json.loads(configs_path.read_text())
    ]
    # Only dev results are available at selection. English manual rewrites are a separate track.
    eligible = [r for r in results if r["config"]["query_language"] == "original"]
    best = max(
        eligible,
        key=lambda r: (
            r["at"]["10"]["macro_recall"],
            r["at"]["5"]["macro_recall"],
            -r["mean_context_proxy_tokens"],
        ),
    )
    selection = {
        "config": best["config"],
        "selected_on": "dev macro recall@10, then recall@5, then context cost",
        "selected_at": datetime.now(UTC).isoformat(),
        "dev_recall_at10": best["at"]["10"]["macro_recall"],
        "dataset_sha256": json.loads((root / "data/evaluation/freeze_v1.json").read_text())[
            "sha256"
        ],
        "grid_sha256": digest(configs_path.read_bytes()),
        "test_read_for_selection": False,
    }
    selection["retrieval_code_sha256"] = retrieval_code_hash(root)
    atomic_json(root / "configs/best.json", selection)
    atomic_json(root / "reports/dev_comparison.json", results)
    return selection


def run_test(root, retriever):
    marker = root / "reports/test_release.json"
    if marker.exists():
        raise ValueError(
            "Test already released. Do not reselect on test; report it or create a new holdout."
        )
    selection = json.loads((root / "configs/best.json").read_text())
    freeze = json.loads((root / "data/evaluation/freeze_v1.json").read_text())
    if selection["dataset_sha256"] != freeze["sha256"]:
        raise ValueError("Selected config and frozen dataset differ")
    if selection["retrieval_code_sha256"] != retrieval_code_hash(root):
        raise ValueError("Retrieval code changed after dev selection; reselect on dev first")
    result = evaluate(root, retriever, RetrievalConfig(**selection["config"]), "test")
    from .query import query_policy

    boundary = []
    for q in load_questions(root, "test"):
        if q.outcome != "answer":
            prediction = query_policy(q.question, retriever.filings, q.as_of)
            boundary.append(
                {
                    "id": q.id,
                    "expected": q.outcome,
                    "predicted": prediction,
                    "correct": prediction["outcome"] == q.outcome,
                }
            )
    atomic_json(
        root / "reports/test_boundary.json",
        {
            "rows": boundary,
            "accuracy": mean(r["correct"] for r in boundary),
            "limitation": "Small rule-based input-routing test; not generated-answer safety certification",
        },
    )
    atomic_json(
        marker,
        {
            "selection": selection,
            "result": result,
            "target": "macro source-evidence recall@10 > 0.85",
            "target_met": result["at"]["10"]["macro_recall"] > 0.85,
        },
    )
    return result


def retrieval_code_hash(root):
    paths = [
        "retrieval.py",
        "chunk.py",
        "query.py",
        "models.py",
        "repository.py",
        "tree.py",
        "embedding.py",
    ]
    return digest("".join((root / "src/finrag" / p).read_text() for p in paths))
