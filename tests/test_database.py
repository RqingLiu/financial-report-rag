"""Opt-in actual pgvector integration; temporary index is removed after each test."""

import os
import uuid

import pytest
from psycopg.errors import ForeignKeyViolation

from finrag.config import settings
from finrag.models import Chunk
from finrag.repository import Repository

pytestmark = pytest.mark.skipif(
    os.getenv("FINRAG_INTEGRATION") != "1", reason="Set FINRAG_INTEGRATION=1 for local pgvector"
)


def test_atomic_publication_idempotency_and_scope():
    repo = Repository(settings().database_url.get_secret_value())
    ix = "integration_" + uuid.uuid4().hex
    chunk = Chunk(
        id=ix + ":0",
        document_id="NVDA_FY2024",
        index_id=ix,
        section="Item 8",
        text="fixture revenue",
        embedding_text="fixture revenue",
        tokens=2,
        spans=[],
        block_ids=[],
    )
    vector = [1.0] + [0.0] * 1023
    try:
        repo.save_index(ix, [chunk], [vector])
        repo.save_index(ix, [chunk], [vector])
        assert repo.index_count(ix) == 1
        with pytest.raises(ValueError):
            repo.save_index(ix, [], [])
        assert repo.index_count(ix) == 1
        assert len(repo.search(ix, ["NVDA_FY2024"], "2026-10-11", 5, vector=vector)) == 1
        assert repo.search(ix, ["MU_FY2024"], "2026-10-11", 5, vector=vector) == []
        assert repo.search(ix, [], "2026-10-11", 5, vector=vector) == []
        assert repo.search(ix, ["NVDA_FY2024"], "2023-01-01", 5, vector=vector) == []
        assert (
            repo.search(ix, ["NVDA_FY2024"], "2026-10-11", 5, query="fixture")[0].chunk.id
            == chunk.id
        )
        bad = chunk.model_copy(update={"id": ix + ":bad", "document_id": "nonexistent_filing"})
        with pytest.raises(ForeignKeyViolation):
            repo.save_index(ix, [bad], [vector])
        # FK failure rolls back the delete and the entire attempted publication.
        assert repo.index_count(ix) == 1
    finally:
        # A failed query may leave an implicit transaction aborted.
        repo.connection.rollback()
        with repo.connection.transaction():
            repo.connection.execute("DELETE FROM finrag.chunks WHERE index_id=%s", (ix,))
        repo.close()
