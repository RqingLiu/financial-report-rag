# Implementation Plan: Auditable Development Baseline
**Date**: 2026-10-26 | **Spec**: [spec.md](spec.md)

## Technical Context / Decisions
Reuse Python3.12, httpx, Pydantic, PostgreSQL, Voyage and the existing Retriever. New entry:`python -m finrag.baseline`. Preserve old retrieval source to protect frozen replay fingerprints. A Repository proxy records actual dense/fts searches; a Retriever subclass captures only super._search output and reconstructs diagnostics using original RRF/interleave. Save all candidate payloads for offline span scoring; actual generation receives only super.retrieve(k=10) output.

New modules:`tracing.py` for local JSON stage hierarchy, `generation.py` for DeepSeek/shared budgets, and `baseline.py` for query-only adaptation, observation, evaluation and Markdown/HTML review. `tests/test_baseline.py` covers important behavior. Without cloud credentials, explicitly use local_only rather than provisioning a service. The trace can later map to LangSmith.

## Contracts
- Query-only input supplies original question/reading context. U14 uses confirmed_context; reject conflicts. Never derive filters from gold.documents or evidence groups. Retrieval/generation receive the same valid input. corpus_scope describes available material, not a filter containing every company.
- Stage fields:id,parent_id,name,start/end/duration,status,inputs,outputs. Never automatically serialize clients, Settings, headers or exception bodies. Atomically save one trace per question.
- Three scores: candidate union, fused top5/10/20 without context limits, and actual final context. The first two are diagnostics, not online Top20 claims. Load gold after retrieval/generation; scoring cannot change runtime.
- Numeric/factual/citation-semantic review defaults to pending_human. Citation-ID/date checks are structural, not faithfulness. Generation may state source text/formulas but must label arithmetic unverified without deterministic execution.
- Budget: fcntl-locked JSONL events, reserve→settle. Unresolved reservations remain until manual reconciliation. Fixed shared path; stop new calls at $4.5. Before calls, estimate an input upper bound from UTF8 bytes plus envelope allowance and reserve max_tokens output. Conservative historical prices per million: DeepSeek peak uncached input/output $0.30/$1.20; Voyage4-lite $0.02. Settle using reported usage/list price, not an invoice reflecting discounts/time bands. Do not retry unknown responses/timeouts; retain reservation. Release only confirmed unsent connection failures. Unknown usage stops the paid batch.
- DeepSeek model deepseek-flash, thinking disabled, temperature 0, max_tokens 4096, serial, httpx timeout 60 seconds, zero automatic retries; no Search/Fetch. Record returned model name/ID and finish_reason.
- Reuse embedding cache, call only for missing query vectors, and share the provider budget. Do not rebuild document embeddings.
- Unique run directory per experiment. Resume from completed query traces with explicit reused status. Support retrieval-only or generation from existing traces to avoid duplicate retrieval.

## Constitution Check
Explicit sources/FY/cutoff; gold isolation; independent modules preserving frozen behavior; no new background service; bounded cost/calls; service errors distinguished from missing evidence; ignored local secrets; no claim of human-approved answers. Compliant.

## Execution / Evidence
Run offline contracts/old regressions/gold --check, read-only DB connectivity, 20-question retrieval diagnostics, then a6-question generation pilot (U02/U03/U06/U09/U12/U14). Check actual usage/truncation before the remaining 14. Save manifest/trace/scores/review/summary. Report root causes after observation; do not tune retrieval in this round. Pricing sources checked2026-10-26: official DeepSeek pricing/chat API and Voyage pricing.
