from typing import Literal

from pydantic import BaseModel, Field, model_validator


class Filing(BaseModel):
    id: str
    ticker: str
    cik: int
    fiscal_year: int
    form: str
    accession: str
    period_end: str
    filed_at: str
    source_url: str
    download_url: str | None = None
    sha256: str | None = None
    amends_document_id: str | None = None


class Block(BaseModel):
    id: str
    document_id: str
    ordinal: int
    kind: Literal["text", "heading", "table", "image"]
    section: str
    text: str
    start: int
    end: int
    locator: dict
    structured: dict = Field(default_factory=dict)


class IndexConfig(BaseModel):
    name: str
    chunk_size: int = Field(ge=80, le=2000)
    overlap: int = Field(ge=0)
    strategy: Literal["recursive", "structure"] = "structure"
    contextual: bool = True
    tokenizer: str = "cl100k_base"
    parser_version: str = "sec-html-v2"
    embedding_model: str = "voyage-4-lite"
    dimension: int = 1024
    table_context: bool = False
    source_mapping_version: str = "offset-v3"

    @model_validator(mode="after")
    def valid_overlap(self):
        if self.overlap >= self.chunk_size:
            raise ValueError("Overlap must be smaller than chunk_size")
        return self


class Chunk(BaseModel):
    id: str
    document_id: str
    index_id: str
    section: str
    text: str
    embedding_text: str
    tokens: int
    spans: list[dict]
    block_ids: list[str]


class Evidence(BaseModel):
    document_id: str
    quote: str
    block_id: str
    start: int
    end: int


class Question(BaseModel):
    id: str
    question: str
    question_en: str
    language: str = "zh"
    category: str
    family: str
    split: Literal["dev", "test"]
    documents: list[str]
    reference: str
    evidence_groups: list[list[Evidence]]
    outcome: Literal["answer", "insufficient_evidence", "clarify"] = "answer"
    as_of: str = "2026-10-11"
    review_status: str = "gpt_source_checked_pending_human"
    derivation: dict = Field(default_factory=dict)


class Hit(BaseModel):
    chunk: Chunk
    score: float
    method: str
    expanded_spans: list[dict] = Field(default_factory=list)


class RetrievalConfig(BaseModel):
    name: str
    index_name: str
    method: Literal["dense", "fts", "hybrid", "tree"] = "dense"
    query_language: Literal["original", "english"] = "original"
    dense_k: int = 30
    fts_k: int = 30
    rrf_c: int = 60
    grouped: bool = False
    expand_parent: bool = False
    context_budget_tokens: int = 8000
    tree_sections: int = 3
    domain_query: bool = False
