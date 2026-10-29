"""Import offline GPT annotations, validate source spans, and build RAGAS datasets."""

import json
from collections import Counter
from pathlib import Path

from ragas.dataset_schema import SingleTurnSample
from ragas.testset.synthesizers.testset_schema import Testset, TestsetSample

from .files import atomic_json, digest, read_jsonl, write_jsonl
from .models import Evidence, Question
from .parse import load_blocks


def evidence_for(root, blocks, selector):
    document_id = selector["document_id"]
    block = next(b for b in blocks[document_id] if b.ordinal == selector["ordinal"])
    quote = selector.get("quote", block.text)
    local = block.text.find(quote)
    if local < 0:
        raise ValueError(f"Quote not found: {document_id}:{block.ordinal}")
    return Evidence(
        document_id=document_id,
        block_id=block.id,
        quote=quote,
        start=block.start + local,
        end=block.start + local + len(quote),
    )


def build_dataset(root: Path):
    blocks = load_blocks(root)
    specs_path = root / "data/evaluation/gpt_specs.json"
    specs = json.loads(specs_path.read_text())
    frozen = root / "data/evaluation/freeze_v1.json"
    if frozen.exists():
        prior = json.loads(frozen.read_text())
        if prior["spec_sha256"] != digest(specs_path.read_bytes()) or prior[
            "prompt_sha256"
        ] != digest((root / "prompts/golden_generation.md").read_bytes()):
            raise ValueError("Frozen annotations/prompt changed. Create a new dataset version.")
        return load_questions(root, "all")
    questions = []
    for spec in specs:
        groups = [
            [evidence_for(root, blocks, alt) for alt in group] for group in spec.pop("sources")
        ]
        questions.append(Question(**spec, evidence_groups=groups))
    validate_questions(questions, blocks)
    path = root / "data/evaluation/golden_v1.jsonl"
    write_jsonl(path, [q.model_dump() for q in questions])
    samples = [
        TestsetSample(
            eval_sample=SingleTurnSample(
                user_input=q.question,
                reference=q.reference,
                reference_contexts=[g[0].quote for g in q.evidence_groups],
                reference_context_ids=[f"{q.id}:g{i}" for i in range(len(q.evidence_groups))],
            ),
            synthesizer_name="offline_gpt_source_grounded_v1",
        )
        for q in questions
    ]
    testset = Testset(samples=samples)
    dataset = testset.to_evaluation_dataset()
    dataset.to_jsonl(str(root / "data/evaluation/ragas_reference.jsonl"))
    manifest = {
        "version": "golden-v1",
        "sha256": digest(path.read_bytes()),
        "spec_sha256": digest(specs_path.read_bytes()),
        "prompt_sha256": digest((root / "prompts/golden_generation.md").read_bytes()),
        "count": len(questions),
        "splits": dict(Counter(q.split for q in questions)),
        "categories": dict(Counter(q.category for q in questions)),
        "source_documents": sorted({d for q in questions for d in q.documents}),
        "review": "GPT source checked, human approval still pending",
        "generation": "Current GPT conversation; fixed specs imported into RAGAS Testset",
        "llm_api_used": False,
        "frozen_before_retrieval_tuning": True,
    }
    atomic_json(root / "data/evaluation/freeze_v1.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return questions


def validate_questions(questions, blocks):
    families = {}
    ids = set()
    for q in questions:
        if q.id in ids:
            raise ValueError(f"Duplicate question: {q.id}")
        ids.add(q.id)
        if q.family in families and families[q.family] != q.split:
            raise ValueError(f"Family leakage: {q.family}")
        families[q.family] = q.split
        if q.outcome == "answer" and not q.evidence_groups:
            raise ValueError(f"Answer without evidence: {q.id}")
        for group in q.evidence_groups:
            if not group:
                raise ValueError("Empty alternative group")
            for e in group:
                canonical = "\n\n".join(b.text for b in blocks[e.document_id])
                if canonical[e.start : e.end] != e.quote:
                    raise ValueError(f"Source span mismatch: {q.id}")
                if e.document_id not in q.documents:
                    raise ValueError(f"Unlisted source: {q.id}")


def load_questions(root: Path, split: str):
    path = root / "data/evaluation/golden_v1.jsonl"
    freeze = json.loads((root / "data/evaluation/freeze_v1.json").read_text())
    if digest(path.read_bytes()) != freeze["sha256"]:
        raise ValueError(
            "Frozen dataset changed; create a new version rather than tune the test set"
        )
    return [Question(**r) for r in read_jsonl(path) if split == "all" or r["split"] == split]
