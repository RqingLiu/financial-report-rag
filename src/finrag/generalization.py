"""Prepare/audit a separate unseen-issuer manifest, then explicitly publish with billing caps.

Acquisition uses the existing SEC downloader; this module never generates evaluation labels
or answers. Raw/processed content stays local, while source metadata is shareable.
"""

import argparse
import json
from decimal import Decimal

from .acquire import download
from .chunk import config_id, make_chunks
from .config import ROOT, settings
from .embedding import VoyageEmbedder
from .files import atomic_json, digest, read_jsonl, write_jsonl
from .models import Filing
from .parse import parse_html
from .serving.ingestion import ingest_html, validate_source_coverage
from .serving.runtime import index_config, load_config, resources, shared_budget

SOURCES = ROOT / "data/generalization/sources.jsonl"
REPORT = ROOT / "reports/generalization/preparation.json"


def prepare():
    cfg = load_config()
    ix = index_config(cfg)
    summaries, unique = [], {}
    for row in read_jsonl(SOURCES):
        filing = Filing(**row)
        raw = (ROOT / "data/raw" / f"{filing.id}.html").read_bytes()
        if digest(raw) != filing.sha256:
            raise ValueError("generalization_source_checksum_mismatch")
        blocks = parse_html(raw, filing)
        chunks = make_chunks(blocks, filing, ix)
        validate_source_coverage(blocks, chunks)
        out = ROOT / "data/generalization/processed" / filing.id
        write_jsonl(out.with_suffix(".blocks.jsonl"), [b.model_dump() for b in blocks])
        write_jsonl(out.with_suffix(".chunks.jsonl"), [c.model_dump() for c in chunks])
        out.with_suffix(".txt").write_text("\n\n".join(b.text for b in blocks))
        for chunk in chunks:
            key = digest(
                json.dumps([ix.embedding_model, ix.dimension, "document", chunk.embedding_text])
            )
            if not (ROOT / "data/cache/embeddings" / (key + ".json")).exists():
                unique[key] = chunk.embedding_text
        summaries.append(
            {
                "document_id": filing.id,
                "filed_at": filing.filed_at,
                "source_url": filing.source_url,
                "source_sha256": filing.sha256,
                "raw_bytes": len(raw),
                "blocks": len(blocks),
                "chunks": len(chunks),
                "tables": sum(b.kind == "table" for b in blocks),
                "images_unverified": sum(b.kind == "image" for b in blocks),
                "proxy_tokens": sum(c.tokens for c in chunks),
                "max_chunk_proxy_tokens": max(c.tokens for c in chunks),
                "source_coverage": "passed for parsed non-image non-whitespace text",
            }
        )
    rate = Decimal(str(VoyageEmbedder.PRICE_PER_MILLION[ix.embedding_model]))
    # Each document is batched separately; conservatively allow framing per input.
    upper = sum(len(t.encode()) + 1024 for t in unique.values())
    snapshot = shared_budget(cfg).snapshot()
    ceiling = Decimal(upper) * rate / Decimal(1000000)
    allowed = Decimal(snapshot["known_peak_list_cost_usd"]) + Decimal(
        snapshot["unresolved_reserved_usd"]
    ) + ceiling < Decimal(str(cfg.stop_usd))
    result = {
        "documents": summaries,
        "index_id": config_id(ix),
        "source_manifest_sha256": digest(SOURCES.read_bytes()),
        "chunk_config": ix.model_dump(),
        "uncached_embedding_inputs": len(unique),
        "conservative_new_cost_ceiling_usd": str(ceiling),
        "budget_preflight": snapshot,
        "fits_current_stop": allowed,
        "new_api_calls": 0,
        "semantic_or_numeric_quality_evaluated": False,
    }
    atomic_json(REPORT, result)
    return result


def publish():
    checked = prepare()
    if not checked["fits_current_stop"]:
        raise ValueError("generalization_embedding_exceeds_shared_stop")
    cfg = load_config()
    companies = {
        r["ticker"]: r
        for r in json.loads((ROOT / "configs/generalization_companies.json").read_text())
    }
    results = []
    with resources(cfg) as (store, _llm, embedder, _ce):
        for ticker, aliases in json.loads(
            (ROOT / "configs/serving_company_aliases.json").read_text()
        ).items():
            store.register_aliases(ticker, aliases)
        for row in read_jsonl(SOURCES):
            filing = Filing(**row)
            result = ingest_html(
                ROOT / "data/raw" / f"{filing.id}.html",
                filing,
                store,
                embedder,
                companies[filing.ticker],
            )
            results.append(result)
            # Preserve completed publications before any later document failure.
            atomic_json(
                ROOT / "reports/generalization/publication.json",
                {
                    "namespace": cfg.namespace,
                    "results": results,
                    "embedding_events": embedder.events,
                    "budget_after": shared_budget(cfg).snapshot(),
                },
            )
            print(json.dumps(result), flush=True)
        store.connection.execute("ANALYZE " + store.table("chunks").as_string(store.connection))
    return {"published": len(results), "results": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["download", "prepare", "publish"])
    args = parser.parse_args()
    if args.command == "download":
        filings = [Filing(**r) for r in read_jsonl(SOURCES)]
        expected = {f.id: f.sha256 for f in filings}
        fetched = download(filings, ROOT / "data/raw", settings().sec_user_agent)
        if any(f.sha256 != expected[f.id] for f in fetched):
            raise ValueError("downloaded_source_differs_from_frozen_manifest")
        result = {"downloaded": len(fetched), "checksums": "passed"}
    else:
        result = prepare() if args.command == "prepare" else publish()
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
