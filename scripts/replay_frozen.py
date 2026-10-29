"""Replay the already released test for reproducibility; this is NOT a new holdout."""

import json

from finrag.cli import resources
from finrag.config import ROOT
from finrag.evaluation import evaluate, retrieval_code_hash
from finrag.files import atomic_json
from finrag.models import RetrievalConfig

release = json.loads((ROOT / "reports/test_release.json").read_text())
selection = release["selection"]
if selection["retrieval_code_sha256"] != retrieval_code_hash(ROOT):
    raise ValueError(
        "Frozen retrieval implementation changed; do not silently replay a different system"
    )
config = RetrievalConfig(**selection["config"]).model_copy(
    update={"name": "replay_" + selection["config"]["name"]}
)
with resources() as retriever:
    result = evaluate(ROOT, retriever, config, "test")
same = result["at"] == release["result"]["at"]
atomic_json(
    ROOT / "reports/replay_validation.json",
    {
        "same_metrics": same,
        "original_at": release["result"]["at"],
        "replay_at": result["at"],
        "status": "Repeated regression evaluation on released labels, not new independent validation",
    },
)
if not same:
    raise RuntimeError("Frozen replay metrics changed")
print("Frozen replay matches; this is not a new test-set validation")
