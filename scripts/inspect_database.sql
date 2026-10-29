-- Financial Report RAG / pgAdmin Query Tool 只读查看指南
-- 连接 localhost:5432 / financial_report_rag，schema 为 finrag。
-- 可选中一个编号下的语句单独执行；不修改数据、不调用 Voyage。
-- 当前 index_id 是 2026-10-11 快照，重建配置后应核对 reports/index_*.json。

-- 1. 确认数据库、用户、端口和 pgvector 版本。
SELECT current_database() AS database, current_user AS username,
       inet_server_addr() AS server_address, inet_server_port() AS port,
       (SELECT extversion FROM pg_extension WHERE extname = 'vector') AS pgvector_version;

-- 2. 看 10 份申报文件、期间与来源。修订关系也可检查完整 metadata。
SELECT id, ticker, fiscal_year, form, period_end, filed_at,
       metadata->>'source_url' AS source_url,
       metadata->>'sha256' AS sha256, metadata->>'amends_document_id' AS amends_document_id,
       metadata
FROM finrag.documents
ORDER BY ticker, fiscal_year, form;

-- 3. 当前五组切块数量；这是逻辑配置，与 PostgreSQL 物理索引不同。
WITH current_indexes(name, index_id) AS (VALUES
  ('recursive_384_plain', '62e1b4ab7a66e485'),
  ('recursive_768_context', 'aa927cdb3e86e6e7'),
  ('structure_512_context', '58b3d982354d09d5'),
  ('structure_900_context', 'bfce8d1295812eb5'),
  ('structure_512_table_context', 'e7fc13a07ce9d588')
)
SELECT i.name, i.index_id, count(c.id) AS chunks
FROM current_indexes i
LEFT JOIN finrag.chunks c ON c.index_id = i.index_id
GROUP BY i.name, i.index_id
ORDER BY i.name;

-- 4. 查看库中所有配置版本；旧 Chunk 已清理，目前应只有当前五组。
-- 后续重建可能新增版本，不能把整表数量当作一次切块数量。
SELECT index_id, count(*) AS chunks
FROM finrag.chunks GROUP BY index_id ORDER BY index_id;

-- 5. 看当前默认组 NVDA FY2026 的实际切块。
-- content 是嵌入输入（包含前缀）；payload.text 是切块正文。
SELECT id, document_id, section,
       (payload->>'tokens')::int AS proxy_tokens,
       payload->>'text' AS chunk_text, content AS embedding_text,
       payload->'block_ids' AS source_blocks,
       payload->'spans' AS source_spans,
       vector_dims(embedding) AS dimensions
FROM finrag.chunks
WHERE index_id = 'e7fc13a07ce9d588' AND document_id = 'NVDA_FY2026'
ORDER BY id LIMIT 20;

-- 6. 看一块真实利润表：正文、嵌入输入、来源、向量数字开头和全文词项。
SELECT id, payload->>'text' AS chunk_text, content AS embedding_text,
       payload->'spans' AS source_spans,
       left(embedding::text, 160) AS vector_preview, search_tsv
FROM finrag.chunks
WHERE id = 'e7fc13a07ce9d588:NVDA_FY2026:c0152:735815ec';

-- 7. 沿 block_ids 回溯切分前的完整原文与表格结构。
-- 不只按 ordinal 关联，因为旧解析版本可能有同序号。
SELECT c.id AS chunk_id, b.id AS block_id, b.ordinal, b.kind,
       b.content AS original_block,
       b.payload->'locator' AS original_locator,
       b.payload->'structured' AS original_table_structure
FROM finrag.chunks c
CROSS JOIN LATERAL jsonb_array_elements_text(c.payload->'block_ids') AS refs(block_id)
JOIN finrag.blocks b ON b.id = refs.block_id
WHERE c.id = 'e7fc13a07ce9d588:NVDA_FY2026:c0152:735815ec'
ORDER BY b.ordinal;

-- 8. 同一完整利润表在五组配置下被切成什么样（每组可能多块）。
WITH current_indexes(name, index_id) AS (VALUES
  ('recursive_384_plain', '62e1b4ab7a66e485'),
  ('recursive_768_context', 'aa927cdb3e86e6e7'),
  ('structure_512_context', '58b3d982354d09d5'),
  ('structure_900_context', 'bfce8d1295812eb5'),
  ('structure_512_table_context', 'e7fc13a07ce9d588')
)
SELECT i.name, c.id, (c.payload->>'tokens')::int AS proxy_tokens,
       c.payload->>'text' AS chunk_text, c.content AS embedding_text,
       c.payload->'spans' AS source_spans
FROM current_indexes i
JOIN finrag.chunks c ON c.index_id = i.index_id
WHERE c.payload->'block_ids' ? 'NVDA_FY2026:b0706:ad547472aa'
ORDER BY i.name, c.id;

-- 9. PostgreSQL 的物理索引定义。当前是 B-tree/GIN，没有 HNSW/IVFFlat。
SELECT tablename, indexname, indexdef
FROM pg_indexes WHERE schemaname = 'finrag'
ORDER BY tablename, indexname;

-- 10. 实验记录；kind 区分 dev/test/replay，null 字段可查看完整 result。
SELECT id, kind, created_at,
       config->>'index_name' AS index_name, config->>'method' AS retrieval_method,
       result->>'split' AS split,
       result->'at'->'10'->>'macro_recall' AS macro_recall_at10,
       result->'at'->'10'->>'micro_recall' AS micro_recall_at10,
       result->'at'->'10'->>'complete_question_rate' AS complete_question_rate_at10,
       config, result
FROM finrag.runs ORDER BY created_at, id;

-- 11. 用已入库向量演示 pgvector 余弦距离（越小越相近）。
-- 使用上面利润表块的向量作为查询，第一条通常就是自己、距离为 0。
-- 这不是自然语言查询，不需要 Voyage；自然语言检索使用 fr-rag query。
WITH seed AS (
  SELECT embedding FROM finrag.chunks
  WHERE id = 'e7fc13a07ce9d588:NVDA_FY2026:c0152:735815ec'
)
SELECT c.id, c.embedding <=> seed.embedding AS cosine_distance,
       c.payload->>'text' AS chunk_text
FROM finrag.chunks c CROSS JOIN seed
WHERE c.index_id = 'e7fc13a07ce9d588' AND c.document_id = 'NVDA_FY2026'
ORDER BY cosine_distance, c.id LIMIT 5;
-- 表格不是只有向量：当前默认索引关联的原始表格与JSONB行列（排除未使用的历史Block）。
WITH current_blocks AS (
  SELECT DISTINCT jsonb_array_elements_text(payload->'block_ids') AS block_id
  FROM finrag.chunks
  WHERE index_id = 'e7fc13a07ce9d588'
)
SELECT b.id, b.document_id, b.payload->>'section' AS section, b.content AS rendered_table,
       b.payload->'structured'->'source_rows' AS original_cell_rows,
       b.payload->'structured'->'rows' AS expanded_grid,
       b.payload->'structured'->'header_rows' AS heuristic_headers,
       b.payload->'locator' AS original_html_locator
FROM finrag.blocks b
JOIN current_blocks c ON c.block_id = b.id
WHERE b.kind = 'table' AND b.document_id = 'NVDA_FY2026'
ORDER BY b.ordinal LIMIT 10;

