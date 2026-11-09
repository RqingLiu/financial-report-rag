# Implementation plan

1. Inspect active runtime imports, frozen input hashes, local artifact sizes, PostgreSQL tables and cross-schema dependencies.
2. Save original historical source/config snapshots. Separate offline legacy modules and update callers without changing algorithms or live retrieval settings.
3. Archive historical reports with checksums and preserve compact public receipts. Remove regenerable caches and obsolete drafts only after dependency checks.
4. Record schema metadata and active signatures; remove obsolete tables/schemas with explicit identifiers and transactional checks.
5. Correct dataset evaluation claims and document a paired raw-input evaluation protocol.
6. Write the separate course-informed single-agent migration proposal; defer implementation.
7. Run offline contracts, corpus integrity checks and selected live database tests without model calls. Record actual cleanup results and remaining limitations.
