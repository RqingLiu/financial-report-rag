"""Trusted local ingestion, index maintenance and real query CLI."""

import argparse
import json
import signal
from pathlib import Path
from threading import Event

from finrag.agent.planner import Request
from finrag.core.config import ROOT, settings
from finrag.core.files import atomic_json
from finrag.core.models import Filing
from finrag.ingestion.publish import ingest_html
from finrag.serving.runtime import load_config, query, resources, safe_failure


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", type=Path, default=ROOT / "configs/serving.json")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("init")
    a = sub.add_parser("download", help="fetch pinned SEC source manifests/HTML")
    a.add_argument("--refresh-manifest", action="store_true")
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

            from finrag.serving.api import create_app

            uvicorn.run(create_app(cfg), host="127.0.0.1", port=args.port, access_log=False)
            return
        if args.command == "query":
            cancel = Event()
            previous = signal.signal(signal.SIGINT, lambda *_: cancel.set())
            try:
                data = query(
                    Request(
                        question=args.question,
                        as_of=args.as_of,
                        reading_context=args.reading_context,
                    ),
                    cfg,
                    do_generate=not args.retrieve_only,
                    cancelled=cancel.is_set,
                )
            finally:
                signal.signal(signal.SIGINT, previous)
            print(json.dumps(data, ensure_ascii=False, indent=2))
            if data["status"] == "error":
                raise SystemExit(1)
            return
        if args.command == "download":
            from finrag.ingestion.acquire import acquire

            acquire(ROOT, settings().sec_user_agent, refresh_manifest=args.refresh_manifest)
            return
        with resources(cfg, models=args.command == "ingest") as (store, _llm, embedder, _ce):
            if args.command == "init":
                store.initialize()
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
