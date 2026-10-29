# Tasks

- [x] T01 Company/period/confirmed-context contract and regression tests, including generated schema/field-specific single repair.
- [x] T02 Long-table/source coverage and pre-embedding immutable preflight; all original2,759 chunk payloads reproduced exactly.
- [x] T03 Six Alphabet/Amazon filings FY2023–2025 published;16 documents/4,961 serving chunks,71 document-embedding requests/660,147 tokens/$0.01320294 list estimate.
- [x] T04 Standard project docs, standalone Git, ignored artifacts, staged secret scan and CI; user selected PUBLIC repository. Clean staged checkout76 passed/11 local corpus or DB skipped.
- [x] T05 Full validation, current diagram/Notion §5.10/§5.15 sync, public GitHub push and readback. Repository: https://github.com/RqingLiu/financial-report-rag ; default branch codex/correctness-release. Initial Linux CI succeeded: https://github.com/RqingLiu/financial-report-rag/actions/runs/40829556506 (76 passed/11 local corpus or DB skipped).

Local validation:87 passed with DB; frozen v2 --check passed; lint/dependency checks passed; original2,759 serving vectors and11,401 frozen chunks unchanged. One live cross-company/different-FY retrieval reached18 evidence items with generation disabled; first schema-missing-field failure retained and corrected rather than defaulting the field. Public receipts inreports/public; new-company answer quality/holdout remains pending user questions.
