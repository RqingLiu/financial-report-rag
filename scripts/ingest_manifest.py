"""Inspect a trusted pinned manifest; publish only when --publish is explicitly supplied."""

import argparse
import json
from pathlib import Path

from finrag.core.config import ROOT
from finrag.core.files import read_jsonl
from finrag.core.models import Filing
from finrag.ingestion.publish import ingest_html
from finrag.serving.runtime import load_config, resources, safe_failure


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--manifest", type=Path, required=True)
    p.add_argument("--companies", type=Path, required=True)
    p.add_argument("--config", type=Path, default=ROOT / "configs/serving.json")
    p.add_argument("--publish", action="store_true")
    args = p.parse_args()
    filings = [Filing(**r) for r in read_jsonl(args.manifest)]
    companies = {r["ticker"]: r for r in json.loads(args.companies.read_text())}
    paths = [(ROOT / "data/raw" / (f.id + ".html")).resolve() for f in filings]
    for filing, path in zip(filings, paths, strict=True):
        if not path.is_relative_to(ROOT / "data/raw") or not path.is_file():
            raise ValueError("manifest raw source missing or outside data/raw")
        if filing.ticker not in companies:
            raise ValueError("trusted company metadata missing")
    if not args.publish:
        print(json.dumps({"documents": [f.id for f in filings], "publish": False}))
        return
    try:
        with resources(load_config(args.config)) as (store, _llm, embedder, _ce):
            for filing, path in zip(filings, paths, strict=True):
                result = ingest_html(path, filing, store, embedder, companies[filing.ticker])
                print(json.dumps({"document": filing.id, **result}), flush=True)
    except Exception as exc:  # noqa: BLE001 — never print DB/provider credentials
        print(json.dumps({"status": "error", "error": safe_failure(exc)}))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
