"""Evidence-anchored Decimal arithmetic. Source/metric selection remains a model judgment."""

import ast
import json
import re
from decimal import Decimal, DecimalException, localcontext

from pydantic import Field, ValidationError

from finrag.agent.planner import Contract, PlanRejected
from finrag.answering.generation import ANSWER_PROMPT, answer_messages
from finrag.ingestion.chunk import token_count

CALCULATION_VERSION = "evidence-decimal-v2-compact-signed"
CALCULATION_PROMPT = """Prepare arithmetic for the original question using ONLY supplied evidence.
Do not answer the question or use outside knowledge. Identify the requested comparisons, periods,
ratios and accounting adjustments that can actually be computed. Prefer exact statement values,
not rounded MD&A values. Keep amounts, ratios and percentage points separate; compare compatible
metrics/units and distinguish actual fact periods from report FY. Use period-specific denominators.
Do not call an unexplained residual demand improvement or a causal contribution.
Return JSON: {"values":[{"id":"v1","value":"123","citation":"E1",
"quote":"exact source excerpt containing that value","unit":"USD_million",
"label":"company, actual fact FY, metric and accounting scope"}],
"calculations":[{"id":"c1","label":"requested result with company/period/scope",
"expression":"v1-v2","unit":"USD_million"}]}.
IDs must be lowercase alphanumeric identifiers beginning with a letter. Use at most 32 values
and 32 calculations. Keep labels under 70 characters; quote only the minimal literal excerpt,
usually the number itself, not whole tables. Reuse operands. Prioritize requested results so
the complete JSON fits 4096 output tokens. Expressions support only + - * / and parentheses, verified value IDs or
earlier calculation IDs. Only constants 0, 1, 2 and 100 are allowed (zero, growth, average, percent).
Other quantities including fiscal-day counts must come from evidence. Source quotes must be
literal excerpts; preserve value signs, units and year columns. Do not invent missing inputs.
Parentheses in a source numeric cell mean a negative signed input. Preserve that sign in value;
if a metric needs a positive expense magnitude, negate that operand in the expression. Do not
drop the negative sign just because the label is a cash outflow or cost.
For a cross-period accounting-effect bridge, first compute the same NET effect in EACH period,
including new charges and releases. Compare those period-specific effects; do not substitute
one period's benefit for the change in the net effect. Amount bridges and rate bridges differ.
Turnover days use average balance / corresponding period flow * verified fiscal days, not
flow / balance. Do not assume 365 days or invent a fiscal-day operand when evidence lacks it.
For monetary growth contributions, compute the requested absolute differences and reconcile
components against the reported consolidated change, including reconciling categories.
Use exact values through intermediate calculations, then let the final answer round them.
Select the arithmetic needed to answer the question, not every possible number in the documents.
If nothing is computable, return empty arrays. Do not include reference answers or external facts.
"""


class Operand(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    value: str = Field(max_length=64)
    citation: str = Field(pattern=r"^E\d+$")
    quote: str = Field(min_length=1, max_length=2000)
    unit: str = Field(min_length=1, max_length=64)
    label: str = Field(min_length=1, max_length=180)


class Calculation(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9_]{0,31}$")
    label: str = Field(min_length=1, max_length=180)
    expression: str = Field(min_length=1, max_length=256)
    unit: str = Field(min_length=1, max_length=64)


class Worksheet(Contract):
    values: list[Operand] = Field(max_length=32)
    calculations: list[Calculation] = Field(max_length=32)


def numeric(text):
    text = text.strip().replace(",", "").replace("−", "-").replace(" ", "")
    if text.startswith("(") and text.endswith(")"):
        text = "-" + text[1:-1]
    value = Decimal(text)
    if not value.is_finite() or abs(value) > Decimal("1e15"):
        raise ValueError("invalid_numeric_operand")
    return value


def evaluate(expression, values):
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 100:
        raise ValueError("expression_too_complex")

    def visit(node):
        if isinstance(node, ast.Name):
            return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) in (int, float):
            value = Decimal(ast.get_source_segment(expression, node))
            if value not in (0, 1, 2, 100):
                raise ValueError("ungrounded_constant")
            return value
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            value = visit(node.operand)
            return -value if isinstance(node.op, ast.USub) else value
        if isinstance(node, ast.BinOp):
            a, b = visit(node.left), visit(node.right)
            if isinstance(node.op, ast.Add):
                return a + b
            if isinstance(node.op, ast.Sub):
                return a - b
            if isinstance(node.op, ast.Mult):
                return a * b
            if isinstance(node.op, ast.Div):
                return a / b
        raise ValueError("unsupported_expression")

    with localcontext() as context:
        context.prec = 38
        value = visit(tree.body)
        if not value.is_finite() or abs(value) > Decimal("1e18"):
            raise ValueError("calculation_out_of_bounds")
        return value


