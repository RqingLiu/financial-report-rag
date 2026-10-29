"""Metadata-driven query planning. No fixed issuer universe or financial synonym glossary."""

import json
import re
from datetime import date
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

from .chunk import token_count
from .files import atomic_json, digest, read_jsonl
from .models import Filing
from .planning_scope import report_year_constraints


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConfirmedCompany(Contract):
    ticker: str = Field(min_length=1, max_length=32)
    report_years: list[int] = Field(min_length=1, max_length=20)


class ConfirmedContext(Contract):
    ticker: str | None = None
    report_document_id: str | None = None
    report_years: list[int] | None = Field(default=None, min_length=1, max_length=20)
    companies: list[ConfirmedCompany] | None = Field(default=None, min_length=1, max_length=12)
    excluded_tickers: list[str] = Field(default_factory=list, max_length=12)
    as_of: date | None = None
    date_precision: Literal["day"] | None = None
    exclude_later_filings: bool = True


class Request(Contract):
    question: str = Field(min_length=1, max_length=16000)
    reading_context: str = Field(default="", max_length=24000)
    confirmed_context: dict | None = None
    as_of: date

    @field_validator("question")
    @classmethod
    def nonblank_question(cls, value):
        if not value.strip():
            raise ValueError("question_must_not_be_blank")
        return value

    @field_validator("confirmed_context")
    @classmethod
    def typed_confirmation(cls, value):
        if value is None:
            return None
        return ConfirmedContext(**value).model_dump(mode="json", exclude_unset=True)


class CompanyScope(Contract):
    ticker: str
    source_mention: str = Field(min_length=1)
    report_years: list[int] = Field(min_length=1, max_length=20)


class Need(Contract):
    id: str
    description: str = Field(min_length=1, max_length=700)
    source_quote: str = Field(min_length=1, max_length=700)


class Task(Contract):
    id: str
    need_ids: list[str] = Field(min_length=1, max_length=16)
    tickers: list[str] = Field(min_length=1, max_length=12)
    dense_queries: list[str] = Field(min_length=1, max_length=2)
    keywords: list[str] = Field(min_length=1, max_length=10)
    depends_on: list[str] = Field(default_factory=list)
    route: Literal["retrieve"] = "retrieve"


class Plan(Contract):
    action: Literal["retrieve", "clarify", "insufficient_evidence"]
    as_of: date
    companies: list[CompanyScope] = Field(max_length=12)
    excluded_tickers: list[str] = Field(default_factory=list)
    period_basis: Literal["report_fy", "fact_fy", "mixed"]
    needs: list[Need] = Field(max_length=16)
    tasks: list[Task] = Field(max_length=4)
    clarification_questions: list[str] = Field(default_factory=list)
    unavailable_entities: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    period_interpretation: str


class PipelineConfig(Contract):
    index_name: str = "structure_512_table_context"
    max_tasks: int = Field(default=4, ge=1, le=4)
    max_variants: int = Field(default=2, ge=1, le=2)
    dense_k: int = Field(default=20, ge=1, le=50)
    fts_k: int = Field(default=20, ge=1, le=50)
    max_groups_per_task: int = Field(default=12, ge=1, le=30)
    max_search_calls: int = Field(default=192, ge=1, le=256)
    max_unique_candidates: int = Field(default=512, ge=1, le=1024)
    max_catalog_tokens: int = Field(default=6000, ge=500, le=20000)
    context_candidate_limit: int = Field(default=80, ge=10, le=512)
    context_k: int = Field(default=10, ge=1, le=30)
    context_tokens: int = Field(default=8000, ge=1000, le=16000)
    source_cache_blocks: int = Field(default=1000, ge=1, le=10000)
    source_cache_characters: int = Field(default=2000000, ge=1000, le=20000000)
    max_table_tokens: int = Field(default=1200, ge=0, le=3000)
    rrf_c: int = Field(default=60, ge=1)
    dense_weight: float = Field(default=1.0, ge=0, le=2)
    fts_weight: float = Field(default=0.35, ge=0, le=2)
    collect_fts_for_ablation: bool = False
    context_strategy: Literal["rank", "coverage", "need_budget"] = "coverage"
    need_cost_exponent: float = Field(default=0.5, ge=0, le=1)
    expand_tables: bool = True
    task_coverage_bonus: float = Field(default=0.12, ge=0, le=1)
    period_coverage_bonus: float = Field(default=0.035, ge=0, le=1)
    coverage_rank_depth: int = Field(default=5, ge=1, le=30)
    overlap_threshold: float = Field(default=0.90, ge=0, le=1)


