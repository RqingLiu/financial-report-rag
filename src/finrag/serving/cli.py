"""Trusted local ingestion, index maintenance and real query CLI."""

import argparse
import json
from pathlib import Path

from ..config import ROOT, settings
from ..files import atomic_json
from ..models import Filing
from ..planning import Request
from ..repository import Repository
from .ingestion import bootstrap_legacy, ingest_html
from .runtime import load_config, query, resources, safe_failure


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "configs/serving.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    sub.add_parser("bootstrap")
    a = sub.add_parser("ann")
    a.add_argument("--kind", choices=["hnsw", "ivfflat"], default="hnsw")
    a.add_argument("--lists", type=int, default=32)
    a = sub.add_parser("ingest")
    a.add_argument("--html", type=Path, required=True)
    a.add_argument("--metadata", type=Path, required=True, help="JSON {filing:{...},company:{...}}")
    a = sub.add_parser("aliases", help="trusted metadata-only alias registration")
    a.add_argument("--metadata", type=Path, required=True, help="JSON {ticker:[aliases]}")
    a = sub.add_parser("query")
    a.add_argument("question")
    a.add_argument("--as-of", required=True)
    a.add_argument("--reading-context", default="")
    a.add_argument("--retrieve-only", action="store_true")
    a = sub.add_parser("serve")
    a.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    try:
        cfg = load_config(args.config)
        if args.command == "serve":
            import uvicorn

            from .api import create_app

            uvicorn.run(create_app(cfg), host="127.0.0.1", port=args.port, access_log=False)
            return
        if args.command == "query":
            data = query(
                Request(
                    question=args.question, as_of=args.as_of, reading_context=args.reading_context
                ),
                cfg,
                do_generate=not args.retrieve_only,
            )
            print(json.dumps(data, ensure_ascii=False, indent=2))
            if data["status"] == "error":
                raise SystemExit(1)
            return
        with resources(cfg, models=args.command == "ingest") as (store, _llm, embedder, _ce):
            if args.command in ("init", "bootstrap"):
                store.initialize()
            if args.command == "bootstrap":
                legacy = Repository(settings().database_url.get_secret_value())
                try:
                    legacy.connection.execute("SET default_transaction_read_only=on")
                    bootstrap_legacy(
                        store, legacy, json.loads((ROOT / "configs/companies.json").read_text())
                    )
                finally:
                    legacy.close()
            elif args.command == "ann":
                store.build_ann(args.kind, args.lists)
            elif args.command == "ingest":
                row = json.loads(args.metadata.read_text())
                result = ingest_html(
                    args.html, Filing(**row["filing"]), store, embedder, row.get("company")
                )
                print(json.dumps(result))
            elif args.command == "aliases":
                for ticker, aliases in json.loads(args.metadata.read_text()).items():
                    print(json.dumps(store.register_aliases(ticker, aliases), ensure_ascii=False))
        print(json.dumps({"status": "ok", "command": args.command, "namespace": cfg.namespace}))
    except Exception as exc:  # noqa: BLE001 — never print DB/provider bodies
        data = {"status": "error", "error": safe_failure(exc)}
        atomic_json(ROOT / "logs/serving_cli_error.json", data)
        print(json.dumps(data))
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
