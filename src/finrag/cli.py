import argparse
import json
from contextlib import contextmanager

from .config import ROOT, settings


@contextmanager
def resources():
    from .embedding import VoyageEmbedder
    from .repository import Repository
    from .retrieval import Retriever

    s = settings()
    repo = Repository(s.database_url.get_secret_value())
    embedder = VoyageEmbedder(
        s.voyage_api_key.get_secret_value(),
        ROOT / "data/cache/embeddings",
        model=s.voyage_model,
        dimension=s.embedding_dimension,
        budget_usd=s.embedding_budget_usd,
    )
    try:
        yield Retriever(ROOT, repo, embedder)
    finally:
        embedder.close()
        repo.close()


def main():
    parser = argparse.ArgumentParser(description="SEC financial-report retrieval lab")
    subs = parser.add_subparsers(dest="command", required=True)
    for name in ["parse", "golden", "audit", "dev", "test", "packets"]:
        subs.add_parser(name)
    download = subs.add_parser("download")
    download.add_argument(
        "--refresh-manifest",
        action="store_true",
        help="Explicit SEC discovery refresh using configs/companies.json; retain history",
    )
    ingest = subs.add_parser("index")
    ingest.add_argument("name")
    query = subs.add_parser("query")
    query.add_argument("question")
    query.add_argument("--as-of", default="2026-10-11")
    query.add_argument("--output", default="reports/query_latest.json")
    args = parser.parse_args()
    if args.command == "download":
        from .acquire import acquire

        acquire(ROOT, settings().sec_user_agent, refresh_manifest=args.refresh_manifest)
    elif args.command == "parse":
        from .parse import parse_all

        parse_all(ROOT)
    elif args.command == "index":
        from .ingest import ingest

        ingest(ROOT, settings(), args.name)
    elif args.command == "golden":
        from .dataset import build_dataset

        print(f"Validated {len(build_dataset(ROOT))} frozen questions")
    elif args.command == "audit":
        from .audit import source_audit

        print(json.dumps(source_audit(ROOT), ensure_ascii=False, indent=2))
    elif args.command == "packets":
        from .service import export_annotation_packets

        print(export_annotation_packets(ROOT))
    elif args.command in ["dev", "test"]:
        from .evaluation import run_dev, run_test

        with resources() as retriever:
            if args.command == "dev":
                if (ROOT / "reports/test_release.json").exists():
                    raise ValueError(
                        "Test released; dev selection must not overwrite the audited configuration"
                    )
                result = run_dev(ROOT, retriever)
            else:
                result = run_test(ROOT, retriever)
            print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        from .files import atomic_json
        from .service import bundle

        with resources() as retriever:
            result = bundle(ROOT, retriever, args.question, args.as_of)
        out = ROOT / args.output
        atomic_json(out, result)
        if "answer_prompt" in result:
            out.with_suffix(".prompt.md").write_text(result["answer_prompt"])
        print(
            json.dumps(
                {
                    "output": str(out),
                    "policy": result["policy"],
                    "evidence_count": len(result["evidence"]),
                },
                ensure_ascii=False,
            )
        )


if __name__ == "__main__":
    main()
