# Workflow explorer

The local UI uses the same LangGraph runtime as the CLI and evaluation runner. It has no separate model client, retrieval pipeline or npm server.

```bash
# From the project root, using the verified environment:
.venv-migrate/bin/python -m finrag.serving.cli serve --port 8000
```

Open **http://127.0.0.1:8000/**. Startup, code inspection, history and replay do not call paid providers. Live queries need the local PostgreSQL corpus, provider credentials and available budget. The page displays a blocked budget without increasing it. The active shared stop is $4.90 within the existing $5 authorization; $0.10 is retained for legacy embedding usage outside the shared ledger. The $0.15 request cap includes $0.04 answer headroom; neither is an extra allowance. Costs include planning, query embedding, LLM reranking, answer generation and any bounded repairs. Historical document embeddings are cached, not rebuilt for each question. Retrieval-only still uses planner/embedding/reranking and can cost money.

## What the page shows

1. **Question:** enter analysis years in natural language when needed. Advanced options hold the information cutoff (today by default), optional reading background and typed confirmed-context JSON. The cutoff limits public filings, not analysis years. Missing periods may use all eligible report coverage with an explicit answer notice; material ambiguity prompts clarification. A new request begins only through Run. Cancellation is cooperative; in-flight calls may still settle.
2. **Actual workflow:** graph-owned nodes/edges, observed path, status and inclusive node duration. Optional regroup/calculate are hidden until enabled or explicitly shown. Resource setup is shown separately. A node completing successfully does not establish financial correctness.
3. **Step inspector:** responsibility, recorded timestamps, input/output summaries, business state before/after with changed fields, nested model/SQL spans and code locations. New `plan.temporal_scope` records `analysis_period`, `source`, `source_quote` and `rationale`; the inspector summarizes these alongside selected report years and the disclosure cutoff. Old plans without this annotation are not reconstructed. State is allowlisted and bounded: large candidate collections use IDs/counts instead of repeated text or vectors. Unrecorded and clipped data remain explicit.
4. **Results:** source-preserving answer rendering, clickable citations, final evidence, filtered coarse candidates/grades/context decisions, actual QueryPlan and original question. Retrieved text is rendered as text, never executable HTML. Reranker grades are model predictions.
5. **Saved runs:** select a local query or managed evaluation run/case. The existing41-case baseline is accessible without copying it into query logs. Playback/previous/next/scrubbing step through recorded nodes; playback advances nodes at a fixed one-second interval, not a simulation of original wall-clock speed. Measured durations stay unchanged.

Old baseline traces contain node count summaries and detailed stage spans but no complete business-state snapshots. The page says so rather than reconstructing historical state from current data. New graph executions capture bounded state. If an explicitly labeled offline contract fixture is present locally, it demonstrates new state capture using mocked dependencies; it is not a real financial answer or a benchmark result.

## Timing, events and source identity

`agent/graph.py` owns registration and conditional routing. `core/tracing.py` assigns event sequences; node/stage events have separate safe projections in `serving/explorer.py`. Nested spans carry the node operation ID. The browser reconciles events by identity and uses the terminal snapshot as authoritative; refreshing or reconnecting does not resubmit a paid request.

Request wall time includes resource setup/cleanup. Node time includes its nested operations, so do not add child times again. The live elapsed timer is provisional. Displayed costs are recorded conservative estimates, not invoices or the cost of replay. There are no online Recall/accuracy scores.

Each node has adapter, graph and algorithm references. New traces record relative source path, function, line and SHA. The Code tab serves bounded snippets from the **current checkout** and flags hash differences; old records without identity are not historical code snapshots. Code references do not claim every optional function executed.

## Files

| Area | Responsibility |
|---|---|
| `agent/graph.py` | Real graph, node observations and workflow metadata |
| `core/tracing.py`, `core/observations.py` | Sequence/operation identity and safe bounded state capture |
| `serving/api.py` | Same-origin localhost API, SSE, cancellation, readiness and admission |
| `serving/explorer.py` | Allowlisted node/stage/state/result projections |
| `serving/history.py` | Managed local run discovery and bounded case reads |
| `serving/code_view.py` | Fixed source-symbol registry; current line/hash/snippets |
| `static/js/main.js` | UI lifecycle, selectors, playback and explicit query submission |
| `static/js/transport.js` | POST/SSE parsing and read-only API requests |
| `static/js/state.js` | Live-event reducer and playback visibility |
| `static/js/workflow.js` | Node/path/status/timing overview |
| `static/js/inspector.js` | State changes, child calls and implementation viewer |
| `static/js/results.js` | Answers, evidence, candidate decisions and plan |
| `static/js/dom.js`, `static/css/style.css` | Safe DOM helpers, responsive layout and visual styles |

## HTTP contracts and access boundaries

| Route | Behavior |
|---|---|
| `GET /` / `/static/...` | Packaged module-based application |
| `GET /workflow` | Graph-owned node metadata and compiled edges, no DB/model setup |
| `GET /readiness` | Read-only budget status; no credential or reservation IDs |
| `GET /health` | Database/index readiness; no paid model call |
| `GET /runs` | Up to50 eligible managed evaluation runs plus recent live query IDs; small manifests only |
| `GET /runs/{run}/cases/{case}` | Registered run membership and bounded, symlink-safe trace projection |
| `GET /traces` / `/traces/{uuid}` | Backward-compatible live history, strict UUID validation |
| `GET /code/{component}` / `/components` | Fixed registry, bounded source excerpts; no arbitrary file reader |
| `POST /query` / `/query/stream` | Same actual runtime; potentially paid, existing controls apply |
| `POST /queries/{id}/cancel` | Signal active request cancellation; no instant-preemption promise |

No ingestion, shell, arbitrary SQL, raw prompts or general file access is exposed over HTTP. Raw traces, credentials, caches, local evaluation reviews and fixture artifacts remain ignored by Git. This is a loopback research UI, not a public multi-tenant deployment.

## Verification

Provider-free regressions check graph parity, streamed node/state events, source identity, clipping/privacy, managed run membership/symlinks, original UUID routes, cancellation and assets. Wheel verification confirms nested JS/CSS packaging. Browser checks use recorded baseline results plus an explicitly labeled offline fixture; they do not establish new financial-answer quality.
