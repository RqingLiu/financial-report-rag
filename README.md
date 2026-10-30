# Financial Report RAG

[English](README.md) · [简体中文](README.zh-CN.md) · [Project Deep Dive / 项目深挖](docs/project-deep-dive.md) · [Experiments](docs/experiments.md)

An evidence-grounded research workflow for SEC annual reports: ask a multi-company, multi-year question, inspect how evidence was retrieved, and trace a cited answer back to the filing.

**Current scope:** a working local research prototype with **5 companies, 16 filings and 4,961 serving chunks**. It handles SEC HTML text/tables, bounded query planning, pgvector retrieval, reranking and cited generation. Financial facts/calculators, forecasting, valuation and an autonomous Agent loop remain future work. Retrieval evidence coverage is measured; independent answer accuracy and production load are not yet accepted.

![Interactive trace studio: workflow nodes, code references and observed results](docs/assets/trace-studio.jpg)

The screenshot shows a saved run, not a new live benchmark. The local UI lets you inspect each stage's input/output, actual model/SQL child calls, candidates, evidence, citations and related repository functions. See the [recorded success and failure examples](docs/examples.md) without configuring an API.

## Problem and approach

Annual-report comparisons require evidence from several documents, financial tables and footnotes. A fluent summary can omit a company, use a different fiscal period, or cite text that does not support a number. This project makes that data path inspectable and measures where evidence is lost.

RAG bounds the evidence supplied to generation and preserves source/date filters. Full-document context remains a useful baseline for a small number of reports; **this project has not established that RAG universally beats long-context input**. The current workflow is bounded Python, not a claim of a fully autonomous financial analyst.

## End-to-end architecture

```mermaid
flowchart TB
  SEC["SEC HTML + filing metadata"] --> Parse["lxml: paragraphs / tables / DOM and offsets"]
  Parse --> Chunk["Structure-aware512 / overlap64 + table context"]
  Chunk --> DocEmb["Voyage document embeddings:1024 dimensions"]
  DocEmb --> PG[("PostgreSQL: provenance + pgvector + BM25 postings")]
  Q["Question + required as_of + optional confirmed scope"] --> Plan["DeepSeek: bounded needs/tasks/queries + validation"]
  PG --> Catalog["Published filing catalog"] --> Plan
  Plan --> Route{"retrieve / clarify / insufficient"}
  Route -->|retrieve| Emb["Voyage query embeddings"]
  Emb --> Search["HNSW dense:Top20 per company/report/query"]
  PG --> Search
  Search --> Fuse["RRF + task/group interleave:retain≤512"]
  Fuse --> Rank["Top80 → DeepSeek LLM reranking"]
  Rank --> Ctx["Source-preserving context:≤30 items /8K evidence /24K input proxy"]
  Ctx --> Answer["DeepSeek cited answer + structure/citation-ID checks"]
  Route -->|other| Result["Answer / clarification / missing evidence"]
  Answer --> Result
  Result --> Trace["Local trace + usage ledger + interactive UI"]
```

**Current default:** HNSW dense multi-query → RRF/interleave → **LLM reranking** → cited generation. BM25 replacement, evidence-objective task regrouping and Voyage `rerank-3-lite` are optional experiment profiles. A good experimental score does not automatically change the default. No LangGraph/DeepAgents runtime is installed in this path.