class PlanRejected(ValueError):
    pass


class Catalog:
    def __init__(self, filings, companies=None):
        self.filings = list(filings)
        self.by_id = {f.id: f for f in self.filings}
        self.by_company_year = {}
        for f in self.filings:
            self.by_company_year.setdefault((f.ticker, f.fiscal_year), []).append(f)
        registered = {c["ticker"].upper(): c for c in (companies or [])}
        self.companies = {}
        for f in self.filings:
            row = registered.get(f.ticker, {})
            self.companies.setdefault(
                f.ticker,
                {
                    "ticker": f.ticker,
                    "cik": f.cik,
                    "name": row.get("name", f.ticker),
                    "aliases": row.get("aliases", []),
                    "reports": [],
                },
            )["reports"].append(
                {
                    "id": f.id,
                    "report_fy": f.fiscal_year,
                    "period_end": f.period_end,
                    "filed_at": f.filed_at,
                    "form": f.form,
                    "amends": f.amends_document_id,
                }
            )

    @classmethod
    def load(cls, root):
        filings = [Filing(**r) for r in read_jsonl(root / "data/sources.jsonl")]
        registry_path = root / "configs/companies.json"
        registry = (
            read_jsonl(registry_path)
            if registry_path.suffix == ".jsonl"
            else (json.loads(registry_path.read_text()) if registry_path.exists() else [])
        )
        known = {r["ticker"]: r for r in registry}
        # SEC names can be discovered from metadata without adding aliases to Python code.
        for f in filings:
            p = root / "data/raw" / f"{f.ticker}_submissions.json"
            if p.exists() and f.ticker not in known:
                data = json.loads(p.read_text())
                known[f.ticker] = {"ticker": f.ticker, "name": data.get("name", f.ticker)}
        return cls(filings, list(known.values()))

    def metadata(self, as_of):
        return [
            {
                **{k: v for k, v in row.items() if k != "reports"},
                "reports": [f for f in row["reports"] if f["filed_at"] <= str(as_of)],
            }
            for row in self.companies.values()
        ]

    def mentions(self, text):
        found = set()
        for ticker, c in self.companies.items():
            for alias in [ticker, c["name"], *c["aliases"]]:
                if not alias:
                    continue
                boundary = rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])"
                if re.search(boundary, text, re.IGNORECASE):
                    found.add(ticker)
        return found

    def explicit_exclusions(self, text):
        excluded = set()
        for ticker, c in self.companies.items():
            for alias in [ticker, c["name"], *c["aliases"]]:
                if re.search(
                    r"(?:不要|排除|不含|不包括|excluding\s+|exclude\s+|except\s+)\s*"
                    + re.escape(alias)
                    + r"(?![A-Za-z0-9_])",
                    text,
                    re.IGNORECASE,
                ):
                    excluded.add(ticker)
        return excluded

    def documents(self, scope, as_of):
        base = [
            f
            for year in scope.report_years
            for f in self.by_company_year.get((scope.ticker, year), [])
            if f.filed_at <= str(as_of)
        ]
        return sorted(f.id for f in base)


