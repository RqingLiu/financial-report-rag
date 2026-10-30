# Implementation plan

1. Establish main at the delivered commit, retain the prior branch, and implement on codex/trace-explorer.
2. Add an optional per-trace event sink and read-only allowlisted HTTP projection. Persist original diagnostic traces privately as before.
3. Add bounded SSE admission/background-worker lifetime, managed history endpoints and static assets to the existing service. No frontend dependency/build process.
4. Build an interactive pipeline map with stage inspector, task/search cards, rank/grade/selection comparison and evidence-linked answers. Preserve raw source text safely.
5. Run offline tests and browser QA with historical real traces, update architecture/development docs, scan staged publication content and publish a PR against main.
