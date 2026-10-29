"""Isolated, immutable document publications, indexed BM25 and explicit pgvector modes."""

import json
import math
from collections import Counter

import psycopg
from psycopg import sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from ..chunk import config_id
from ..files import digest
from ..models import Chunk, Filing, Hit
from ..planning import Catalog
from .errors import ServingError
from .lexical import query_terms, replace_second_variants, terms


class LiveStore:
    def __init__(self, dsn, config, index_config):
        self.config, self.index_config = config, index_config
        self.index_id = config_id(index_config)
        # Namespace validated by ServingConfig; SQL identifiers still quoted.
        self.ns = sql.Identifier(config.namespace)
        self.connection = psycopg.connect(
            dsn, autocommit=True, row_factory=dict_row, connect_timeout=5
        )
        self.connection.execute(
            "SELECT set_config('statement_timeout',%s,false)", (str(config.sql_timeout_ms),)
        )

    def close(self):
        self.connection.close()

    def table(self, name):
        return sql.Identifier(self.config.namespace, name)

    def initialize(self):
        dim = self.index_config.dimension
        if not 1 <= dim <= 2000:
            raise ServingError("cosine_vector_dimension_limit")
        self.connection.execute("CREATE EXTENSION IF NOT EXISTS vector")
        statements = [
            "CREATE SCHEMA IF NOT EXISTS {ns}",
            """CREATE TABLE IF NOT EXISTS {ns}.documents (
              id text PRIMARY KEY, accession text NOT NULL UNIQUE, metadata jsonb NOT NULL,
              company jsonb NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS {ns}.publications (
              document_id text REFERENCES {ns}.documents(id), index_id text NOT NULL,
              signature text NOT NULL, chunks int NOT NULL, PRIMARY KEY(document_id,index_id))""",
            """CREATE TABLE IF NOT EXISTS {ns}.indexes (
              id text PRIMARY KEY, config jsonb NOT NULL, n bigint NOT NULL DEFAULT 0,
              length bigint NOT NULL DEFAULT 0)""",
            """CREATE TABLE IF NOT EXISTS {ns}.blocks (
              id text PRIMARY KEY, document_id text REFERENCES {ns}.documents(id),
              payload jsonb NOT NULL)""",
            """CREATE TABLE IF NOT EXISTS {ns}.chunks (
              id text PRIMARY KEY, document_id text REFERENCES {ns}.documents(id),
              index_id text REFERENCES {ns}.indexes(id), filed_at date NOT NULL,
              payload jsonb NOT NULL, embedding vector({dim}) NOT NULL,
              content text NOT NULL, dl int NOT NULL,
              search_tsv tsvector GENERATED ALWAYS AS (to_tsvector('english',content)) STORED)""",
            """CREATE TABLE IF NOT EXISTS {ns}.postings (
              chunk_id text REFERENCES {ns}.chunks(id), index_id text NOT NULL,
              term text NOT NULL, tf int NOT NULL, PRIMARY KEY(index_id,term,chunk_id))""",
            """CREATE TABLE IF NOT EXISTS {ns}.term_stats (
              index_id text NOT NULL, term text NOT NULL, df bigint NOT NULL,
              PRIMARY KEY(index_id,term))""",
            "CREATE INDEX IF NOT EXISTS chunks_scope ON {ns}.chunks(index_id,document_id,filed_at)",
            "CREATE INDEX IF NOT EXISTS chunks_fts ON {ns}.chunks USING gin(search_tsv)",
        ]
        with self.connection.transaction():
            for statement in statements:
                self.connection.execute(sql.SQL(statement).format(ns=self.ns, dim=sql.Literal(dim)))
            self.connection.execute(
                sql.SQL(
                    "INSERT INTO {}(id,config) VALUES (%s,%s) ON CONFLICT(id) DO NOTHING"
                ).format(self.table("indexes")),
                (self.index_id, Jsonb(self.index_config.model_dump())),
            )
            rows = self.connection.execute(
                sql.SQL("SELECT id FROM {} WHERE id<>%s").format(self.table("indexes")),
                (self.index_id,),
            ).fetchall()
            if rows:
                raise ServingError("one_index_per_namespace_use_new_namespace_for_version")

    def indexed_documents(self, index_id):
        return self.connection.execute(
            sql.SQL("SELECT document_id,chunks AS n FROM {} WHERE index_id=%s").format(
                self.table("publications")
            ),
            (index_id,),
        ).fetchall()

    def prepare_jobs(self, jobs, plan):
        return (
            replace_second_variants(jobs, plan)
            if self.config.coarse_policy == "hybrid_replace"
            else jobs
        )

    def catalog(self):
        rows = self.connection.execute(
            sql.SQL(
                "SELECT d.metadata,d.company FROM {} d JOIN {} p "
                "ON p.document_id=d.id WHERE p.index_id=%s ORDER BY d.id"
            ).format(self.table("documents"), self.table("publications")),
            (self.index_id,),
        ).fetchall()
        return Catalog([Filing(**r["metadata"]) for r in rows], [r["company"] for r in rows])

    def block_payloads(self, ids):
        return self.connection.execute(
            sql.SQL("SELECT payload - 'structured' AS payload FROM {} WHERE id=ANY(%s)").format(
                self.table("blocks")
            ),
            (ids,),
        ).fetchall()

    def publication(self, document_id):
        return self.connection.execute(
            sql.SQL("SELECT signature FROM {} WHERE document_id=%s AND index_id=%s").format(
                self.table("publications")
            ),
            (document_id, self.index_id),
        ).fetchone()

    def preflight(self, filing):
        row = self.connection.execute(
            sql.SQL(
                "SELECT d.metadata,p.chunks FROM {} d LEFT JOIN {} p "
                "ON p.document_id=d.id AND p.index_id=%s WHERE d.id=%s"
            ).format(self.table("documents"), self.table("publications")),
            (self.index_id, filing.id),
        ).fetchone()
        if row and row["metadata"] != filing.model_dump():
            raise ServingError("immutable_source_conflict")
        if row and row["chunks"] is not None:
            return {"document_id": filing.id, "status": "unchanged", "chunks": row["chunks"]}
        return None

    def register_aliases(self, ticker, aliases):
        if (
            not isinstance(ticker, str)
            or not isinstance(aliases, list)
            or len(aliases) > 32
            or any(not isinstance(a, str) or not 0 < len(a) <= 160 for a in aliases)
        ):
            raise ServingError("invalid_company_alias_metadata")
        # Only trusted local metadata maintenance; never a user-query or LLM operation.
        with self.connection.transaction():
            rows = self.connection.execute(
                sql.SQL("SELECT id,company FROM {} WHERE metadata->>'ticker'=%s FOR UPDATE").format(
                    self.table("documents")
                ),
                (ticker,),
            ).fetchall()
            for row in rows:
                company = dict(row["company"])
                company["aliases"] = sorted(set(company.get("aliases", [])) | set(aliases))
                self.connection.execute(
                    sql.SQL("UPDATE {} SET company=%s WHERE id=%s").format(self.table("documents")),
                    (Jsonb(company), row["id"]),
                )
        return {"ticker": ticker, "documents": len(rows)}

    def publish(self, filing, blocks, chunks, vectors, company=None):
        if not chunks or len(chunks) != len(vectors):
            raise ServingError("incomplete_document_vectors")
        if any(c.document_id != filing.id or c.index_id != self.index_id for c in chunks):
            raise ServingError("chunk_publication_identity_mismatch")
        if any(b.document_id != filing.id for b in blocks):
            raise ServingError("block_publication_identity_mismatch")
        bids = {b.id for b in blocks}
        if len(bids) != len(blocks) or len({c.id for c in chunks}) != len(chunks):
            raise ServingError("duplicate_source_or_chunk_identity")
        source = {b.id: b for b in blocks}
        if any(set(c.block_ids) - bids for c in chunks):
            raise ServingError("chunk_source_missing")
        for chunk in chunks:
            for span in chunk.spans:
                block = source.get(span.get("block_id"))
                if (
                    block is None
                    or not block.start <= span.get("start", -1) < span.get("end", -1) <= block.end
                ):
                    raise ServingError("source_span_out_of_bounds")
        if any(
            len(v) != self.index_config.dimension
            or not all(isinstance(x, (int, float)) and math.isfinite(x) for x in v)
            or not any(v)
            for v in vectors
        ):
            raise ServingError("invalid_publication_vector")
        signature = digest(
            json.dumps(
                [
                    filing.model_dump(),
                    self.index_config.model_dump(),
                    [b.model_dump() for b in sorted(blocks, key=lambda b: b.id)],
                    [c.model_dump() for c in sorted(chunks, key=lambda c: c.id)],
                ],
                sort_keys=True,
                ensure_ascii=False,
            )
        )
        company = company or {
            "ticker": filing.ticker,
            "cik": filing.cik,
            "name": filing.ticker,
            "aliases": [],
        }
        if company.get("ticker") != filing.ticker:
            raise ServingError("company_identity_mismatch")
        with self.connection.transaction():
            self.connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (self.config.namespace + ":" + filing.id,),
            )
            existing = self.publication(filing.id)
            if existing:
                if existing["signature"] != signature:
                    raise ServingError("immutable_publication_conflict_use_new_version")
                return {"document_id": filing.id, "status": "unchanged", "chunks": len(chunks)}
            prior = self.connection.execute(
                sql.SQL("SELECT metadata FROM {} WHERE id=%s").format(self.table("documents")),
                (filing.id,),
            ).fetchone()
            if prior and prior["metadata"] != filing.model_dump():
                raise ServingError("immutable_source_conflict")
            collisions = self.connection.execute(
                sql.SQL("SELECT id,payload FROM {} WHERE id=ANY(%s)").format(self.table("blocks")),
                (list(bids),),
            ).fetchall()
            if any(r["payload"] != source[r["id"]].model_dump() for r in collisions):
                raise ServingError("source_block_identity_collision")
            self.connection.execute(
                sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s) ON CONFLICT(id) DO NOTHING").format(
                    self.table("documents")
                ),
                (filing.id, filing.accession, Jsonb(filing.model_dump()), Jsonb(company)),
            )
            with self.connection.cursor() as cur:
                cur.executemany(
                    sql.SQL("INSERT INTO {} VALUES (%s,%s,%s) ON CONFLICT(id) DO NOTHING").format(
                        self.table("blocks")
                    ),
                    [(b.id, b.document_id, Jsonb(b.model_dump())) for b in blocks],
                )
                df, total_length = Counter(), 0
                for start in range(0, len(chunks), 64):
                    rows, postings = [], []
                    for c, v in zip(
                        chunks[start : start + 64], vectors[start : start + 64], strict=True
                    ):
                        counts = terms(c.embedding_text)
                        dl = sum(counts.values())
                        total_length += dl
                        df.update(counts.keys())
                        postings.extend(
                            (c.id, self.index_id, term, tf) for term, tf in counts.items()
                        )
                        rows.append(
                            (
                                c.id,
                                c.document_id,
                                self.index_id,
                                filing.filed_at,
                                Jsonb(c.model_dump()),
                                json.dumps(v),
                                c.embedding_text,
                                dl,
                            )
                        )
                    cur.executemany(
                        sql.SQL(
                            "INSERT INTO {}(id,document_id,index_id,filed_at,payload,"
                            "embedding,content,dl) VALUES (%s,%s,%s,%s,%s,%s::vector,%s,%s)"
                        ).format(self.table("chunks")),
                        rows,
                    )
                    cur.executemany(
                        sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s)").format(
                            self.table("postings")
                        ),
                        postings,
                    )
                cur.executemany(
                    sql.SQL(
                        "INSERT INTO {} AS t VALUES (%s,%s,%s) "
                        "ON CONFLICT(index_id,term) DO UPDATE SET df=t.df+excluded.df"
                    ).format(self.table("term_stats")),
                    [(self.index_id, t, n) for t, n in sorted(df.items())],
                )
            self.connection.execute(
                sql.SQL("UPDATE {} SET n=n+%s,length=length+%s WHERE id=%s").format(
                    self.table("indexes")
                ),
                (len(chunks), total_length, self.index_id),
            )
            self.connection.execute(
                sql.SQL("INSERT INTO {} VALUES (%s,%s,%s,%s)").format(self.table("publications")),
                (filing.id, self.index_id, signature, len(chunks)),
            )
        return {"document_id": filing.id, "status": "published", "chunks": len(chunks)}

    def ann_kind(self):
        rows = self.connection.execute(
            "SELECT am.amname FROM pg_index i "
            "JOIN pg_class t ON t.oid=i.indrelid JOIN pg_namespace n ON n.oid=t.relnamespace "
            "JOIN pg_class idx ON idx.oid=i.indexrelid JOIN pg_am am ON am.oid=idx.relam "
            "WHERE n.nspname=%s AND t.relname='chunks' AND i.indisvalid "
            "AND am.amname IN ('hnsw','ivfflat')",
            (self.config.namespace,),
        ).fetchall()
        return [r["amname"] for r in rows]

    def build_ann(self, kind="hnsw", lists=32):
        if kind not in ("hnsw", "ivfflat") or not 1 <= lists <= 10000:
            raise ServingError("invalid_ann_configuration")
        found = self.ann_kind()
        if found and found != [kind]:
            raise ServingError("different_ann_exists_use_separate_namespace_for_comparison")
        if kind == "ivfflat":
            row = self.connection.execute(
                sql.SQL("SELECT n FROM {} WHERE id=%s").format(self.table("indexes")),
                (self.index_id,),
            ).fetchone()
            if row is None or row["n"] < lists:
                raise ServingError("ivfflat_requires_training_rows_at_least_lists")
        name = sql.Identifier("chunks_" + kind)
        options = (
            sql.SQL("WITH (m=16,ef_construction=64)")
            if kind == "hnsw"
            else sql.SQL("WITH (lists={})").format(sql.Literal(lists))
        )
        # Explicit maintenance command only; never drop/block an existing serving index.
        self.connection.execute(
            sql.SQL(
                "CREATE INDEX CONCURRENTLY IF NOT EXISTS {} ON {} "
                "USING {}(embedding vector_cosine_ops) {}"
            ).format(name, self.table("chunks"), sql.SQL(kind), options)
        )
        self.connection.execute(sql.SQL("ANALYZE {}").format(self.table("chunks")))

    def search(
        self,
        index_id,
        document_ids,
        as_of,
        k,
        vector=None,
        query=None,
        sections=None,
        explain=False,
    ):
        if index_id != self.index_id or not 1 <= k <= 100:
            raise ServingError("invalid_search_index_or_k")
        if document_ids == []:
            return []
        clauses, params = [sql.SQL("c.index_id=%s"), sql.SQL("c.filed_at<=%s")], [index_id, as_of]
        if document_ids is not None:
            clauses.append(sql.SQL("c.document_id=ANY(%s)"))
            params.append(document_ids)
        if sections:
            clauses.append(sql.SQL("c.payload->>'section'=ANY(%s)"))
            params.append(sections)
        where = sql.SQL(" AND ").join(clauses)
        with self.connection.transaction():
            self.connection.execute(
                "SELECT set_config('statement_timeout',%s,true)", (str(self.config.sql_timeout_ms),)
            )
            if vector is not None:
                mode = self.config.vector_search
                if mode != "exact" and self.ann_kind() != [mode]:
                    raise ServingError("requested_ann_index_not_available")
                if (
                    len(vector) != self.index_config.dimension
                    or not any(vector)
                    or not all(math.isfinite(x) for x in vector)
                ):
                    raise ServingError("query_vector_invalid")
                if mode == "hnsw":
                    self.connection.execute(
                        "SELECT set_config('hnsw.ef_search',%s,true),"
                        "set_config('hnsw.iterative_scan','strict_order',true),"
                        "set_config('hnsw.max_scan_tuples',%s,true)",
                        (str(self.config.hnsw_ef_search), str(self.config.ann_max_scan)),
                    )
                if mode == "ivfflat":
                    self.connection.execute(
                        "SELECT set_config('ivfflat.probes',%s,true),"
                        "set_config('ivfflat.iterative_scan','relaxed_order',true),"
                        "set_config('ivfflat.max_probes',%s,true)",
                        (str(self.config.ivf_probes), str(self.config.ivf_max_probes)),
                    )
                if mode != "exact":
                    # Bias toward ANN; actual usage is checked by EXPLAIN benchmark, not assumed.
                    self.connection.execute("SET LOCAL enable_seqscan=off")
                    self.connection.execute("SET LOCAL enable_bitmapscan=off")
                    self.connection.execute("SET LOCAL enable_sort=off")
                ordering = (
                    sql.SQL("(c.embedding <=> %s::vector) + 0, c.id")
                    if mode == "exact"
                    else sql.SQL("score")
                )
                statement = sql.SQL(
                    "WITH nearest AS MATERIALIZED (SELECT c.id,c.payload, "
                    "c.embedding <=> %s::vector AS score FROM {} c WHERE {} "
                    "ORDER BY {} LIMIT %s) SELECT payload,score FROM nearest ORDER BY score+0,id"
                ).format(self.table("chunks"), where, ordering)
                bound = [json.dumps(vector), *params]
                if mode == "exact":
                    bound.append(json.dumps(vector))
                bound.append(k)
            elif self.config.lexical == "bm25":
                tokens = query_terms(query or "")
                if not tokens:
                    return []
                statement = sql.SQL("""SELECT c.payload,SUM(
                    ln(1+(i.n-s.df+0.5)/(s.df+0.5)) * (p.tf*2.2) /
                    (p.tf+1.2*(0.25+0.75*c.dl/NULLIF(i.length::float/i.n,0)))) AS score
                    FROM {p} p JOIN {c} c ON c.id=p.chunk_id
                    JOIN {s} s ON s.index_id=p.index_id AND s.term=p.term
                    JOIN {i} i ON i.id=p.index_id
                    WHERE p.index_id=%s AND p.term=ANY(%s) AND {where}
                    GROUP BY c.id ORDER BY score DESC,c.id LIMIT %s""").format(
                    p=self.table("postings"),
                    c=self.table("chunks"),
                    s=self.table("term_stats"),
                    i=self.table("indexes"),
                    where=where,
                )
                bound = [index_id, tokens, *params, k]
            elif query:
                statement = sql.SQL(
                    "SELECT c.payload,ts_rank_cd(c.search_tsv,q) AS score "
                    "FROM {} c,plainto_tsquery('english',%s) q WHERE {} AND c.search_tsv@@q "
                    "ORDER BY score DESC,c.id LIMIT %s"
                ).format(self.table("chunks"), where)
                bound = [query, *params, k]
            else:
                raise ServingError("query_or_vector_required")
            if explain:
                return self.connection.execute(
                    sql.SQL("EXPLAIN (ANALYZE,BUFFERS,FORMAT JSON) ") + statement, bound
                ).fetchone()["QUERY PLAN"]
            rows = self.connection.execute(statement, bound).fetchall()
        return [
            Hit(
                chunk=Chunk(**r["payload"]),
                score=float(r["score"]),
                method=self.config.vector_search if vector is not None else self.config.lexical,
            )
            for r in rows
        ]
