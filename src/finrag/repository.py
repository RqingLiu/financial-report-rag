"""PostgreSQL-only persistence. Parameterized SQL, exact vectors, and native English FTS."""

import json

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .models import Block, Chunk, Filing, Hit

SCHEMA = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE SCHEMA IF NOT EXISTS finrag;
CREATE TABLE IF NOT EXISTS finrag.companies (
  ticker text PRIMARY KEY, cik bigint NOT NULL UNIQUE
);
CREATE TABLE IF NOT EXISTS finrag.documents (
  id text PRIMARY KEY, ticker text NOT NULL REFERENCES finrag.companies(ticker),
  fiscal_year int NOT NULL, form text NOT NULL, period_end date NOT NULL,
  filed_at date NOT NULL, accession text UNIQUE NOT NULL, metadata jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS finrag.blocks (
  id text PRIMARY KEY, document_id text NOT NULL REFERENCES finrag.documents(id),
  ordinal int NOT NULL, section text NOT NULL, kind text NOT NULL,
  content text NOT NULL, payload jsonb NOT NULL
);
CREATE TABLE IF NOT EXISTS finrag.chunks (
  id text PRIMARY KEY, document_id text NOT NULL REFERENCES finrag.documents(id),
  index_id text NOT NULL, section text NOT NULL, content text NOT NULL,
  payload jsonb NOT NULL, embedding vector(1024) NOT NULL,
  search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english', content)) STORED
);
CREATE INDEX IF NOT EXISTS chunks_filter ON finrag.chunks(index_id,document_id);
CREATE INDEX IF NOT EXISTS chunks_fts ON finrag.chunks USING gin(search_tsv);
CREATE INDEX IF NOT EXISTS documents_filters ON finrag.documents(ticker,fiscal_year,filed_at);
CREATE TABLE IF NOT EXISTS finrag.runs (
  id text PRIMARY KEY, created_at timestamptz NOT NULL DEFAULT now(),
  kind text NOT NULL, config jsonb NOT NULL, result jsonb NOT NULL
);
"""


class Repository:
    def __init__(self, dsn: str):
        # Reads must not open an implicit outer transaction that would swallow save_run commits.
        self.connection = psycopg.connect(dsn, row_factory=dict_row, autocommit=True)

    def close(self):
        self.connection.close()

    def initialize(self):
        with self.connection.transaction():
            self.connection.execute(SCHEMA)
            self.connection.execute(
                "ALTER TABLE finrag.blocks DROP CONSTRAINT IF EXISTS blocks_document_id_ordinal_key"
            )

    def save_sources(self, filings: list[Filing], blocks: dict[str, list[Block]]):
        with self.connection.transaction():
            for f in filings:
                self.connection.execute(
                    "INSERT INTO finrag.companies VALUES (%s,%s) ON CONFLICT DO NOTHING",
                    (f.ticker, f.cik),
                )
                self.connection.execute(
                    """INSERT INTO finrag.documents VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
                    ON CONFLICT(id) DO UPDATE SET metadata=excluded.metadata""",
                    (
                        f.id,
                        f.ticker,
                        f.fiscal_year,
                        f.form,
                        f.period_end,
                        f.filed_at,
                        f.accession,
                        Jsonb(f.model_dump()),
                    ),
                )
                with self.connection.cursor() as cursor:
                    cursor.executemany(
                        """INSERT INTO finrag.blocks VALUES (%s,%s,%s,%s,%s,%s,%s)
                        ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,
                        content=excluded.content""",
                        [
                            (
                                b.id,
                                b.document_id,
                                b.ordinal,
                                b.section,
                                b.kind,
                                b.text,
                                Jsonb(b.model_dump()),
                            )
                            for b in blocks[f.id]
                        ],
                    )

    def save_index(self, index_id: str, chunks: list[Chunk], vectors):
        if len(chunks) != len(vectors) or not chunks:
            raise ValueError("Cannot publish an empty/incomplete index")
        # Publish the entire version atomically; previous index versions remain usable.
        with self.connection.transaction():
            self.connection.execute("DELETE FROM finrag.chunks WHERE index_id=%s", (index_id,))
            with self.connection.cursor() as cursor:
                cursor.executemany(
                    "INSERT INTO finrag.chunks VALUES (%s,%s,%s,%s,%s,%s,%s::vector,DEFAULT)",
                    [
                        (
                            c.id,
                            c.document_id,
                            c.index_id,
                            c.section,
                            c.embedding_text,
                            Jsonb(c.model_dump()),
                            json.dumps(v),
                        )
                        for c, v in zip(chunks, vectors)
                    ],
                )

    def index_count(self, index_id):
        return self.connection.execute(
            "SELECT count(*) n FROM finrag.chunks WHERE index_id=%s", (index_id,)
        ).fetchone()["n"]

    def search(self, index_id, document_ids, as_of, k, vector=None, query=None, sections=None):
        if document_ids == []:
            return []
        clauses = ["c.index_id=%s", "d.filed_at<=%s"]
        params = [index_id, as_of]
        if document_ids:
            clauses.append("c.document_id=ANY(%s)")
            params.append(document_ids)
        if sections:
            clauses.append("c.section=ANY(%s)")
            params.append(sections)
        if vector is not None:
            score = "c.embedding <=> %s::vector"
            score_params = [json.dumps(vector)]
            ordering = "score ASC"
        elif query:
            # OR of normalized English lexemes: native ts_rank_cd, explicitly not BM25.
            lexemes = self.connection.execute(
                "SELECT tsvector_to_array(to_tsvector('english',%s)) terms", (query,)
            ).fetchone()["terms"]
            if not lexemes:
                return []
            tsquery = " | ".join("'" + t.replace("'", "''") + "'" for t in lexemes)
            score = "ts_rank_cd(c.search_tsv,to_tsquery('english',%s))"
            score_params = [tsquery]
            clauses.append("c.search_tsv @@ to_tsquery('english',%s)")
            params.append(tsquery)
            ordering = "score DESC"
        else:
            raise ValueError("Supply vector or query")
        sql = f"""SELECT c.payload,{score} AS score FROM finrag.chunks c
                  JOIN finrag.documents d ON c.document_id=d.id
                  WHERE {" AND ".join(clauses)} ORDER BY {ordering},c.id LIMIT %s"""
        rows = self.connection.execute(sql, [*score_params, *params, k]).fetchall()
        return [
            Hit(
                chunk=Chunk(**r["payload"]),
                score=float(r["score"]),
                method="dense" if vector is not None else "fts",
            )
            for r in rows
        ]

    def save_run(self, run_id, kind, config, result):
        with self.connection.transaction():
            self.connection.execute(
                """INSERT INTO finrag.runs(id,kind,config,result) VALUES (%s,%s,%s,%s)
                ON CONFLICT(id) DO UPDATE SET config=excluded.config,result=excluded.result""",
                (run_id, kind, Jsonb(config), Jsonb(result)),
            )
