# Plan: Repository organization and a live workflow explorer

**Date:** 2026-11-12. **Status:** implementation authorized on 2026-11-12; no paid execution.

This plan covers repository organization and the local interactive UI. It does not authorize paid model/Judge calls, changes to retrieval/planning algorithms or budgets, database cleanup, or GitHub publication. It is separate from the financial-correctness optimization proposal associated with evaluation 009.

## 1. Outcome

One documented command opens the existing localhost application. A user enters a question and sees the actual LangGraph execution, each node's state changes, elapsed time, implementation location and recorded results, followed by the answer and supporting evidence. The UI explains what each step does without asking another LLM to explain the trace.

Reuse FastAPI, the existing POST/SSE transport, LangGraph and the current trace/code/evidence viewers. Keep a local, lightweight application without introducing React/Next.js, another service, database or agent runtime. A later need for a larger frontend can justify a separate decision.

## 2. Verified current state

| Area | Finding | Consequence |
|---|---|---|
| Existing entry | `.venv-migrate/bin/python -m finrag.serving.cli serve --port 8000`, then `http://127.0.0.1:8000/` | A frontend already exists; improve its discoverability and behavior instead of creating another entry |
| Actual workflow | Ten registered LangGraph nodes; normally eight execute, with optional regroup/calculate | The current hardcoded eight-stage UI is not the actual node graph; embedding and rerank belong under nodes as child operations |
| Missing live node events | `api.py:on_event` sends every event through `stage_view`; node events have `node` rather than required `name`. A provider-free probe reproduced `KeyError`. `Trace.emit` suppresses observer exceptions | Actual node start/end events are lost; fix the event contract before adding animations |
| State visibility | Node transition data currently records counts/outcomes, not detailed business-state deltas. Stage spans retain more input/output | Add explicit bounded state capture for future runs; do not manufacture historical snapshots |
| Code references | Current component registry still attributes some stages to runner as their orchestration callsite | Map graph node adapters, algorithm functions and actual child-call provenance separately |
| History | Browser reads UUID traces from `logs/serving`; the 41 baseline traces live under an ignored evaluation run with U-style IDs | Add a managed run/case browser; no arbitrary filesystem reader or weakening of existing UUID routes |
| Frontend size | About 1,492 lines of JavaScript and 1,367 lines of CSS in single files | Separate responsibilities while retaining one frontend and one startup command |
| Repository | Runtime already has agent/ingestion/retrieval/answering/providers/core/serving/evaluation packages. Many local changes are uncommitted | Preserve existing work; do not move every Python file or equate uncommitted work with obsolete code |

## 3. Proposed experience

- **Header/composer:** question, disclosure cutoff, optional confirmed context; clearly separate Live query and Saved run modes. Display prerequisites and budget-blocked status without bypassing controls. Startup, history, replay, code inspection and refresh never trigger a paid query.
- **Execution overview:** a compact ordered workflow with real node status and elapsed time. Highlight the running node and taken edge; collapse disabled optional nodes. Show graph-external setup/cleanup separately. Make all branches accessible by keyboard and at narrow widths.
- **Selected-step inspector:** plain-language responsibility; observed input summary; changed state fields; output; actual child calls; source/implementation references. Keep technical JSON and long tables expandable, not the default presentation.
- **Answer/evidence area:** show the final answer prominently, with clickable source citations. Preserve plan, search jobs, candidate ranks, reranker grades and context inclusion/exclusion as inspectable views. Do not render retrieved document HTML as executable content.
- **History/replay:** browse local saved query runs and explicitly managed evaluation runs/cases, including all 41 baseline attempts. Selecting a case shows original input, executed path and results. Optional play/pause/step uses recorded events/times only and is clearly labeled playback, not a new execution.

Every node shows pending/running/completed/failed/cancelled/skipped or another precise terminal state. Cache is a badge, not a synthetic execution state. Unsupported/clarification/empty-evidence paths are valid branches, distinct from technical failures. A node with zero measured time must not be assigned an invented duration.

New-run updates are step-level: inputs/state at entry, outputs/state changes at completion. A running elapsed timer is labeled provisional and reconciled with the recorded server duration. This increment does not require token-by-token model output or reveal model chain-of-thought. Explanations are static responsibilities plus factual templates such as counts/filters/results; they are not claims about hidden model reasoning.

