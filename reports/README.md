# Evaluation receipts

The public repository includes compact, sanitized evidence under [public/](public/README.md). Full local traces, paid responses, HTML views, machine-specific audits and compressed archives are ignored.

Read [evaluation methodology](../docs/evaluation.md) for dataset/metric boundaries and [development history](../docs/history.md) for failed/selected experiments. Raw run directories used by legacy replay scripts must be rebuilt or restored locally; they are not runtime dependencies of the serving CLI.

The small original `test_release.json` is retained for frozen dataset hash validation. It is historical v1 evidence, not an unseen quality test for the current service.
