# Design Decisions

- Use saved outputs rather than new model calls: they suffice to exercise the evaluator, and leave current serving and billing unchanged.
- Grade rubric items before considering aggregate scores. Keep numeric comparisons deterministic after explicit extraction and alignment. A generic reference similarity or citation-ID metric cannot establish financial correctness.
- Grade attached citation support separately from factual correctness. A correct claim can cite the wrong passage; a cited claim can still fail the gold rubric.
- Start with in-conversation judgments as versioned local artifacts. This is useful for manual calibration but does not measure judge repeatability or replace independent human review.