def execute_worksheet(worksheet, evidence):
    sources = {e["citation"]: e["text"] for e in evidence}
    values, citations, accepted, results, rejected = {}, {}, [], [], []
    ids = [v.id for v in worksheet.values] + [c.id for c in worksheet.calculations]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate_worksheet_id")
    for item in worksheet.values:
        try:
            norm = lambda s: re.sub(r"[\s|]+", " ", s).strip()
            if norm(item.quote) not in norm(sources[item.citation]):
                raise ValueError("source_quote_not_found")
            value = numeric(item.value)
            literals = re.findall(
                r"\(\s*\d[\d,]*(?:\.\d+)?\s*\)|[-−+]?\d[\d,]*(?:\.\d+)?", item.quote
            )
            if value not in [numeric(s) for s in literals]:
                raise ValueError("operand_value_not_in_quote")
            values[item.id], citations[item.id] = value, {item.citation}
            accepted.append(item.model_dump())
        except (KeyError, ValueError, DecimalException) as exc:
            rejected.append(
                {
                    "id": item.id,
                    "error": str(exc) if isinstance(exc, ValueError) else type(exc).__name__,
                }
            )
    for item in worksheet.calculations:
        try:
            value = evaluate(item.expression, values)
            names = {
                n.id
                for n in ast.walk(ast.parse(item.expression, mode="eval"))
                if isinstance(n, ast.Name)
            }
            if not names:
                raise ValueError("calculation_requires_evidence_operand")
            refs = set().union(*(citations[n] for n in names))
            values[item.id], citations[item.id] = value, refs
            results.append(
                {**item.model_dump(), "value": format(value, "f"), "citations": sorted(refs)}
            )
        except (KeyError, ValueError, SyntaxError, DecimalException) as exc:
            rejected.append({"id": item.id, "error": type(exc).__name__})
    return {
        "version": CALCULATION_VERSION,
        "values": accepted,
        "results": results,
        "rejected": rejected,
        "verification": "literal anchors and arithmetic only; metric, units and period selection require review",
    }


def prepare_calculations(data, llm, *, full_prompt_tokens=24000, answer_prompt=ANSWER_PROMPT):
    messages = answer_messages(data, system_prompt=CALCULATION_PROMPT)
    if token_count(json.dumps(messages, ensure_ascii=False)) > full_prompt_tokens:
        raise PlanRejected("calculation_prompt_limit")
    response = llm.generate(
        messages, max_tokens=4096, json_object=True, purpose="calculation_prepare"
    )
    try:
        if response["finish_reason"] != "stop":
            raise ValueError("worksheet_truncated")
        result = execute_worksheet(
            Worksheet.model_validate_json(response["answer"]), data["runtime_evidence"]
        )
    except (ValidationError, ValueError) as exc:
        result = {
            "version": CALCULATION_VERSION,
            "values": [],
            "results": [],
            "rejected": [{"error": type(exc).__name__}],
            "verification": "worksheet rejected; no verified arithmetic",
        }
    # Preserve the complete audit artifact; pass only bounded results to answer generation.
    compact = {k: result[k] for k in ("results", "verification")}
    while (
        compact["results"]
        and token_count(
            json.dumps(
                answer_messages(
                    {**data, "calculation_results": compact}, system_prompt=answer_prompt
                ),
                ensure_ascii=False,
            )
        )
        > full_prompt_tokens
    ):
        compact["results"] = compact["results"][:-1]
    return compact, {
        **result,
        "response": response,
        "messages": messages,
        "included_results": len(compact["results"]),
    }
