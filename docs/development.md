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
| Browser / safe trace and code projection | `serving/static/`, `serving/explorer.py`, `serving/code_view.py` ([usage](trace-explorer.md)) |
| New issuer preparation | `generalization.py`, `configs/generalization_companies.json` |
| Experiments/gold | `experiments/`, historical `*_experiment.py`, `evaluation.py`, `dataset.py` |

The older `fr-rag query` returns evidence/prompts through rule-based retrieval. `python -m finrag.pipeline` is an earlier QueryPlan experiment. Use **`fr-rag-serve`** for the current full query→rerank→generation path. Historical modules are preserved for frozen comparisons, not parallel daily services.

## Follow the current query in code

Paths below are relative to this repository, `financial-report-rag/`. Use Cmd+P in the editor to find a path. A workflow step is not a separate file: shared adapters serve multiple stages, and `serving/runtime.py:execute` calls the implementations. The browser's **Code map** provides clickable functions and dynamically resolved current line numbers from `serving/code_view.py`.

| Workflow | Repository implementation | Responsibility |
| --- | --- | --- |
| HTTP / orchestration | `src/finrag/serving/api.py:create_app` → `src/finrag/serving/runtime.py:query` → `execute` | Receive request, create resources, sequence stages, persist trace |
| Published filings | `src/finrag/serving/store.py:LiveStore.catalog` → `src/finrag/planning.py:Catalog.metadata` | Join published DB documents; apply disclosure cutoff to planner metadata |
| Planner | `src/finrag/planning.py:plan_request`, `validate_plan`; `src/finrag/planning_scope.py` | Needs/tasks/query generation; company/FY/constraint validation |
| Query embeddings | `src/finrag/planned_retrieval.py:PlannedRetriever.search` → `src/finrag/serving/providers.py:DocumentEmbedder._request` | Query batching/cache and Voyage adapter |
| Retrieval | `src/finrag/planned_retrieval.py:prepare_searches`, `PlannedRetriever.search` → `src/finrag/serving/store.py:LiveStore.search` | Scope-specific jobs and actual pgvector/lexical SQL |
| Fusion | `src/finrag/planned_retrieval.py:rank_records` | RRF, source deduplication and task/group interleaving |
| Rerank | `src/finrag/serving/runtime.py:select_context` → `src/finrag/rerank_context.py:candidates_for_rerank` → `src/finrag/reranking.py:grade_candidates` | Top80 selection, source-line payload, batched LLM grades/cache/validation |
| Context | `src/finrag/rerank_context.py:select_reranked` | Source overlap, table expansion, evidence/prompt budgets |
| Answer | `src/finrag/answering.py:answer_messages`, `generate_answer` | Need-aligned generation and citation/shape validation |
| Shared model transport | `src/finrag/generation.py:DeepSeek.generate` | Real DeepSeek API calls, usage and shared budget; used by planner/rerank/answer |

The default reranker is **LLM reranking with DeepSeek Flash**, not mocked scores and not the embedding API. Each batch contains question/needs and candidate source lines; cached batches do not make new requests. `src/finrag/serving/providers.py:CrossEncoder.rank` supports the optional dedicated Voyage reranker but is not enabled by `configs/serving.json`.

**Published filings** means the database catalog, not a source-code directory. Original HTML exists locally under ignored `data/raw/`; tracked manifests are `data/sources.jsonl` and `data/generalization/sources.jsonl`. `src/finrag/serving/ingestion.py:ingest_html` connects HTML → `parse.py` → `chunk.py` → embeddings → `LiveStore.publish`. Online queries read published DB metadata/chunks instead of reparsing local HTML for each request.

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

## GitHub workflow

This project has its own repository, independent of the parent learning directory. A repository holds the project's files and shared commit history; branches point to different lines of development inside that same repository. A separate repository per project is a common choice, not a Git requirement (a monorepo can contain several projects).

`main` is the default delivered baseline. New increments use `codex/<feature>` branches, versioned specs, a pull request against main and CI before merging. The original `codex/correctness-release` branch is retained as release history; main was established at the same delivered commit, without rewriting history. Local checking out a branch changes the files in this checkout; a push publishes commits, and a PR proposes their merge—it does not itself merge them.

```bash
git switch main
git pull --ff-only
git switch -c codex/your-feature
# edit, verify, review staged contents and commit
git push -u origin codex/your-feature
gh pr create --base main
```

Avoid committing on main for routine feature work. Merge after reviewing the diff and CI; use ordinary commits or a revert to preserve understandable history. Public GitHub source does not expose the ignored database, local credentials or full traces.

Visibility belongs to the **repository**, not an individual branch. Every pushed branch in this public repository is publicly readable; branch protection does not hide it. Unpushed local changes remain local. Private development requires an independent private repository or local-only work. The completed Trace Studio increment (007) is included in the authorized bilingual-guide/main delivery (008).

## Publication and local artifacts

`.env`, raw/processed/cache files, local logs, complete traces and archives are ignored. The public repository includes source metadata, reviewed evaluation data, compact sanitized receipts and reproducible code. Large local experiment paths may require restoring their archived run before using historical replay commands; they are not required for the serving CLI.

Before committing:

```bash
git add .
python scripts/check_publication.py
```

The scanner reads the actual Git index, checks size, token/private-key patterns, password-bearing database URLs, private home paths and matches to local credential values without printing them. It is a practical guard, not proof of absence of every possible secret. Never commit credentials or paste them into issues/logs. Regenerate caches outside Git.

Python3.12/macOS is the current local validation environment; CI targets Linux3.12 unit contracts. The budget ledger uses POSIX file locks; Windows support is not claimed. Runtime and evaluation currently share a pinned dependency environment; splitting heavy evaluation dependencies into an optional extra remains a maintainability improvement.
