# Implementation plan

1. Add scope guard helpers, typed confirmed context and regression cases; keep retrieval/rerank/context budgets unchanged. New planner version invalidates stale cached plans rather than mutating historical traces.
2. Correct the table fallback and add ingestion source-coverage/preflight checks. Reproduce current selected chunks to establish compatibility; retain original config/index IDs only if every current chunk is unchanged.
3. Download six filings into the existing raw storage with a separate generalization source manifest. Publish through LiveStore with existing document embedding cache/shared budget. Enrich aliases through trusted metadata registration, leaving frozen configs untouched.
4. Split the large historical README into docs; keep current entry and limitations visible. Create project-local Git metadata after reviewing parent Git scope. Use a dedicated report publication allowlist; keep bulky/personal diagnostics local. Add CI and a staged-content scanner. User explicitly selected public RqingLiu/financial-report-rag.
5. Offline/DB/frozen checks, source/chunk/ANN smoke and budget receipts; Notion current diagram/contract update. Report remaining natural-question/answer review and optional repository visibility input.

No new services or agent framework. Acquisition can proceed while code is validated; paid embedding waits for parse/coverage/cost preflight. No branch, database, raw source or frozen label deletion.
