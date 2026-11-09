-- Current production schema; no obsolete research tables are required.
-- Run read-only in pgAdmin Query Tool connected to financial_report_rag.
BEGIN READ ONLY;
SELECT current_database(), current_schema();
SELECT schemaname, relname, n_live_tup AS estimated_rows,
       pg_size_pretty(pg_total_relation_size(relid)) AS total_size
FROM pg_stat_user_tables
ORDER BY schemaname, relname;

SELECT id, metadata->>'ticker' AS ticker, metadata->>'fiscal_year' AS report_fy,
       metadata->>'filed_at' AS filed_at, metadata->>'source_url' AS source_url
FROM finrag_live_ready.documents ORDER BY id;

SELECT id, config, n, length FROM finrag_live_ready.indexes;
SELECT document_id, index_id, chunks, signature
FROM finrag_live_ready.publications ORDER BY document_id;
SELECT index_id, count(*) AS actual_chunks
FROM finrag_live_ready.chunks GROUP BY index_id;

-- Text, original span coordinates, table metadata and embedding dimension.
SELECT id, document_id, index_id,
       payload->>'section' AS section, payload->>'tokens' AS proxy_tokens,
       payload->'spans' AS original_spans, left(content, 1000) AS preview,
       vector_dims(embedding) AS vector_dimensions
FROM finrag_live_ready.chunks ORDER BY document_id,id LIMIT 20;
SELECT id, document_id, payload
FROM finrag_live_ready.blocks ORDER BY document_id,id LIMIT 10;
SELECT indexname,indexdef FROM pg_indexes
WHERE schemaname='finrag_live_ready' ORDER BY indexname;
COMMIT;
