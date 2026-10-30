# Public bilingual project guide and main delivery

## Goal and scope
Make the repository self-contained for an instructor's technical deep dive. Publish the completed007 UI/code-map work with documentation matching main. User authorized public main delivery; do not add a personal-contribution breakdown.

## Requirements
- D01: English README and Chinese README with matching facts, language links, architecture/demo/result summaries, setup, scope limits and navigable details.
- D02: Integrate the project story into both READMEs: research problem, end-to-end flow, design tradeoffs, measured failures/improvements and next validation priorities. Remove the standalone deep-dive document and its links; retain detailed experiments and code maps as supporting references. No ownership breakdown or invented performance claims.
- D03: Public compact experiment artifacts are extracted from actual local results with input hashes/run identifiers, configs, dataset/metric/conditions and per-question metrics when available. Distinguish historical v1,20-query development, exact-search replay, real ANN checks and synthetic expansion. Do not silently promote the best experiment to serving defaults.
- D04: Publish no credentials, raw provider logs, private paths, personal Notion content or large generated corpus. Include sanitized screenshots/case excerpts and reproducibility instructions; do not depend on private Notion access for the main explanation.
- D05: Preserve frozen evaluation and historical receipts. Validate current code/tests, links, artifact consistency and staged publication scan; update the existing PR, wait for CI, merge main without force or history rewriting, and verify remote main.

## Non-goals
No paid rerun, model/retrieval behavior change, autonomous Agent, public deployment or new accuracy/load acceptance. Static demo is a saved observation, not a live benchmark.
