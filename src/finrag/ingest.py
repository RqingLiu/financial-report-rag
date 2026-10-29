import json
from pathlib import Path

from .chunk import config_id, make_chunks
from .config import Settings
from .embedding import VoyageEmbedder
from .files import atomic_json, read_jsonl, write_jsonl
from .models import Filing, IndexConfig
from .parse import load_blocks
from .repository import Repository


def ingest(root: Path, settings: Settings, index_name: str):
    configs = [IndexConfig(**c) for c in json.loads((root / "configs/indexes.json").read_text())]
    config = next(c for c in configs if c.name == index_name)
    if (
        config.dimension != settings.embedding_dimension
        or config.embedding_model != settings.voyage_model
    ):
        raise ValueError("Settings and versioned index model/dimension differ")
    filings = [Filing(**r) for r in read_jsonl(root / "data/sources.jsonl")]
    blocks = load_blocks(root)
    chunks = [
        chunk for filing in filings for chunk in make_chunks(blocks[filing.id], filing, config)
    ]
    ix = config_id(config)
    atomic_json(
        root / f"reports/index_{config.name}.json",
        {
            "config": config.model_dump(),
            "id": ix,
            "chunks": len(chunks),
            "proxy_tokens": sum(c.tokens for c in chunks),
            "max_proxy_tokens": max(c.tokens for c in chunks),
            "tokenizer_note": "cl100k_base proxy; billed Voyage tokens come from API usage",
        },
    )
    write_jsonl(
        root / f"data/processed/{config.name}.chunks.jsonl", [c.model_dump() for c in chunks]
    )
    print(f"index {config.name}: {len(chunks)} chunks", flush=True)
    repository = Repository(settings.database_url.get_secret_value())
    embedder = VoyageEmbedder(
        settings.voyage_api_key.get_secret_value(),
        root / "data/cache/embeddings",
        model=config.embedding_model,
        dimension=config.dimension,
        budget_usd=settings.embedding_budget_usd,
    )
    try:
        repository.initialize()
        repository.save_sources(filings, blocks)
        vectors = embedder.embed([c.embedding_text for c in chunks])
        repository.save_index(ix, chunks, vectors)
        if repository.index_count(ix) != len(chunks):
            raise RuntimeError("Published index row count mismatch")
        print(f"published {config.name}: {len(chunks)} rows", flush=True)
    finally:
        embedder.close()
        repository.close()
