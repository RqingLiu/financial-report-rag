# Financial Report RAG

An evidence-grounded SEC annual-report research workflow with source provenance, bounded query planning, PostgreSQL retrieval, reranking and cited answers.

**Status:** working research/portfolio prototype. Current serving covers **5 companies, 16 filings and 4,961 chunks**. The complex20-question evaluation is a development set; answer-level numeric/semantic accuracy and production load are not yet accepted.

## What it does

- Parses SEC10-K HTML into traceable paragraphs/tables and structure-aware chunks.
- Publishes one immutable document atomically with vectors, metadata and BM25 statistics.
- Converts a user question into a bounded, validated company/FY/need/query plan.
- Retrieves with pgvector, reranks a coarse Top80 and builds a source-preserving context under explicit budgets.
- Generates need-aligned cited answers, partial answers and missing-evidence explanations.
- Records local traces, provider usage, billing reservations and reproducible evaluation artifacts.
- Provides a local query workbench with live stage events, searchable candidate rankings and evidence-linked answers.

Current default: **Voyage4-lite / 1024-dimensional embeddings → HNSW dense multi-query → RRF/interleave → LLM rerank → DeepSeek generation**. BM25 replacement, evidence-objective regroup and a dedicated Voyage CrossEncoder are optional comparison profiles. No LangGraph or autonomous multi-agent loop is required by this implementation.

## Read the project

| Document | Contents |
| --- | --- |
| [Architecture](docs/architecture.md) | Current flowchart, parameters, components and correctness boundaries |
| [Data and ingestion](docs/data-and-ingestion.md) | Corpus, chunking, source manifests, setup and new filing publication |
| [Evaluation](docs/evaluation.md) | Golden dataset, stage metrics, controlled results and limitations |
| [Development](docs/development.md) | Code map, tests, Spec Kit and publication hygiene |
| [History](docs/history.md) | Incremental decisions, failures and cleanup |
| [Query / trace UI](docs/trace-explorer.md) | Browser workflow, live events, history, API and privacy boundaries |
| [Current spec](specs/006-trace-explorer/spec.md) | Query and trace explorer requirements and acceptance |

## Quick start

Prerequisites: Python3.12 and PostgreSQL with pgvector0.8+ available. Create a local database named `financial_report_rag`; the CLI initializes project schemas. The checked-in dependency lock reflects the validated environment.

```bash
git clone https://github.com/RqingLiu/financial-report-rag.git
cd financial-report-rag
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
cp .env.example .env
```

In a fresh checkout, fill `.env` locally with `VOYAGE_API_KEY`, `DEEPSEEK_API_KEY`, the database URL and a SEC User-Agent with a real contact. Keys, connection secrets and caches are ignored. API subscriptions/billing are separate; uncached embedding and generation may incur charges. The shared ledger has a conservative cumulative stop configured in `configs/serving.json`.

Build the source corpus and selected index using [the documented ingestion commands](docs/data-and-ingestion.md). Then:

```bash
fr-rag-serve query "Compare NVIDIA and AMD FY2025 data-center revenue growth and explain the disclosed drivers" --as-of 2026-10-28
fr-rag-serve serve --port 8000
```

Open **http://127.0.0.1:8000/** for the query/trace interface: Planner → embedding → scoped searches → fusion → rerank → context → cited answer. Inspect each search and candidate decision, or open a historical run without API calls. New queries (including retrieval-only planning/reranking) can incur charges. See [UI details](docs/trace-explorer.md).

The localhost API also exposes `/query`, `/query/stream`, `/traces`, `/health` and `/docs`. `as_of` is required. The existing `fr-rag query` is a historical evidence-only CLI; use **`fr-rag-serve`** for current reranking and generation.

## Corpus and evaluation

| Company | Report FYs | Use |
| --- | --- | --- |
| NVIDIA / Micron | 2024–2026 | Original development corpus |
| AMD | 2023–2025 + FY2025 amendment | Original development corpus |
| Alphabet / Amazon | 2023–2025 | New generalization corpus; questions pending |

Source metadata and SEC links: [original](data/sources.jsonl), [new companies](data/generalization/sources.jsonl). Raw HTML, embeddings, full traces and local archives are not committed. Download/prepare the data before corpus-dependent validation.

The reviewed development dataset contains **20 questions /225 required evidence groups /123 numeric checks**. A controlled same-budget BM25 replacement arm reached **71.53% final-context evidence recall** versus67.66% for its dense control. This is a saved-plan development comparison, **not answer accuracy or a production acceptance result**; it did not automatically change serving defaults. See [evaluation details](docs/evaluation.md).

## Verify

```bash
pytest -q
ruff check src tests --exclude src/finrag/vendor
python scripts/check_publication.py
# With the local source corpus and PostgreSQL prepared:
FINRAG_INTEGRATION=1 pytest -q
python scripts/build_golden_v2.py --check
```

Clean-checkout CI runs credential-free unit contracts. Local corpus and DB tests are explicitly separated; provider mocks verify behavior, not retrieval quality. Public receipts are in [reports/public](reports/public/README.md).

## Boundaries and next steps

SEC HTML text/tables are supported; general PDF/OCR and image understanding are not. The system validates source offsets, company/report scope and citation IDs, but it does not yet automatically verify financial arithmetic or claim-level citation entailment. Real-time market data, a financial facts/calculator layer, forecasting, valuation, independent holdout quality and representative p95/RPS testing remain future work.

Developed as an individual project with AI-assisted implementation/review. [Contribution guidance](CONTRIBUTING.md) · [Data and third-party notices](NOTICE.md).
