# Architecture and implementation map

The default query engine is a bounded LangGraph StateGraph (`agent/graph.py`) with request-local typed business state and dependency context. `serving/runtime.py` adapts the existing CLI/API contract. A planner is still one bounded model operation, not an autonomous subagent. PostgreSQL stores sources and retrieval indexes. Deep Agents, subagents and persistent checkpoints are not used.

The [next-runtime proposal](rag-agent-refactor.md) describes a typed-state, bounded LangGraph migration and its dependency/replay gates. The equivalent migration is implemented; evidence-driven follow-up remains planned.

```mermaid
flowchart TB
    subgraph Ingestion["Trusted CLI ingestion"]
        SEC["SEC HTML + filing/company metadata"] --> Preflight["SHA256 / immutable source preflight; unchanged skips embedding"]
        Preflight --> Parse["lxml: paragraphs, tables, DOM locators, character offsets"]
        Parse --> Chunk["Structure chunks: 512 proxy tokens / overlap 64; long-table preservation"]
        Chunk --> Coverage["Parsed-source coverage guard before paid embedding"]
        Coverage --> Embed["Voyage 4-lite: document role / 1024 dimensions / cache / shared billing"]
        Embed --> Publish["Atomic document publication: sources, chunks, vectors, BM25 postings/statistics"]
    end
    Publish --> PG[("PostgreSQL + pgvector")]
    User["CLI / local browser / API: question, background, confirmed scope, as_of"] --> Planner["DeepSeek QueryPlan: needs, tasks, company/report FY, retrieval queries"]
    PG --> Catalog["Published catalog + registered aliases"]
    Catalog --> Planner
    Planner --> Guard["agent/scope.py + validate_plan: alias binding, per-company FY, typed confirmation"]
    Guard --> Decision{"retrieve / clarify / insufficient"}
    Decision -->|retrieve| QueryEmb["Voyage query-role embeddings"]
    Decision -->|other| Response["Answer / clarification / missing evidence / typed error"]
    QueryEmb --> Recall["Per query × company/FY: dense Top20; default HNSW cosine"]
    PG --> Recall
    Hybrid["Optional: BM25 replaces second dense variant, same SQL budget"] --> Recall
    Recall --> Fusion["Variant RRF c=60; task/company-FY interleave; retain ≤512"]
    Fusion --> Shortlist["Top80 coarse shortlist"]
    Shortlist --> Rerank["Default: LLM source-line relevance; optional Voyage CrossEncoder"]
    Rerank --> Context["Source-span dedup + small-table expansion; ≤30 items / 8K evidence / 24K serialized input"]
    Context --> Generate["DeepSeek need-aligned answer; citation ID and output structure checks"]
    Context -.-> Calc["Opt-in pilot: evidence operands + bounded Decimal arithmetic"]
    Calc -.-> Generate
    Generate --> Response
    Response --> Trace["Local stage trace, source spans, model usage and cost ledger"]
    Trace -.-> Explorer["Same FastAPI service: actual stage SSE + safe history projection; interactive trace UI"]
    Trace -.-> Eval["Offline evaluation loads gold only after evidence selection"]
```

## Runtime choices

| Component | Current default | Implementation |
| --- | --- | --- |
| Public input contract | `question`, required `as_of`, bounded `reading_context`, typed `confirmed_context` dictionary | `agent/planner.py: Request` |
| Planner | DeepSeek `deepseek-flash`, JSON schema with specific field/type repair feedback; ≤16 needs / 4 tasks / 2 queries per task; one repair | `agent/planner.py: plan_request` |
| Scope | Catalog aliases and confirmed metadata; explicit FY associations and exclusions per company | `agent/scope.py`, `agent/planner.py: validate_plan` |
| Retrieval | HNSW cosine, ef_search=100, iterative strict order, scan cap=20,000; Top20 per job; transaction-local JIT off | `retrieval/store.py: search` |
| SQL/resource bounds | ≤12 company/report-year groups per task; ≤192 actual search attempts including retries; SQL timeout 5s/attempt; one timeout recovery slot per request, no user-cancel retry | `configs/serving.json`, `retrieval/store.py` |
| Coarse fusion | RRF c=60 plus group/task interleave, ≤512 candidates, Top80 shortlist | `retrieval/search.py: rank_records` |
| Keyword alternative | PostgreSQL BM25 postings; one lexical job replaces the second dense job | `retrieval/lexical.py`, `retrieval/store.py` |
| Reranker | LLM 0–4 grades, need IDs and source-line bounds; batches ≤32 candidates | `retrieval/rerank.py` |
| Dedicated reranker | Optional `rerank-3-lite` query/document joint scoring; not embedding similarity | `providers/voyage.py: CrossEncoder` |
| Context | Original spans, overlap dedup and bounded table expansion; 8K/24K proxy-token caps | `retrieval/evidence.py`, `retrieval/context.py` |
| Answer | Supported/partial/missing per need; one structural repair with the preceding response and typed feedback; no automatic semantic acceptance | `answering/generation.py` |
| Arithmetic preparation | Opt-in (`calculation_tool=false` by default): one model call selects ≤32 source-anchored values/expressions; bounded Decimal execution, no arbitrary code. Literal/sign checks do not certify metric, period or unit selection | `answering/calculations.py`, `serving/runtime.py` |
| API | Localhost FastAPI, ≤2 in-flight requests, admission before worker dispatch | `serving/api.py` |
| Query UI | Static HTML/CSS/JS, actual stage SSE, read-only history; shared pipeline/budget | `serving/static/`, `serving/explorer.py` ([details](trace-explorer.md)) |
| Cost/trace | Persistent reservations; unknown billing stays reserved; no blind paid retry | `providers/llm.py`, `core/tracing.py` |

