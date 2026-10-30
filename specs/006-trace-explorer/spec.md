# Local query and trace explorer

## Problem and scope

Researchers currently need CLI JSON and local trace files to understand a query. Add a localhost browser interface to the existing FastAPI service: submit natural questions, observe real pipeline stages, inspect planning and retrieval decisions, and follow answer citations to supplied evidence. One service and one pipeline; no agent framework or separate frontend build service.

## Requirements

- Show question, disclosure cutoff and optional reading context. Full answer and retrieval-only modes share existing validation, budgets and admission control. Retrieval-only still uses paid planning/reranking.
- Stream actual stage start/end events, including nested model calls and individual searches. Distinguish pending, running, completed, failed and skipped stages without simulated progress.
- Inspect validated company/report-FY/need/task/query plans; show individual search queries, document scope, distance/scores and hits. Show coarse rank, reranker grades and context inclusion/exclusion decisions; expose selected evidence and citation links.
- Load bounded local serving traces without invoking a model. Clearly identify historical runs. Do not imply a reranker judgment is verified factual support or show recall without labels.
- Public HTTP projections exclude credentials, config paths, raw provider bodies and model/system messages. Treat displayed queries/documents/answers as untrusted text. Only managed UUID trace IDs can select local files.
- A browser disconnect does not cancel paid worker operations or release admission early. Existing POST /query and CLI remain compatible; no retrieval defaults or frozen artifacts change.
- Bind to localhost. No public deployment/authentication/ingestion UI in this increment.

## Acceptance

Offline contracts cover SSE event ordering, projection privacy, bounded history/path validation, worker failure and admission lifetime. Existing tests pass. Browser QA uses real saved traces without paid calls and verifies planner/search/ranking/context inspection, source links and narrow-screen layout. Document how to launch and how to use the GitHub main/feature/PR workflow.
