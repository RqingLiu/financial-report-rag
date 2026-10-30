# Query and trace explorer

The browser is a local interface to the existing serving pipeline. It has no independent model client or agent runtime. Run from the project environment:

```bash
fr-rag-serve serve --port 8000
# Equivalent: python -m finrag.serving.cli serve --port 8000
```

Open **http://127.0.0.1:8000/**. The CLI binds only to loopback. Python/FastAPI serves the HTML, CSS and JavaScript; Node, npm and a separate frontend build/server are not required. PostgreSQL and local provider credentials are needed for new queries. Saved traces can be inspected even when PostgreSQL is unavailable.

## Use

1. Enter a question, explicit disclosure cutoff and optional reading background. The interface executes independent requests, not a conversation with persistent memory.
2. Choose full answer or retrieval-only. **Both can incur planner, query-embedding and reranker charges.** Existing shared reservations, cumulative stop and in-flight limits apply. No budget changes are exposed in the browser.
3. Follow actual stage start/end events on the connected eight-step graph. Click a node, then choose **Overview / Input / Output / Code** in the step inspector. The call selector opens actual child model/SQL calls; JSON fields expand on demand. Zoom/fit controls and background dragging move the canvas. On narrow screens the graph uses four rows and the inspector appears below. There is no synthetic progress percentage. Cache hits can complete a stage without a new model-call span.
4. In candidates, filter by company/text and final selection. Click a row to inspect its text, coarse rank, reranker grade and context decision. Grades/need mappings are model predictions. Coarse order also includes task interleaving, so it need not be monotonic in the displayed RRF score.
5. Click an answer's `[E…]` button to open the actual supplied evidence, its report FY/filing date, SEC link and source block/character spans. Tables are displayed as source-preserving plain text; the browser does not reinterpret column semantics.
6. The newest saved run opens automatically without provider calls. Use **History** beside the data tabs to select another run. Historical mode is explicitly labeled; the composer remains a separate new-query draft. The selector lists the newest 30 managed traces by timestamp/ID; a selected trace is capped at32MiB. Clipped candidate previews are marked. Evidence/answer inspection is distinct from manually reviewed ground truth.

