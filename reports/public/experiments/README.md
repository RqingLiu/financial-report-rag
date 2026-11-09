# Public experiment evidence

[Experiment narrative / 实验解读](../../../docs/experiments.md) · [Metric boundaries](../../../docs/evaluation.md)

These are compact allowlisted exports from completed local experiments, not a new benchmark run. Source paths are repository-relative **provenance identifiers**, not downloadable raw runs; full provider messages and large local traces are intentionally excluded. [manifest.json](manifest.json) records source SHA256. Public files include numeric summaries and per-question evidence counts, without credentials, provider response IDs or machine paths.

| Artifact | Contents |
| --- | --- |
| [v1_dev.json](v1_dev.json) |28 historical development retrieval configurations; separate v1 task mix |
| [context.json](context.json) |4 budget-selection strategies,80 per-question rows |
| [funnel.json](funnel.json) | Candidate/Top80/context loss attribution and pool sizes |
| [rerank.json](rerank.json) |6 rerank/context strategies,120 per-question rows |
| [coarse.json](coarse.json) |8 Top80 coarse policies,160 per-question rows |
| [focused.json](focused.json) | Wide/focused/mixed queries,60 per-question rows |
| [serving.json](serving.json) |3 retrieval/planning arms ×2 rerankers,120 per-question rows |
| [ann_real.json](ann_real.json) |59 real filtered query/index checks on2,759 chunks |
| [ann_synthetic.json](ann_synthetic.json) |99 size/filter/search profiles plus build resource summaries; synthetic SQL-only |
| [recorded_demo.json](recorded_demo.json) | Saved generated answer/evidence previews and failed planner example; not ground truth |

`python scripts/verify_public_evidence.py` recomputes27 v2 aggregate arms from exported per-question rows, checks source-citation IDs and first-party documentation links. It needs only Python, not DB/provider credentials. Original v1 frozen test results stay in [test_release.json](../../test_release.json).

`python scripts/verify_public_evidence.py` recomputes the exported arithmetic without raw traces, DB credentials or models. Original large runs, their archive and retired drivers were removed during repository cleanup. Source hashes identify historical inputs; they do not make missing raw runs replayable. These are development evidence-recall results, not independently held-out answer-quality scores.
