# Contributing

Start with `docs/development.md` and the current increment in `specs/`. Keep serving and offline gold evaluation separate, preserve source/period provenance, and add regressions for meaningful boundary changes. Do not overwrite frozen labels or released experiment controls to improve a metric.

Run unit contracts and the staged publication scanner before a commit. Corpus/DB checks are separate opt-in validation; paid API calls need an explicit budget. Never include raw caches, credentials or complete local paid responses in pull requests.

For a retrieval change, report the input split, fixed budgets, candidate/Top80/context effects and regressions. For generation, distinguish structural validation from numeric and semantic correctness. No unmeasured throughput or accuracy claims.
