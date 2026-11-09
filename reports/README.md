# Results

- [public/](public/README.md): compact sanitized experiment conditions, results and validation receipts for GitHub.
- `current/` (local, ignored): recent comparisons and compact saved answer/evidence records for human review.
- `test_release.json`: small frozen v1 provenance marker still hash-checked by the compound dataset validator; it does not configure serving.

The entire archive and retired research programs were removed by request. There is no restore command or hidden dependency on them. Historical scores remain records of the conditions under which they were measured; rerunning those retired experiments is not a current supported command. Current checks use `python scripts/verify_public_evidence.py`; current data/run/answer evaluation uses `python -m finrag.evaluation --help`.