`cl100k_base` counts are a budget proxy, not the providers' billing tokenizer. Default retrieval is dense multi-query plus LLM reranking; retired rule-based hybrid controls have been removed from the source tree.

The 2026-11-07 reliability follow-up keeps planner, ANN parameters, fusion, reranker and context caps unchanged. The experimental generation profile emphasizes complete comparisons, late rounding, period-specific accounting-effect bridges and trend checks. Both that profile and arithmetic preparation require `calculation_tool=true`; the default generation prompt is unchanged. Structural repair and optional arithmetic remain within the shared paid-call ledger and 24K input cap. A second invalid structure remains a visible failure; a rejected arithmetic worksheet supplies no verified results. These checks do not establish answer truthfulness.

## Storage and provenance

`documents` holds immutable filing metadata; `blocks` holds parsed text/table structure and DOM/character locators; `chunks` holds source spans, embedding text, vectors and lexical fields. `publications` makes complete documents visible. `postings`, `term_stats` and index length statistics support BM25. Every selected evidence record carries document/accession context, date and source spans.

The current serving namespace is `finrag_live_ready`. The old `finrag` (five research chunk configurations) and `finrag_live` (bootstrap copy) schemas were removed on 2026-11-07. Compact historical results remain under `reports/public/`; retired vectors do not occupy a second database copy. The active schema retains one selected chunk configuration. Current ingestion publishes directly from HTML and metadata; it does not require bootstrap or the old research database.

Company aliases can be updated through the trusted metadata CLI without editing Python issuer lists. They are business entity metadata, not tenant authorization. This service has no public deployment or multi-tenant authorization claim.

## Correctness boundaries

- Report FY and a numeric table's fact FY are different. Explicit report constraints and confirmed scopes are guarded; arbitrary financial-period language still needs clarification and held-out evaluation.
- The FY guard recognizes explicit `FY2024`/ranges and bounded company associations. It is not a universal temporal parser. Unknown aliases should be clarified or registered rather than guessed.
- Long tables with four or fewer rows are retained even after preceding prose. Rows/headers can exceed the target chunk size; source coverage does not prove correct financial column interpretation.
- Citation existence, source offsets and answer shape are checked. Numeric accuracy, causal support and claim-level entailment are not automatically verified.
- Per-call SQL/provider timeouts exist; a shared end-to-end deadline and representative load acceptance remain open work.

The ANN filtering and iterative-scan approach follows [pgvector's documented behavior](https://github.com/pgvector/pgvector#filtering). Small filtered sets may favor exact search; no automatic router is currently enabled.


## LangGraph migration — 2026-11-08

`agent/runner.py` binds RunPolicy, then invokes the compiled graph. `agent/nodes.py` calls the existing algorithms; `reference.py` retains the sequential rollback control. Plans, ranking, evidence and answer inputs are compared with deterministic receipts; this is an orchestration check, not a new answer-quality score. Node transitions/tool receipts and additive typed outcomes are recorded alongside the original spans. No graph retry policy or checkpoint backend is enabled. Availability gating does not assert semantic sufficiency.

`configs/serving.json` keeps the same retrieval/context/model settings and adds `engine` and `run_policy`. Request-local counts and optional deadline/cost caps share the existing persistent ledger; unknown charges remain held. Deadline checks are cooperative, with existing HTTP/SQL timeouts for in-flight operations. [Detailed source and state map](repository-layout.md).
