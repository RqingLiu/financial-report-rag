# Quickstart

From the repository root, using the local historical planner traces:

```sh
.venv/bin/python -m finrag.evaluation prepare \
  --traces reports/planner/20261027T034153Z_198f65/traces \
  --golden data/evaluation/golden_v2 --ids U03 U06 U10 U12 U14 U16 \
  --out reports/answer_eval/pilot_v1/packets.json
.venv/bin/python -m finrag.evaluation score \
  --packets reports/answer_eval/pilot_v1/packets.json \
  --verdicts reports/answer_eval/pilot_v1/verdicts.json \
  --out reports/answer_eval/pilot_v1
```

Review `review.md`; duplicate `verdicts.json` before human corrections and write revised results into a separate output directory. The historical traces and verdicts are local artifacts, not part of a fresh clone. No database or credentials are needed for replay.

## Whole-answer scoring

Use the [versioned rubric](contracts/whole_answer_rubric.json) to export prompts for any judge. `judge_inputs.json` contains one messages envelope per generated answer. Use each envelope in a separate judge request or conversation and collect the returned objects as a JSON array. The included local pilot judgments were authored in conversation; the CLI does not call a model.

```sh
.venv/bin/python -m finrag.evaluation export-judge \
  --packets reports/answer_eval/pilot_v1/packets.json \
  --rubric specs/009-answer-evaluation/contracts/whole_answer_rubric.json \
  --out reports/answer_eval/pilot_v2/judge_inputs.json
.venv/bin/python -m finrag.evaluation score \
  --packets reports/answer_eval/pilot_v1/packets.json \
  --verdicts reports/answer_eval/pilot_v1/verdicts.json \
  --rubric specs/009-answer-evaluation/contracts/whole_answer_rubric.json \
  --whole-verdicts reports/answer_eval/pilot_v2/whole_verdicts.json \
  --out reports/answer_eval/pilot_v2
```

The new report contains five independent dimension scores, reasons, source/answer excerpts, and the earlier detailed diagnostics. A `null` score is pending review and excluded from that dimension's mean, with the scored count shown. No overall mean is computed.

## Six-question optimization replay

`python -m finrag.experiments.answer_optimization diagnose` compares saved candidate, Top80 and context spans against Golden v2. `prepare` reads only the saved runtime traces and reranked contexts. Both are offline; see `--help` for paths. The local run uses `reports/planner/20261027T034153Z_198f65/traces` and `reports/rerank/20261027T170703Z_9a25db/rerank80_full`. Its results are under ignored `reports/answer_eval/optimization_v1/`. Re-score `optimized/` or `prompt_only/` with the whole-answer command above using that arm's packets and verdicts. Scoring makes no API calls. The separate `run` command can incur generation charges and uses the shared stop limit.
## Targeted follow-up

Run only the authorized subset in a new local output directory:

```bash
python -m finrag.evaluation run \
  --out reports/answer_eval/<new-targeted-run> \
  --ids U01 U02 U04 U06 U11 U15 --calculation-tool
```

`--calculation-tool` activates both arithmetic preparation and its experimental precision prompt. Omit it for the default prompt with reliability fixes. An experiment-only `--stop-usd` requires explicit authorization; it does not edit serving configuration. Do not retry a saved failed attempt silently: preserve it and use a new named run. Paid generation receives only original requests, plans and actual evidence. Prepare/review offline judge packets after the attempt. Replay both comparison arms with the same scorer, particularly after the direction-word numeric extraction fix.