## 4. Data and event design

1. Define one versioned event envelope with run/query ID, event sequence, kind, node/operation ID, span/parent ID when applicable, timestamps and status. Dispatch node and stage events through separate allowlisted projections. Continue noncritical observation: a visualization failure cannot change a query result or cause a paid retry.
2. Link nested embedding/model/SQL/rerank/context stages to their actual node operation. Obtain topology and conditional branches from graph-owned definitions; the browser must not maintain a second independently drifting graph.
3. Capture a bounded business-state projection: request scope, validated plan, search references/counts, candidate/selected IDs, evidence references, generation and terminal outcome. Record changed fields and a lightweight before/after view; load large details on demand. Exclude RunContext clients, credentials, raw system prompts, vectors and arbitrary configuration. Clearly distinguish absent, omitted, clipped and failed data.
4. Avoid copying every candidate/source into each state snapshot. Reference already recorded artifacts and preserve caps/pagination. Failed nodes expose the last confirmed state and their actual error; no fabricated output patch. Additive trace versions keep existing evaluation and query contracts compatible.
5. Define timing explicitly: total request wall time; inclusive node time; nested operation time; live provisional timer. Never sum nested durations into a fictitious total. Cached calls and retries remain visible; recorded usage/cost estimates are not invoices or online answer-quality scores.
6. Give each node its adapter location, graph wiring reference and algorithm implementation. Retain relative path, symbol, line and SHA for actual new execution provenance. Current-checkout code snippets must be marked current; hash differences and missing historical identity remain visible. Function registration does not prove every optional function executed.
7. Reconcile duplicate/out-of-order/missed events by sequence and IDs; terminal snapshots are authoritative. Refresh or reconnect must not resubmit a paid POST. Cancellation uses the existing endpoint and cooperative semantics; a lost browser connection is not evidence of immediate cancellation settlement.
8. Register trusted local evaluation directories internally, list run/case metadata, and validate filenames, symlinks, size, scope and identity. Use opaque registered IDs for browser routes. Never accept a user-supplied absolute path, traverse the filesystem, or expose raw provider traces. Old UUID history routes retain their restrictions.
9. Legacy traces are read-only. If they lack node events or state snapshots, show available recorded spans/transition counts and label unavailable fields; do not infer historical states or code versions from today's database/source.

## 5. Repository organization

Keep `src/finrag` as the installable package and preserve the current domain packages. Improve navigation and split actual oversized UI responsibilities rather than moving working modules merely to change appearance.

| Area | Planned action |
|---|---|
| `serving/static/` | Modularize into `index.html`, `js/` entry/transport/state/workflow/inspector/results modules, and `css/` layout/style files. Update package-data globs and the same-origin module entry; no npm/build server |
| `core/tracing.py`, `agent/graph.py` | Additive event identity, node timing and bounded state observation; preserve workflow/ranking semantics |
| `serving/api.py`, `explorer.py` | Typed node/stage dispatch, safe state projection, managed history/replay. Split projection/history code only where responsibilities justify it |
| `serving/code_view.py` | Correct node-to-adapter/algorithm mapping and keep bounded, allowlisted code access |
| `evaluation/` | Retain current CLI, datasets, scorers, baseline and audit receipts. Evaluation run discovery is read-only; gold never enters runtime |
| `scripts/` | Retain the six documented active operational/dataset scripts until dependency/provenance checks prove any obsolete |
| `docs/`, `specs/` | README remains the entry; link architecture, code map, operating commands and evaluation. Update stale behavior descriptions; preserve required versioned specs instead of creating another archive |
| Local generated material | Inventory caches, egg-info, build artifacts and intermediate outputs; remove only demonstrably unused/reproducible duplicates in implementation. Do not delete virtual environments, credentials, embeddings, raw corpus, shared ledger, active DB or the baseline evidence needed for replay |
| Working tree/Git | Capture a change inventory, preserve existing uncommitted work and separate cleanup from behavioral changes. No commit/push or raw-trace publication under this planning request |

README must explain each retained directory/script, the primary UI command, live-query cost, offline history mode, prerequisites and common blocked states. A launcher alias is optional; do not add a second runtime or duplicate existing CLI commands to solve discoverability.

## 6. Implementation sequence after review

