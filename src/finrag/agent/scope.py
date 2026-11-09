"""Catalog-bound alias spans and conservative explicit report-year constraints.

This recognizes explicit FY syntax, not arbitrary financial-period semantics. Ambiguities
still need clarification/held-out tests; it never invents issuer aliases from model output.
"""

import re
from collections import defaultdict

YEAR = re.compile(
    r"(?<![A-Za-z0-9_])FY\s*(20\d{2})(?:\s*[-–—~至到]\s*(?:FY\s*)?(20\d{2}))?", re.IGNORECASE
)
EXCLUDE = re.compile(
    r"(?:不要|排除|不含|不包括|excluding\s+|exclude\s+|except\s+)\s*$", re.IGNORECASE
)


def alias_spans(text, companies):
    spans = []
    for ticker, row in companies.items():
        for alias in {ticker, row["name"], *row["aliases"]}:
            if alias:
                pattern = rf"(?<![A-Za-z0-9_]){re.escape(alias)}(?![A-Za-z0-9_])"
                spans.extend(
                    (m.start(), m.end(), ticker) for m in re.finditer(pattern, text, re.IGNORECASE)
                )
    return sorted(set(spans))


def report_year_constraints(text, companies):
    """Associate explicit company/FY clauses, including shared-prefix/postfix years.

    Process request/background separately from confirmed JSON so serializer key order
    never creates an accidental company-year association. Confirmed scopes are typed.
    """
    required, excluded = defaultdict(set), defaultdict(set)
    for clause in re.split(r"[\n;；。!?！？]", text):
        aliases = alias_spans(clause, companies)
        years = list(YEAR.finditer(clause))
        if not aliases or not years:
            continue
        issuers = {a[2] for a in aliases}
        all_before = max(m.end() for m in years) <= min(a[0] for a in aliases)
        all_after = min(m.start() for m in years) >= max(a[1] for a in aliases)
        for m in years:
            first, last = int(m[1]), int(m[2] or m[1])
            if last < first or last - first > 19:
                raise ValueError("explicit_fy_range_invalid")
            values = set(range(first, last + 1))
            targets = issuers
            if len(issuers) > 1 and not (all_before or all_after):
                attached = set()
                for start, end, ticker in aliases:
                    gap = clause[end : m.start()] if end <= m.start() else clause[m.end() : start]
                    if re.fullmatch(r"\s*(?:的|在|for|in)?\s*", gap, re.IGNORECASE):
                        attached.add(ticker)
                if len(attached) == 1:
                    targets = attached
                    dest = excluded if EXCLUDE.search(clause[: m.start()]) else required
                    for ticker in targets:
                        dest[ticker].update(values)
                    continue
                distances = {
                    ticker: min(
                        max(start - m.end(), m.start() - end, 0)
                        for start, end, t in aliases
                        if t == ticker
                    )
                    for ticker in issuers
                }
                nearest = min(distances.values())
                targets = {t for t, distance in distances.items() if distance == nearest}
                if len(targets) != 1:
                    raise ValueError("explicit_fy_company_ambiguous")
            dest = excluded if EXCLUDE.search(clause[: m.start()]) else required
            for ticker in targets:
                dest[ticker].update(values)
    return dict(required), dict(excluded)
