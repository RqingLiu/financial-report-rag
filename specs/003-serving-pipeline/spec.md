# 003 — Incremental ingestion and bounded serving pipeline

Status: implementation and bounded development validation complete; production quality/load acceptance pending. Historical experiments remain development evidence, not a release gate.

## Scope and contracts

FR-01 Preserve frozen finrag data/configs and existing CLI. New serving namespace and entry point.
FR-02 Publish one immutable filing + blocks + one versioned chunk index + vectors + lexical postings atomically. Embeddings precede publication; unchanged retry is a no-op; changed identity/content is rejected, amendments are separate filings. No all-index delete.
FR-03 Read catalog from the published database, names/aliases from metadata. New companies/reports require no Python edits. Bound file, catalog, candidates, SQL, provider, concurrency and context resources; return typed errors without widening scope.
FR-04 Explicit exact/HNSW/IVFFlat paths, correct cosine operator, bounded iterative filtered scans, statement timeouts and explain/recall benchmark. ANN index maintenance is separate from ingestion; exact is the quality control. Do not claim million-row throughput from this corpus.
FR-05 Evidence-objective regrouping may change tasks/query wording, not needs/companies/as_of/exclusions. Cross-company tasks run equivalent objectives across selected firms. Same or fewer SQL jobs as original plan and same dense k; validate both total calls and each company's report-year coverage. At most one repair, cache by prompt/plan/catalog/config. Objective proposals use primary/alternative scalar queries; a deterministic compiler allocates alternatives only within original SQL capacity. All multi-company objectives share the selected firm scope. Diagnostic reason truncation is allowed only for non-semantic logs, preserving raw API output.
FR-06 Full-corpus BM25 indexed postings with explicit tokenization/statistics and optional dense+BM25 RRF; native FTS remains distinct. No in-memory scan of the whole corpus for each request.
FR-07 Optional LLM or dedicated Voyage CrossEncoder rerank on coarse Top80, original question + source metadata. Explicit failures, no silent reranker fallback. Source-preserving context under evidence and full prompt budgets, then actual need-aligned generation. CrossEncoder scores are not verified need labels.
FR-08 CLI and optional localhost HTTP API share one runtime. Bounded admission, per-request DB/client ownership, query traces, shared persistent billing reservations, request validation and safe errors. No arbitrary model SQL/code or public unauthenticated ingestion API.
FR-09 Separate replay/evaluation from serving. Compare plans under fixed SQL/k/index/context caps, record candidate/Top80/context evidence recall, costs, latency and failures. Gold loaded only after evidence selected. Holdout and semantic/numeric answer correctness remain required before a production quality claim.

## Acceptance

A1 DB tests: atomic failure rollback, idempotency, new opaque issuer/report, catalog visibility, concurrent read while publish, temporal scope and old data preserved.
A2 ANN: actual EXPLAIN index usage, overlap@k against exact, cutoff/issuer filters; IVFFlat adapter exercised in isolated fixture. Large-scale throughput explicitly pending until representative data/load exists.
A3 Offline: regroup scope/need/job violations rejected; provider/rerank validation, concurrency-safe cache writes, context budget and query→rerank→answer contracts pass.
A4 Controlled dev comparison over existing 20 queries; live provider pilot then bounded reranking/generation comparison, no score-based automatic default promotion.
A5 README current diagram/commands/module map, Notion current architecture and audit findings synchronized; Figma update only if connector available.

## Non-goals

No LangGraph/subagents, forecasts/valuation, XBRL facts/calculator, public deployment, new ground truth, wholesale historical refactoring, or promise that 69.81% holds on unseen queries.
