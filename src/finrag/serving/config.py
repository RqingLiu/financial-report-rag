from typing import Literal

from pydantic import Field, model_validator

from ..planning import Contract, PipelineConfig


class ServingConfig(Contract):
    pipeline: PipelineConfig = Field(default_factory=lambda: PipelineConfig(fts_weight=0))
    namespace: str = Field(default="finrag_live", pattern=r"^finrag_live(?:_[a-z0-9]+)?$")
    vector_search: Literal["exact", "hnsw", "ivfflat"] = "hnsw"
    hnsw_ef_search: int = Field(default=100, ge=20, le=1000)
    ann_max_scan: int = Field(default=20000, ge=100, le=1000000)
    ivf_probes: int = Field(default=10, ge=1, le=1000)
    ivf_max_probes: int = Field(default=100, ge=1, le=10000)
    lexical: Literal["fts", "bm25"] = "bm25"
    coarse_policy: Literal["dense", "hybrid_replace"] = "dense"
    sql_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    regroup: bool = False
    reranker: Literal["none", "llm", "crossencoder"] = "llm"
    crossencoder_model: Literal["rerank-3-lite", "rerank-3"] = "rerank-3-lite"
    evidence_tokens: int = Field(default=8000, ge=1000, le=16000)
    full_prompt_tokens: int = Field(default=24000, ge=4000, le=64000)
    max_context_items: int = Field(default=30, ge=1, le=30)
    max_inflight: int = Field(default=2, ge=1, le=16)
    max_raw_bytes: int = Field(default=25000000, ge=10000, le=100000000)
    max_document_chunks: int = Field(default=10000, ge=1, le=100000)
    stop_usd: float = Field(default=1.60, gt=0, le=4.50)

    @model_validator(mode="after")
    def hybrid_contract(self):
        if self.coarse_policy == "hybrid_replace" and (
            self.pipeline.fts_weight or self.pipeline.collect_fts_for_ablation
        ):
            raise ValueError(
                "hybrid_replace requires base fts_weight=0; it replaces, not adds jobs"
            )
        return self
