# Data, chunking and ingestion

## Corpus

| Group | Company | Report fiscal years | Role |
| --- | --- | --- | --- |
| Original | NVIDIA / Micron | 2024–2026 | Existing development corpus |
| Original | AMD | 2023–2025, plus FY2025 10-K/A | Existing development corpus and amendment example |
| Expansion | Alphabet (`GOOGL`; Google parent, `GOOG` alias) | 2023–2025 | New-company generalization corpus; evaluation questions pending |
| Expansion | Amazon (`AMZN`) | 2023–2025 | New-company generalization corpus; evaluation questions pending |

Latest-three selection was verified against SEC submissions on 2026-10-28. No FY2026 annual 10-K for Alphabet/Amazon was selected. A fiscal-year label is not a filing year: FY2025 was filed in 2026.

Original metadata stays in `data/sources.jsonl`; new metadata stays in `data/generalization/sources.jsonl`. Each row includes accession, period end, filing date, source URL and raw SHA256. Keeping a separate expansion manifest preserves the original golden dataset's input hashes. Raw filings, parsed data and embeddings are local generated data and are ignored by Git.

## Parsing and chunking

The source path is SEC HTML, not PDF/OCR. lxml removes hidden/script elements and records paragraphs, tables, images, Item labels, DOM locators and canonical character offsets. Tables retain raw HTML/cells and an expanded merged-cell grid. Images are unverified source records, not visual evidence.

The serving selection is `structure_512_table_context`: structure-aware chunks, target512/overlap64 proxy tokens, company/FY metadata prefixes, table-row groups and nearby title/unit text. The first-four-row header assumption is heuristic. A short/fat table is retained as a whole when needed; indivisible rows may exceed the target. Ingestion checks parsed non-image text coverage before paying for embeddings. This does not prove no raw HTML was missed or every financial column was understood.

The long-table fix reproduces all original2,759 selected chunk payloads exactly. Existing indexes/labels were not silently rewritten; the six new filings use the same selected configuration/model/dimension. They produce2,202 additional chunks, bringing serving to16 filings /4,961 chunks.

## Original corpus setup

After configuring PostgreSQL/pgvector and `.env` as described in the main README:

```bash
fr-rag download
fr-rag parse
fr-rag index structure_512_table_context
fr-rag-serve init
fr-rag-serve bootstrap
fr-rag-serve ann
fr-rag-serve aliases --metadata configs/serving_company_aliases.json
```

`download` reuses pinned metadata and cached bytes. `index` may bill uncached embedding inputs. `bootstrap` copies the selected frozen vectors, validating raw parsing against chunk payloads; it does not call a model. The `init` command initializes only the selected serving namespace, not the whole database.

## Expansion setup

```bash
python -m finrag.generalization download
python -m finrag.generalization prepare
python -m finrag.generalization publish
```

`download` retrieves and hash-checks the six pinned filings. `prepare` parses, chunks, audits source coverage and estimates uncached cost without calling a model. `publish` is explicit: it reruns preflight and uses the existing shared billing ledger and stop threshold, then publishes each document atomically. Previously published identical documents skip embedding even if the local vector cache was removed. Changed identity/hash metadata is rejected before paid embedding, and publication rechecks inside the transaction.

This expansion made71 document-embedding requests /660,147 provider tokens. Conservative list-price estimate: **$0.01320294**, excluding unknown free-credit/discount treatment; not an invoice. Pricing basis: [Voyage official pricing](https://docs.voyageai.com/docs/pricing), checked2026-10-28. No generated answers or labels were purchased for the new companies.

New local reading files are under `data/generalization/processed/`; the source manifest provides browser links to the originals. New questions can use one company, compare Google Cloud/AWS, or compare cash generation/capital spending, while retaining explicit year and accounting scope.

## Any new filing

The trusted CLI accepts metadata separately from HTML:

```bash
fr-rag-serve ingest --html path/to/report.html --metadata path/to/metadata.json
```

Metadata JSON shape:

```json
{
  "filing": {
    "id": "EXAMPLE_FY2025", "ticker": "EXAMPLE", "cik": 123,
    "fiscal_year": 2025, "form": "10-K", "accession": "SEC-accession",
    "period_end": "2025-12-31", "filed_at": "2026-02-01",
    "source_url": "https://www.sec.gov/Archives/edgar/data/..."
  },
  "company": {"ticker": "EXAMPLE", "cik": 123, "name": "Example Corporation", "aliases": ["Example"]}
}
```

File-size/document-chunk bounds apply. Publication includes metadata, blocks, vectors, lexical postings/statistics and a completion marker in one transaction. HNSW automatically receives inserted rows; IVF distribution/retraining maintenance remains an explicit operation. No unauthenticated ingestion endpoint is exposed over HTTP.
