# Configuration

- `serving.json`: one live default, LangGraph policy and namespace `finrag_live_ready`.
- `indexes.json`: only the selected `structure_512_table_context` recipe; removing unused recipes does not change existing vectors.
- `companies.json`: original issuer metadata used by download / manifest publication.
- `generalization_companies.json`: Alphabet/Amazon metadata used by the new-issuer helper.
- `serving_company_aliases.json`: trusted alias-registration input.
- `best.json`: frozen historical selection bytes referenced by the reviewed 20-question validator. It is a provenance hash anchor, not the service configuration.

Retired candidate profiles, synthetic benchmarks and old sweep configuration were deleted. Commands and side effects are listed in the main README.