PLANNER_VERSION = "catalog-queryplan-v3-scope-schema"
PLANNER_PROMPT = """你是SEC财报检索规划器，输出json；不回答财务问题，不编造数字或SQL。
根据原问、用户阅读背景、已确认约束和语料catalog规划。catalog仅说明可用报告，不代表用户要查全部公司。
公司通过名称/别名/上下文映射至catalog ticker；中文与英文公司标识连写也有效，不要求空格。
不在catalog的公司放unavailable_entities，不替换成别家公司。需要比较且一方缺材料，可检索已知部分并说明限制。
公司、报告财年、实际事实期间、截止日、否定/排除条件不可被改写丢失。excluded_tickers仅列用户明确排除的公司，不能把所有未请求的catalog公司放进去。source_mention和source_quote必须逐字来自原问或阅读背景或确认上下文。
已确认的公司/报告/as_of必须保留。report_years决定查哪些报告，不等于事实财年；较新报告可以含更早的比较数据。
source_mention必须是catalog中该公司的名称/别名且逐字来自输入，或是用户已确认的report_document_id；不得借用别家名称或普通词充当实体依据。未登记/无法唯一映射的名称先澄清，不依据常识扩展公司范围。显式跨公司不同FY分别保留；confirmed_context.companies逐公司固定report_years。
阅读背景中明确'三个财年'且catalog恰有三份可用年度报告，可按该覆盖范围列明各公司报告财年；不能把库内最新当外部最新。
'目前市场份额'等缺时间/市场口径时先回答可支持的产品关系，limitations列出其余需澄清/外部材料的部分，不整题拒绝。
无公司/期间/指标且无法从已确认上下文恢复时action=clarify，列具体问题。不因英文ticker连写中文而澄清。
截止日、公司范围等执行约束放入对应字段，不创建无取证任务的need；每个need必须被tasks.need_ids覆盖。所有可回答/需要披露缺项的信息需求分配need ID，确保原问所有子问都有need，不能只保留第一个指标。
最多4个retrieve任务，每任务最多2条英文dense_queries（独立完整描述取证目标）；中文概念翻译而不是固定同义词替换。
每任务keywords是3–8个具体英文检索词组，如指标/产品/风险术语，不要公司名/财年/Item编号/目录等元数据词来匹配正文。
相关信息需求可合为一个任务，need_ids映射所有需求；跨年比较任务通常包含同一公司的全部已选财年。
只支持retrieve，depends_on通常为空；计算/季度/预测工具未开放，limitations说明缺能力，但仍检索支持事实/公式的原文。
参数之外不得增加字段。action非retrieve时tasks为空；retrieve时companies/needs/tasks均非空。
JSON结构示例（值仅作格式示意，不能当本题实体）：
{"action":"retrieve","as_of":"2020-01-01","companies":[{"ticker":"EXAMPLE","source_mention":"Example","report_years":[2019]}],
"excluded_tickers":[],"period_basis":"mixed","needs":[{"id":"n1","description":"Revenue trend and disclosed growth drivers","source_quote":"收入变化"}],
"tasks":[{"id":"t1","need_ids":["n1"],"tickers":["EXAMPLE"],"dense_queries":["Revenue and year-over-year growth, management explanation"],
"keywords":["revenue","growth drivers"],"depends_on":[],"route":"retrieve"}],
"clarification_questions":[],"unavailable_entities":[],"limitations":[],"period_interpretation":"User-provided report FY; actual value periods must be checked in tables"}
"""


