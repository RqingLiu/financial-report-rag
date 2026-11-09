# Evaluation Data Model

- Packet: query ID, original request, cutoff/confirmations, status, answer, evidence, trace hash, rubric and numeric checks. A packet hash binds verdicts to the exact content. Reference answers and linked gold excerpts are judge-only inputs.
- Verdict: ID and packet hash; one judgment per mandatory fact, numeric ID, limit and material-error rule, plus optional extra observations. A fact verdict records its status, reason, exact answer excerpt and zero or more citation/source anchors. Numeric rows map a literal observation or identify missing, wrong scope or uncertainty.

Numeric rows may specify `direction: -1` only for an adjacent explicit decrease amount (for example, “decreased by 12” or “减少12”). The literal remains copied exactly. Level statements such as “decreased to 12” do not qualify. Omitted direction defaults to +1; all prior judgments therefore retain their arithmetic. Same-rubric comparisons must replay both arms with the same scorer after this extraction fix.
- Score: retains item explanations and deterministic comparisons, separate completeness/numeric/citation counts, provenance and a provisional overall outcome. Aggregate denominators include applicable required checks; non-generated attempts remain visible.
- Human correction: copy verdicts to a new local file, edit disputed rows, and rescore. Never change the saved answer, evidence or Golden v2 to fix a judge decision.