[`serving/runtime.py:execute`](src/finrag/serving/runtime.py) orchestrates the query; algorithms and SQL live in separate modules. Ingestion uses a separate trusted CLI. [Exact parameters, storage and failure boundaries](docs/architecture.md) · [Workflow-to-code map](docs/development.md#follow-the-current-query-in-code).

## Results, with conditions

The main development set has **20 reviewed complex questions, 225 required evidence groups and 123 numeric checks**. Gold is loaded only for offline scoring, not query planning or retrieval. The older 60-question v1 split is a separate historical experiment.

| Controlled20-query development arm | Candidate evidence recall | Top80 recall | Final-context recall | All groups recovered |
| --- | ---: | ---: | ---: | ---: |
| Dense + LLM rerank |94.47%|80.95%|67.66%|4/20|
| Dense + BM25 replacement + LLM |94.77%|83.87%|71.53%|5/20|
| Evidence-objective regroup + LLM |95.62%|79.19%|67.62%|5/20|
| Dense + dedicated CrossEncoder |94.47%|80.95%|59.20%|4/20|

These are **macro source-span evidence-group recalls, not answer accuracy**. Arms use the same 342 SQL jobs, Top20/job, Top80 reranking and matched per-question context budgets; comparison retrieval is exact, reuses saved plans and mixes cached/new LLM judgments. It is not a cold end-to-end HNSW production benchmark. The BM25 gain is **3.87 percentage points** in this comparison; the service still defaults to dense+LLM.

The useful finding is the **candidate → shortlist → context bottleneck**, not one headline score. Other experiments cover five chunk configurations/28 v1 retrieval arms, context budgets, Top80 versus full-pool LLM reranking, focused queries and synthetic ANN scaling. [Conditions, negative results and reproducibility](docs/experiments.md) · [Machine-readable aggregates and per-question results](reports/public/experiments/README.md).

## Why these choices

| Decision | Reason and tradeoff |
| --- | --- |
| SEC HTML first | Preserves table cells and source locators without a PDF/OCR service; generic PDFs and image understanding are outside current support. |
| PostgreSQL + pgvector | Keeps metadata, provenance, vectors and lexical statistics together; FAISS is useful for an in-memory vector baseline but does not supply this whole storage contract. PG still needs index/filter and load validation. |
| Structure-aware chunks + table context | Selected from v1 development controls; avoids separating tables from titles/units. Large indivisible rows can exceed the target; v1 selection does not prove v2 optimality. |
| LLM planner/reranker | Produces explicit needs/scopes and source-line relevance judgments. Adds cost/latency; schema validity is not semantic correctness. |
| Bounded Python workflow | Explicit call/budget/error boundaries with a single local service. Introduce a stateful Agent framework only when iterative tool use actually requires one. |

[Alternatives, failure investigations and the next validation priorities](docs/project-deep-dive.md).

## Run locally

Prerequisites: Python3.12 and PostgreSQL with pgvector0.8+. No Node/frontend build is needed.

```bash
git clone https://github.com/RqingLiu/financial-report-rag.git
cd financial-report-rag
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.lock
cp .env.example .env
```

Set `DATABASE_URL`, `VOYAGE_API_KEY`, `DEEPSEEK_API_KEY` and a SEC User-Agent locally. Create `financial_report_rag`, then follow [corpus/index setup](docs/data-and-ingestion.md). A fresh clone contains source manifests and evaluation labels, **not** a ready-populated database, provider credentials, raw HTML or paid caches. Uncached embedding/planning/reranking/generation incurs provider charges; saved-history reads do not.

```bash
fr-rag-serve serve --port 8000
# Open http://127.0.0.1:8000/
fr-rag-serve query "Compare Google FY2024 and Amazon FY2025 cloud revenue disclosures" --as-of 2026-10-28
```

The same loopback FastAPI service provides query/SSE, history, a read-only published-report catalog, an allowlisted code map and `/docs`. There is no authenticated public deployment. [UI, APIs and privacy](docs/trace-explorer.md).

## Corpus, validation and limitations

- NVIDIA/Micron FY2024–2026; AMD FY2023–2025 plus an amendment; Alphabet/Amazon FY2023–2025. Report FY, fact FY and filing date are distinct. [Original manifest](data/sources.jsonl) · [Expansion manifest](data/generalization/sources.jsonl).
- Reviewed20-query results are development evidence. New-company holdout questions, claim-level citation entailment, financial arithmetic/units and no-answer quality still need acceptance. No exhaustive relevance labels means no defensible blanket Precision/nDCG claim.
- Source offsets, scope constraints, immutable publication, citation IDs, admission limits and shared billing reservations are implemented. These are not guarantees for arbitrary financial questions or multi-tenant permissions.
- Real filtered ANN checks and synthetic 10k/30k/100k stress tests are separate. Synthetic SQL p95 is not end-to-end p95 or RPS. [Evaluation boundaries](docs/evaluation.md).

```bash
pytest -q
ruff check src tests --exclude src/finrag/vendor
python scripts/verify_public_evidence.py
# Requires local corpus + PostgreSQL; no paid models:
FINRAG_INTEGRATION=1 pytest -q
python scripts/build_golden_v2.py --check
```

[Current release validation](reports/public/project_guide_validation.json) · [Historical receipts](reports/public/README.md) · [Directory/code guide](docs/development.md) · [History](docs/history.md) · [Contribution guidance](CONTRIBUTING.md) · [Data/third-party notices](NOTICE.md).