def validate_plan(plan, request, catalog, config):
    text = (
        request.question
        + "\n"
        + request.reading_context
        + "\n"
        + json.dumps(request.confirmed_context or {}, ensure_ascii=False)
    )
    if plan.as_of > request.as_of or (plan.as_of < request.as_of and str(plan.as_of) not in text):
        raise PlanRejected("cutoff_changed_without_user_evidence")
    selected = {s.ticker for s in plan.companies}
    excluded = set(plan.excluded_tickers)
    confirmed = request.confirmed_context or {}
    confirmed_companies = {
        r["ticker"]: set(r["report_years"]) for r in confirmed.get("companies", [])
    }
    if len(confirmed_companies) != len(confirmed.get("companies", [])):
        raise PlanRejected("duplicate_confirmed_company")
    if confirmed.get("ticker"):
        confirmed_companies.setdefault(
            confirmed["ticker"], set(confirmed.get("report_years") or [])
        )
    confirmed_exclusions = set(confirmed.get("excluded_tickers", []))
    if excluded - catalog.mentions(text) - confirmed_exclusions:
        raise PlanRejected("unsupported_exclusion")
    if len(selected) != len(plan.companies) or selected & excluded:
        raise PlanRejected("duplicate_or_excluded_company")
    if selected - set(catalog.companies) and plan.action == "retrieve":
        raise PlanRejected("unknown_company_selected")
    if catalog.explicit_exclusions(text) - excluded or selected & catalog.explicit_exclusions(text):
        raise PlanRejected("explicit_exclusion_lost")
    # Non-retrieval outcomes can explicitly explain unresolved companies.
    if catalog.mentions(text) - selected - excluded and plan.action == "retrieve":
        raise PlanRejected("explicit_company_lost")
    if plan.action == "retrieve" and selected - catalog.mentions(text) - set(confirmed_companies):
        document = catalog.by_id.get(confirmed.get("report_document_id"))
        if document is None or selected - catalog.mentions(text) != {document.ticker}:
            raise PlanRejected("unrequested_company_selected")
    if confirmed_companies and plan.action == "retrieve" and selected != set(confirmed_companies):
        raise PlanRejected("confirmed_company_scope_changed")
    if confirmed_exclusions - excluded or selected & confirmed_exclusions:
        raise PlanRejected("confirmed_exclusion_lost")
    for scope in plan.companies:
        if scope.source_mention not in text:
            raise PlanRejected("company_mention_not_in_request")
        if plan.action == "retrieve":
            matched = catalog.mentions(scope.source_mention)
            document = catalog.by_id.get(confirmed.get("report_document_id"))
            opaque_confirmation = (
                document is not None
                and document.ticker == scope.ticker
                and scope.source_mention == document.id
            )
            if matched != {scope.ticker} and not opaque_confirmation:
                raise PlanRejected("company_mention_alias_mismatch")
            fixed_years = confirmed_companies.get(scope.ticker)
            if fixed_years and set(scope.report_years) != fixed_years:
                raise PlanRejected("confirmed_report_year_changed")
        available = {
            f.fiscal_year
            for f in catalog.filings
            if f.ticker == scope.ticker and f.filed_at <= str(plan.as_of)
        }
        if set(scope.report_years) - available and plan.action == "retrieve":
            raise PlanRejected("report_year_not_available")
    if confirmed.get("as_of") and str(plan.as_of) != confirmed["as_of"]:
        raise PlanRejected("confirmed_cutoff_changed")
    if confirmed.get("report_document_id"):
        filing = next((f for f in catalog.filings if f.id == confirmed["report_document_id"]), None)
        if filing is None or selected != {filing.ticker}:
            raise PlanRejected("confirmed_report_scope_changed")
        if next(s for s in plan.companies if s.ticker == filing.ticker).report_years != [
            filing.fiscal_year
        ]:
            raise PlanRejected("confirmed_report_year_changed")
    report_syntax = re.search(
        r"年报|年度报告|\b(?:10-K|annual\s+reports?|reports?)\b",
        request.question + "\n" + request.reading_context,
        re.IGNORECASE,
    )
    if plan.action == "retrieve" and (plan.period_basis != "fact_fy" or report_syntax):
        try:
            required, excluded_years = report_year_constraints(
                request.question + "\n" + request.reading_context, catalog.companies
            )
        except ValueError as exc:
            raise PlanRejected(str(exc)) from None
        for scope in plan.companies:
            if set(scope.report_years) & excluded_years.get(scope.ticker, set()):
                raise PlanRejected("explicit_report_year_exclusion_lost")
            wanted = required.get(scope.ticker, set()) - excluded_years.get(scope.ticker, set())
            if not wanted.issubset(set(scope.report_years)):
                raise PlanRejected("explicit_report_year_lost")
    need_ids, task_ids = {n.id for n in plan.needs}, {t.id for t in plan.tasks}
    if len(need_ids) != len(plan.needs) or len(task_ids) != len(plan.tasks):
        raise PlanRejected("duplicate_need_or_task")
    for need in plan.needs:
        if need.source_quote not in text:
            raise PlanRejected("need_quote_not_in_request")
    covered = set()
    for task in plan.tasks:
        if set(task.tickers) - selected or set(task.need_ids) - need_ids:
            raise PlanRejected("invalid_task_scope_or_needs")
        if set(task.depends_on) - task_ids or task.id in task.depends_on:
            raise PlanRejected("invalid_dependencies")
        if len(task.dense_queries) > config.max_variants:
            raise PlanRejected("variant_limit")
        if any(not q.strip() or len(q) > 1200 for q in task.dense_queries + task.keywords):
            raise PlanRejected("query_size_limit")
        covered.update(task.need_ids)

    def visit(key, seen):
        if key in seen:
            raise PlanRejected("dependency_cycle")
        for dep in next(t for t in plan.tasks if t.id == key).depends_on:
            visit(dep, seen | {key})

    for key in task_ids:
        visit(key, set())
    if len(plan.tasks) > config.max_tasks:
        raise PlanRejected("task_limit")
    if plan.action == "retrieve" and (
        not selected or not need_ids or not task_ids or covered != need_ids
    ):
        raise PlanRejected("incomplete_retrieval_plan")
    if plan.action == "retrieve" and {t for task in plan.tasks for t in task.tickers} != selected:
        raise PlanRejected("selected_company_without_task")
    if plan.action != "retrieve" and plan.tasks:
        raise PlanRejected("nonretrieval_tasks")
    if plan.action == "clarify" and not plan.clarification_questions:
        raise PlanRejected("missing_clarification_question")
    return plan


