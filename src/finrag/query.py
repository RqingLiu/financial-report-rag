"""Small transparent bilingual glossary; no QA labels, model, or per-question rewrites."""

import re

# General financial-report concepts. A production query rewriter may replace this adapter.
GLOSSARY = [
    (
        r"合并收入|consolidated.*revenue",
        "consolidated statements income operations annual revenue net revenue",
    ),
    (
        r"经营现金流|operating.*cash",
        "consolidated statements cash flows net cash provided operating activities",
    ),
    (
        r"存货|库存|inventor",
        "inventories total inventories raw materials work in process finished goods",
    ),
    (r"毛利率|gross.*margin", "gross margin percentage cost revenue selling prices"),
    (
        r"研发费用|research.*development",
        "research development expenses consolidated statements operations",
    ),
    (
        r"供应链|supply.*chain",
        "manufacturing supply chain suppliers geographic concentration Asia Pacific",
    ),
    (
        r"制造模式|manufacturing model",
        "fabless manufacturing strategy wafer assembly test packaging suppliers",
    ),
    (
        r"客户集中|customer.*concentration",
        "customer concentration ten percent revenue direct customers",
    ),
    (r"保修|warrant", "product warranty costs limited warranty"),
    (
        r"不可取消|non.cancellable",
        "non-cancellable non-returnable purchase commitments obligations demand inventory",
    ),
    (
        r"剩余履约|performance obligations",
        "remaining performance obligations contract liabilities customer deposits",
    ),
    (r"开票|billing", "customer billing location geographic revenue shipments"),
    (r"制程|foundry|晶圆", "wafer foundry fabrication technology nodes suppliers"),
    (r"公共资源|utilities", "manufacturing utilities reliable uninterrupted power water outages"),
]


def domain_query(question):
    concepts = [terms for pattern, terms in GLOSSARY if re.search(pattern, question, re.IGNORECASE)]
    if concepts:
        # Preserve remaining source identifiers (e.g. HBM, IPR&D); metadata handles company/year.
        acronyms = re.findall(r"\b[A-Z][A-Z&]{2,}\b", question)
        return " ".join([*concepts, *acronyms])
    return question


def query_policy(question, filings, as_of):
    from .retrieval import ALIASES, resolve_scope

    if re.search(r"\bTSM\b|台积电|\bAAPL\b|苹果公司|\bMSFT\b", question, re.IGNORECASE):
        return {"outcome": "insufficient_evidence", "reason": "requested_company_not_in_corpus"}
    if not any(re.search(p, question, re.IGNORECASE) for p in ALIASES.values()):
        return {"outcome": "clarify", "reason": "specify_company_period_and_metric"}
    if re.search(
        r"私人|未公开|尚未公布|即时股价|盘中|精确收盘价|绝不会|保证.*盈利|private|undisclosed|unpublished|live.*price|exact.*price|cannot.*loss",
        question,
        re.IGNORECASE,
    ):
        return {
            "outcome": "insufficient_evidence",
            "reason": "not_supported_by_public_historical_filings",
        }
    if not resolve_scope(question, filings, as_of):
        return {"outcome": "insufficient_evidence", "reason": "requested_period_not_in_corpus"}
    return {"outcome": "retrieve", "reason": "scope_available; evidence still requires inspection"}
