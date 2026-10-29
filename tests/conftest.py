"""Keep clean-checkout unit tests distinct from optional source-corpus validation."""

import pytest

from finrag.config import ROOT


def pytest_collection_modifyitems(items):
    if not (ROOT / "data/processed/structure_512_table_context.chunks.jsonl").exists():
        marker = pytest.mark.skip(
            reason="Local SEC corpus absent; run documented download/parse/index setup"
        )
        for item in items:
            if item.get_closest_marker("corpus"):
                item.add_marker(marker)