def plan_request(request, catalog, config, llm, cache_dir):
    metadata = catalog.metadata(request.as_of)
    encoded = json.dumps(metadata, ensure_ascii=False)
    if token_count(encoded) > config.max_catalog_tokens:
        # Large catalogs: use explicit metadata aliases to narrow prompt input only.
        # Full catalog still validates exclusions/unknown entities and selected reports.
        text = (
            request.question
            + "\n"
            + request.reading_context
            + "\n"
            + json.dumps(request.confirmed_context or {}, ensure_ascii=False)
        )
        mentioned = catalog.mentions(text)
        metadata = [r for r in metadata if r["ticker"] in mentioned]
        if (
            not metadata
            or token_count(json.dumps(metadata, ensure_ascii=False)) > config.max_catalog_tokens
        ):
            raise PlanRejected("catalog_capacity_exceeded_narrow_company_scope")
    messages = [
        {"role": "system", "content": PLANNER_PROMPT},
        {
            "role": "user",
            "content": json.dumps(
                {
                    "request": request.model_dump(mode="json"),
                    "catalog": metadata,
                    "response_contract": Plan.model_json_schema(),
                },
                ensure_ascii=False,
            ),
        },
    ]
    key = digest(json.dumps([PLANNER_VERSION, messages], ensure_ascii=False))
    path = Path(cache_dir) / f"{key}.json"
    cached = path.exists()
    if cached:
        result = json.loads(path.read_text())
        plan = Plan.model_validate_json(result["answer"])
        validate_plan(plan, request, catalog, config)
        return plan, {
            "cached": True,
            "cache_key": key,
            "api_result": result,
            "messages": messages,
            "prompt_version": PLANNER_VERSION,
            "repairs": 0,
        }
    repairs = 0
    for attempt in range(2):
        result = llm.generate(messages, max_tokens=4096, json_object=True, purpose="query_planning")
        if result["finish_reason"] != "stop":
            raise PlanRejected("planner_response_truncated")
        try:
            try:
                plan = Plan.model_validate_json(result["answer"])
            except ValidationError as exc:
                # Field locations/types help the single repair; never echo input values.
                fields = [
                    {"field": ".".join(map(str, e["loc"])), "type": e["type"]}
                    for e in exc.errors(include_input=False, include_url=False)[:12]
                ]
                raise PlanRejected("planner_schema_invalid: " + json.dumps(fields)) from None
            validate_plan(plan, request, catalog, config)
        except PlanRejected as exc:
            if attempt == 1:
                raise
            repairs += 1
            messages = [
                *messages,
                {"role": "assistant", "content": result["answer"]},
                {
                    "role": "user",
                    "content": "上一份json未通过业务校验："
                    + str(exc)
                    + "。只修复该计划，不更改原问/已确认约束；每个need必须映射到任务；排除字段只放明确排除的公司。返回完整json。",
                },
            ]
            continue
        atomic_json(path, result)
        return plan, {
            "cached": False,
            "cache_key": key,
            "api_result": result,
            "messages": messages,
            "prompt_version": PLANNER_VERSION,
            "repairs": repairs,
        }
    raise PlanRejected("planner_validation_failed")