The page title is **财报检索与运行追踪**. Each node displays its primary file/function; its overview lists clickable full repository-relative paths, current lines and function responsibilities. **Code map** above the canvas or in the data tabs shows all stages plus API/orchestration, ingestion, shared model adapters and the optional dedicated reranker. These are current implementation associations, not a claim that every cache/optional branch executed in the displayed run. See [the repository walkthrough](development.md#follow-the-current-query-in-code).

The first node is **已入库年报**, not the repository directory. Its report view reads recorded catalog metadata (or the same run's actual planner business input, clearly labeled as potentially narrowed). The button to read the **current** database is a separate read-only operation with the displayed cutoff, no model request. It shows document/FY/period/filing date, SEC URL and the conventional local HTML path when that file exists. Current rows are never presented as a historical snapshot. The list is capped at500 rows with total/truncation metadata; it does not serve arbitrary local files.

New spans record the orchestration callsite (relative path, function, line and whole-file SHA256). The Code tab reads bounded function excerpts from the **current checkout**, including implementation and orchestration references. Matching file hashes are identified; a changed file is identified too. Old traces have no source identity and are explicitly labeled as current implementation references, **not historical execution snapshots**. A callsite records entering an instrumented stage; it is not a line-by-line profiler of every function called inside it.

New stage inputs additionally record request/scope, shortlist IDs and evidence IDs; the search parent records completion/hit counts. Historical empty fields remain empty. For known model purposes, the inspector projects recorded **business JSON** (request/catalog, reranking candidates/source lines, or generation plan/evidence), with unexpected nested keys removed. Raw system messages, repair instructions and provider answer bodies remain hidden. Validated plans, grades and answers appear on parent-stage outputs. Omitted values and never-recorded values are not reconstructed from the current database.

If the connection drops, the paid worker may still finish and save a trace. Refresh history before submitting again. A disconnected browser does not cancel provider calls or free the service's concurrency slot prematurely. A service restart is different from a browser disconnect; this is not a durable job queue. The timestamp/ID can be used to find the private full trace under `logs/serving/`.

## Component and data map

| Step/view | Observable data | Code |
| --- | --- | --- |
| Catalog | Published filing count/fingerprint | `serving/runtime.py`, `serving/store.py` |
| Planner | Validated company/report FY, needs, tasks, queries, limitations/clarification | `planning.py`, `planning_scope.py` |
| Embedding | Query strings, role/model and recorded usage; vectors omitted | `planned_retrieval.py`, `serving/providers.py` |
| Search | One task/company-FY/query per search, actual document IDs, k, distance, hit text | `planned_retrieval.py`, `serving/store.py` |
| Fusion | De-duplicated candidate order and RRF score | `planned_retrieval.py: rank_records` |
| Rerank | Actual shortlist count, method, grades/need IDs and cache status | `reranking.py`, `serving/runtime.py` |
| Context | Included evidence, selected/source-overlap/budget decisions, token counts/caps | `rerank_context.py` |
| Answer | Need-aligned sections, partial/missing evidence, clickable citations | `answering.py` |
| Events/transport | Actual nested span start/end/status/duration, usage/cost projection | `tracing.py`, `serving/explorer.py`, `serving/api.py` |
| Browser | Connected DOM/SVG canvas, stage inspector, tables, evidence viewer, SSE parser | `serving/static/{index.html,style.css,app.js}` |
| Code inspector | Fixed component/symbol registry, AST line ranges, at most140 lines per excerpt | `serving/code_view.py` |

The duration summary sums top-level spans only; nested model calls are already inside their parents. It excludes setup/serialization/network time and is not end-to-end p95. The cost summary totals this trace's recorded model-call/query-embedding estimates, not historical costs embedded in cached responses or provider invoices. No online recall/accuracy is displayed because it needs labels and offline evaluation.

## HTTP contracts

| Route | Behavior |
| --- | --- |
| `GET /` | Local static application |
| `GET /health` | Existing DB readiness and ANN method; no paid model |
| `POST /query` | Existing non-streaming request/response, unchanged |
| `POST /query/stream?generate=true` | Same request schema; `generate=false` skips answer generation only |
| `GET /traces` | Bounded timestamp/ID/file-size list, no model calls |
| `GET /traces/{query_id}` | Read-only safe projection;32 lowercase hex ID, no arbitrary file path |
| `GET /code/{component}` | Allowlisted component functions from current checkout only; no arbitrary path input |
| `GET /components` | Current allowlisted file/function/line/role map; no DB or model |
| `GET /catalog?as_of=YYYY-MM-DD` | Current published DB metadata filtered by cutoff; at most500 rows, no model |
| `GET /docs` | OpenAPI documentation |

SSE event order: `accepted` → zero or more `stage_started` / `stage_finished` → `result` or `failure`. A `result` may have an error/clarify/insufficient-evidence status. The terminal snapshot is authoritative; bounded queues can discard earlier intermediate events for a stalled consumer. `: keepalive` comments keep idle connections open. The stream reports program steps, not chain-of-thought, and sends the answer after existing structural validation, not unvalidated token-by-token output.

Each trace has its own optional event sink. Worker callbacks create an allowlisted snapshot and transfer it to the async loop. A bounded queue and admission gate avoid an unbounded work backlog; a retained worker task outlives a disconnected consumer. The private original diagnostic file remains unchanged in purpose. The HTTP projection removes raw model/system messages, provider bodies/response IDs, cache keys and runtime configuration. Input/doc/answer text is rendered with `textContent`, not executable HTML. Host/origin checks and a self-only content policy protect the local interface; this is still **not an authenticated public web service**.

Tests use provider-free fake workers to exercise ordering, nested errors, observer failure, projection privacy, replay bounds, failure cleanup, disconnect admission lifetime, source provenance, source-map consistency and read-only catalog cutoff/error handling. Studio007 validation including S06–07: **94 passed / 7 DB tests skipped**, syntax/lint passed; desktop and mobile319px replay checks use real saved runs. Current published catalog16-report/path/source-link checks are read-only; no new paid calls. The earlier006 live smoke is historical evidence, not a new007 live test. A successful smoke query and citation-ID validation do not establish semantic answer accuracy.
