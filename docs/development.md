# Development, tests and scope

## Code map

| Area | Key files |
| --- | --- |
| Filing discovery/cache | `src/finrag/acquire.py` |
| HTML/offsets, chunks | `parse.py`, `chunk.py`, `models.py` |
| Serving publication/query SQL | `serving/ingestion.py`, `serving/store.py`, `serving/lexical.py` |
| QueryPlan and scope guard | `planning.py`, `planning_scope.py`, `planned_retrieval.py` |
| Rerank/context/answer | `reranking.py`, `rerank_context.py`, `context.py`, `answering.py` |
| Providers/cost/trace | `embedding.py`, `generation.py`, `serving/providers.py`, `tracing.py` |
| Current entry/API | `serving/cli.py`, `serving/runtime.py`, `serving/api.py` |
| New issuer preparation | `generalization.py`, `configs/generalization_companies.json` |
| Experiments/gold | `experiments/`, historical `*_experiment.py`, `evaluation.py`, `dataset.py` |

The older `fr-rag query` returns evidence/prompts through rule-based retrieval. `python -m finrag.pipeline` is an earlier QueryPlan experiment. Use **`fr-rag-serve`** for the current full query→rerank→generation path. Historical modules are preserved for frozen comparisons, not parallel daily services.

## Validation

```bash
pytest -q
ruff check src tests --exclude src/finrag/vendor
python -m pip check
# Local PostgreSQL and source corpus must already exist:
FINRAG_INTEGRATION=1 pytest -q
python scripts/build_golden_v2.py --check
```

Tests marked `corpus` require the ignored downloaded/processed files. They are explicitly skipped in a clean checkout rather than replaced with fake evidence. Opt-in DB tests use disposable fixture namespaces or controlled temporary rows and do not call paid models. Do not point tests at an unrelated database.

The frozen golden builder is left unchanged for hash reproducibility; it has legacy script-style lint issues. Current CI lints `src/` and `tests/` excluding unchanged upstream vendor code. Known RAGAS ID-metric deprecation warnings do not represent quality scores.

## Spec-driven changes

`specs/` contains requirements, plan and completion tasks for each increment; `.specify/` contains the constitution/templates. These are engineering artifacts, not runtime agent skills. Update the relevant spec before changing scope or behavior, add outcome/boundary regressions, then sync architecture and validation. Shared Spec Kit skills under `.agents/skills/` are optional development tooling.

Preserve original gold/config/release markers. A new question variant of an already tuned intent is development data. A new unseen intent can be held out. Do not load references/answer labels in query planning or retrieval. Changes to source/chunk output need an explicit version/migration assessment; the current table bug fix was checked byte-for-byte against the original corpus.

## Publication and local artifacts

`.env`, raw/processed/cache files, local logs, complete traces and archives are ignored. The public repository includes source metadata, reviewed evaluation data, compact sanitized receipts and reproducible code. Large local experiment paths may require restoring their archived run before using historical replay commands; they are not required for the serving CLI.

Before committing:

```bash
git add .
python scripts/check_publication.py
```

The scanner reads the actual Git index, checks size, token/private-key patterns, password-bearing database URLs, private home paths and matches to local credential values without printing them. It is a practical guard, not proof of absence of every possible secret. Never commit credentials or paste them into issues/logs. Regenerate caches outside Git.

Python3.12/macOS is the current local validation environment; CI targets Linux3.12 unit contracts. The budget ledger uses POSIX file locks; Windows support is not claimed. Runtime and evaluation currently share a pinned dependency environment; splitting heavy evaluation dependencies into an optional extra remains a maintainability improvement.