1. Write acceptance requirements/tasks and freeze baseline identities plus the existing working-tree inventory. Audit imports, packaging and active entrypoints before any deletion.
2. Correct the node/stage event path; add sequence/timestamps, node-operation linkage, bounded business-state deltas and compatible historical projections. Keep retrieval, prompts, model configuration, budgets and database data unchanged.
3. Add graph-owned workflow metadata, managed evaluation history and correct code references. Expose actual cancellation and safe diagnostics; distinguish startup readiness, budget limits and query errors.
4. Refactor the existing static frontend into modules and implement the compact execution overview, inspector and prominent answer. Keep one transport/state reducer for live and recorded data, with explicitly different modes.
5. Validate replay of representative saved success, partial, refusal/clarification and failure records where available. Include the three baseline plan failures and material-error answers without relabeling them as correct. Old traces cannot demonstrate absent new fields.
6. Complete the scoped cleanup and documentation, verify package installation/assets and startup, and inspect the real browser at desktop/narrow widths. Paid smoke testing is a separate decision; opening the UI and replaying saved runs require none.

This UI increment should precede or remain isolated from the P0/P1 financial-correctness work. Mixing both into one score comparison would obscure which intervention changed the answer.

## 7. Acceptance and verification

- **Event correctness:** node start/end events survive projection; child spans map to the correct operation; repeated or missing SSE events reconcile with final state; empty/optional/error branches are truthful.
- **State correctness:** new nodes expose captured, allowlisted inputs/changes/outputs; secrets/clients/vectors are absent; legacy missing state is labeled, not reconstructed.
- **Timing/source correctness:** no nested-time double count; source path/symbol/line/hash resolve; current code and historical provenance are distinguished.
- **No-cost replay:** all 41 baseline cases are discoverable; 38 actual answers and three failures remain visible. Opening, stepping, refreshing or reconnecting saved records invokes no provider and does not alter the ledger.
- **Controls:** cancellation, budget/deadline outcomes, admission limits, errors and evidence-only fallback remain correct. A blocked budget is displayed, not silently raised. Paid live requests are submitted only by an explicit user Run action.
- **Organization/packaging:** documented entry works from the project root; modular static assets are included in the built package; no imports/links rely on deleted files. No credentials, private paths, caches or raw traces are added to the public source tree.
- **Browser usability:** run a provider-free controlled event fixture and inspect the actual UI, then inspect real saved baseline records. Mark fixtures as simulated. Keyboard/narrow-screen navigation, source links and lazy detail views work; no fake online Recall/accuracy or invented progress.

Use existing pytest/API tests, focused event/projection/security/packaging tests and browser checks. No financial benchmark rerun or paid Judge is required for UI acceptance. Keep generated regression fixtures minimal; do not create another copy of the full baseline.

## 8. Scope boundaries

No automatic Web research, unrestricted code/file access, raw credentials/prompt display, new agent framework, multi-agent runtime, persistent conversation memory, database/index migration, or retrieval-quality tuning. No automatic paid query on page load, history selection or replay. No automatic spending-stop increase, cloud tracing, deployment, commit or push. Required semantic/runtime changes, if discovered, must be described before broadening this UI/organization increment.

## Implementation authorization

The user approved this plan, requested starting the local UI and publishing the reviewed code/documentation to origin/main after secret/privacy checks. This supersedes the earlier proposal-only publication restriction. Keep retrieval/generation strategies, model settings, budgets and stored financial data unchanged; no paid calls. Preserve previous working-tree changes and include the completed project work in the reviewed delivery.

## Implementation verification — 2026-11-12

Implemented separate node/stage projections, graph-owned metadata, operation-linked spans, bounded state before/after, managed run/case discovery and modular UI with read-only stepping. Replaced the retired single-file JS/CSS. All 41 baseline cases are available locally; a separately labeled mocked graph fixture demonstrates new captured state without paid calls. Browser checks covered real successful/failed records, citations, source positions, playback, and390px/1280px layouts. Retrieval/planner/generation/config/ledger hashes match the pre-implementation snapshot. Initial full offline regression:161 passed,7 skipped; lint/dependency/public-evidence checks passed. Publication scans found no credential or home-path patterns in staged content or437 historical blobs. This does not certify absence of every possible secret. The budget remains blocked at its existing cumulative stop, so live submission is disabled while free history remains usable.
