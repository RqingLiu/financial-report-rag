# Offline CLI Contract

`prepare --traces DIR --golden DIR --ids ID [ID ...] --out FILE` writes hashed packets. Inputs are read-only; IDs must be unique Golden v2 IDs. A historical attempt may be generated or not generated.

`score --packets FILE --verdicts FILE --out DIR` writes `scores.json` and `review.md`. Verdict IDs and hashes must match. Missing/duplicate item IDs, invalid status fields and unverifiable quotes fail validation before output. The CLI never imports the serving runtime or calls a provider. See [quickstart](../quickstart.md).

`export-judge --packets FILE --rubric FILE --out FILE` exports one message envelope per generated answer. Run the judge separately and collect the resulting objects in an array. `score` accepts `--rubric FILE --whole-verdicts FILE` together. The scorer validates the packet/rubric hashes, prompt version, five dimensions and their anchors, and material-error cap before producing a combined report.
