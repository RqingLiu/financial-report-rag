# Active evaluation data

| Entry | Role | Command |
| --- | --- | --- |
| `golden_v2/` | Reviewed answers/qrels/numeric checks for 20 compound development questions | `python -m finrag.evaluation check-data --dataset compound` |
| `golden_v3/` | 81 canonical intent derivatives, with scoped answers/labels; pending review | `python -m finrag.evaluation check-data --dataset intents` / `build-intents` |
| `user_seeds_v2.jsonl`, `review_v2/review.md`, `review_v2/human_review.jsonl` | Inputs actually read/hash-checked by the compound release recipe | No separate daily command |
| `golden_v1.jsonl`, `freeze_v1.json`, `ragas_reference.jsonl` | Small earlier-release hash anchors checked by the compound release manifest | No live use and no separate v1 runner |

`retrieval_queries.jsonl` is the only dataset input for online runs. `golden.jsonl`, `rubrics.jsonl`, `numeric_checks.jsonl`, `reference_answers.md` and `evidence_catalog.jsonl` are offline labels/reference material. Parent `answer_specs.json`/`label_specs.json` and child `split_specs.json` feed intent construction. Version names describe annotation lineage, not chunking algorithms.

The two scripts `scripts/build_golden_v2.py` and `build_golden_v3.py` are retained because these datasets are still active; the CLI gives them purpose-based names. The reviewed compound recipe retains its original filename/hash. Do not edit released answers or replace their historical scores. The intent draft may be rebuilt and re-reviewed, but derivatives are not independent new samples.

Unused prompt templates, old annotation drafts, old research drivers and the full archive were deleted. There is no current dependency on those directories. Natural raw-query pairs and independent new-company holdout labels are still to be collected.
