"""Build/check the user-authorized 20-question DEV annotation release, offline only.

No retrieval, indexing, database, model API, or production financial tool is invoked.
Existing releases are immutable: --check revalidates inputs and every output byte.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import Counter
from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path

from lxml import html
from finrag.models import Question
from ragas.dataset_schema import EvaluationDataset, SingleTurnSample

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'data/evaluation/golden_v2'
REF = re.compile(r'\[((?:NVDA|AMD|MU)\d{2}\.\d+)\]')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha(content):
    return hashlib.sha256(content).hexdigest()


def json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, indent=2) + '\n').encode()


def jsonl_bytes(rows):
    return ''.join(json.dumps(x, ensure_ascii=False) + '\n' for x in rows).encode()


def read_jsonl(path):
    return [json.loads(x) for x in path.read_text().splitlines() if x.strip()]


class Sources:
    def __init__(self):
        self.filings = {x['id']: x for x in read_jsonl(ROOT / 'data/sources.jsonl')}
        self.blocks, self.canonical, self.doms, self.catalog = {}, {}, {}, {}

    def resolve(self, alias):
        if alias in self.catalog:
            return self.catalog[alias]
        match = re.fullmatch(r'(NVDA|MU|AMD)(\d{2})\.(\d+)', alias)
        require(match is not None, f'Invalid alias: {alias}')
        doc = f'{match[1]}_FY20{match[2]}'
        filing = self.filings[doc]
        if doc not in self.blocks:
            raw = (ROOT / f'data/raw/{doc}.html').read_bytes()
            require(sha(raw) == filing['sha256'], f'Raw file changed: {doc}')
            self.blocks[doc] = read_jsonl(ROOT / f'data/processed/{doc}.blocks.jsonl')
            canonical = '\n\n'.join(b['text'] for b in self.blocks[doc])
            require(canonical == (ROOT / f'data/processed/{doc}.txt').read_text(),
                    f'Canonical text changed: {doc}')
            self.canonical[doc] = canonical
            tree = html.fromstring(raw)
            for node in list(tree.iter()):
                style = re.sub(r'\s+', '', node.get('style', '').lower())
                if str(node.tag).lower() in ('script', 'style', 'noscript', 'ix:header', 'ix:hidden') or 'display:none' in style or 'visibility:hidden' in style:
                    node.drop_tree()
            self.doms[doc] = tree
        block = self.blocks[doc][int(match[3])]
        require(block['ordinal'] == int(match[3]), f'Ordinal mismatch: {alias}')
        require(self.canonical[doc][block['start']:block['end']] == block['text'],
                f'Span mismatch: {alias}')
        xp = re.sub(r'/([\w.-]+:[\w.-]+)', r"/*[name()='\1']", block['locator']['xpath'])
        nodes = self.doms[doc].xpath(xp)
        require(len(nodes) == 1, f'DOM locator mismatch: {alias}')
        normalize = lambda x: ' '.join(x.replace('\xa0', ' ').split())
        text = normalize(' '.join(nodes[0].itertext()))
        cursor = 0
        for part in block['text'].replace('\n', '|').split('|'):
            part = normalize(part)
            if not part:
                continue
            at = text.find(part, cursor)
            require(at >= 0, f'Raw DOM does not contain quote: {alias}: {part[:80]}')
            cursor = at + len(part)
        entry = {'id': alias, 'document_id': doc, 'accession': filing['accession'],
                 'report_fiscal_year': filing['fiscal_year'], 'period_end': filing['period_end'],
                 'filed_at': filing['filed_at'], 'source_url': filing['source_url'],
                 'source_sha256': filing['sha256'], 'block_id': block['id'],
                 'locator': block['locator'], 'start': block['start'], 'end': block['end'],
                 'quote': block['text'], 'raw_dom_verified': True,
                 'canonical_span_verified': True}
        self.catalog[alias] = entry
        return entry

    def row(self, alias, prefix, occurrence=0):
        entry = self.resolve(alias)
        matches = [x for x in entry['quote'].splitlines() if x.startswith(prefix)]
        require(0 <= occurrence < len(matches), f'Missing table row: {alias}: {prefix}')
        return matches[occurrence]

    def evidence(self, selector, as_of):
        entry = self.resolve(selector['alias'])
        require(entry['filed_at'] <= as_of, f'Future evidence leak: {entry["id"]}')
        quote = self.row(entry['id'], selector['row'], selector.get('occurrence', 0)) if 'row' in selector else entry['quote']
        local = entry['quote'].find(quote)
        require(local >= 0, f'Subquote missing: {entry["id"]}')
        result = {k: entry[k] for k in ('document_id', 'block_id')}
        result.update(quote=quote, start=entry['start'] + local, end=entry['start'] + local + len(quote))
        require(self.canonical[entry['document_id']][result['start']:result['end']] == quote,
                'Subquote offset mismatch')
        return result


def numeric_cell(sources, item):
    row = sources.row(item['alias'], item['row'], item.get('occurrence', 0))
    numbers = []
    for value in row.split('|')[1:]:
        value = value.replace(',', '').replace(' ', '').replace('$', '').replace('%', '')
        if value in ('—', '–'):
            numbers.append(Decimal(0))
        elif re.fullmatch(r'\(?-?\d+(\.\d+)?\)?', value):
            numbers.append(-Decimal(value[1:-1]) if value.startswith('(') else Decimal(value))
    col = item['numeric_column']
    require(col < len(numbers), f'Numeric column absent: {item}')
    # All selected tables are annual comparison tables; fiscal_year is the fact period,
    # not automatically the report year. Check the explicit table header year ordering.
    full = sources.resolve(item['alias'])['quote']
    header = '\n'.join(full.splitlines()[:8])
    header_years = list(dict.fromkeys(int(y) for y in re.findall(r'\b20\d{2}\b', header)))
    require(col < len(header_years) and header_years[col] == item['fiscal_year'],
            f'Fiscal column mismatch: {item}')
    return numbers[col]


def evaluate_formula(operation, values):
    if operation == 'ratio_pct':
        return values[0] / values[1] * 100
    if operation == 'yoy_pct':
        return (values[0] / values[1] - 1) * 100
    if operation in ('sum', 'cash_residual'):
        return sum(values, Decimal(0))
    if operation == 'difference':
        return values[0] - values[1]
    if operation == 'avg_days':
        return (values[0] + values[1]) / 2 / values[2] * values[3]
    if operation in ('nrv_margin_delta', 'margin_delta'):
        return values[0] / values[1] * 100 - values[2] / values[3] * 100
    raise ValueError(f'Unsupported formula: {operation}')


def validate_numeric(sources, checks, seeds):
    known = {}
    seed_map = {x['id']: x for x in seeds}
    results = []
    for check in checks:
        require(check['id'] not in known, 'Duplicate numeric ID')
        values, source_aliases = [], set()
        for item in check['inputs']:
            expected = Decimal(item['value'])
            if 'check_id' in item:
                require(item['check_id'] in known, 'Numeric reference must be an earlier check')
                value, inherited = known[item['check_id']]
                source_aliases.update(inherited)
            elif 'row' in item:
                value = numeric_cell(sources, item)
                source_aliases.add(item['alias'])
            elif 'source_phrase' in item:
                entry = sources.resolve(item['alias'])
                require(item['source_phrase'] in entry['quote'], f'Missing numeric phrase: {item}')
                source_aliases.add(item['alias'])
                if item['unit'] == 'fiscal_days':
                    weeks = 53 if item['fiscal_year'] == 2026 else 52
                    require(item['fiscal_year'] in (2024, 2025, 2026) and item['alias'] == 'MU26.614', 'Invalid week mapping')
                    value = Decimal(weeks * 7)
                else:
                    raw = Decimal(re.search(r'\d+(?:\.\d+)?', item['source_phrase'])[0])
                    value = raw * Decimal(item.get('scale', '1'))
                    if 'scale' in item:
                        require(item['source_unit'] == 'USD_billion' and item['unit'] == 'USD_million' and item['scale'] == '1000', 'Bad unit conversion')
            else:
                require(item['unit'] == 'fiscal_days', 'Unsourced numeric input')
                entry = sources.resolve(item['date_source_alias'])
                source_aliases.add(item['date_source_alias'])
                start, end = date.fromisoformat(item['prior_period_end']), date.fromisoformat(item['period_end'])
                for dt in (start, end):
                    formatted = f'{dt:%b} {dt.day}, {dt.year}'
                    require(formatted in entry['quote'], f'Date absent from balance sheet: {formatted}')
                value = Decimal((end-start).days)
            require(value == expected, f'Input mismatch in {check["id"]}: {item}')
            values.append(value)
        calculated = evaluate_formula(check['operation'], values)
        quantized = calculated.quantize(Decimal('1').scaleb(-check['decimal_places']), rounding=ROUND_HALF_UP)
        require(calculated == Decimal(check['exact_decimal']), f'Exact arithmetic mismatch: {check["id"]}')
        require(quantized == Decimal(check['expected']), f'Rounded arithmetic mismatch: {check["id"]}')
        for case_id in check['case_ids']:
            seed = seed_map[case_id]
            as_of = (seed.get('confirmed_context') or {}).get('as_of', '2026-10-11')
            for alias in source_aliases:
                e = sources.resolve(alias)
                require(e['filed_at'] <= as_of, f'Numeric future leak: {case_id}/{alias}')
                require(case_id != 'U14' or e['document_id'] == 'NVDA_FY2024', 'U14 numerical scope leak')
        known[check['id']] = calculated, source_aliases
        results.append({**check, 'verified': True, 'source_aliases': sorted(source_aliases)})
    return results


def render_reference(text, catalog):
    return REF.sub(lambda m: f'[{m[1]}]({catalog[m[1]]["source_url"]}#e-{m[1].lower().replace(".", "-")})', text)


def build_payloads():
    sources = Sources()
    answers = json.loads((OUT / 'answer_specs.json').read_text())
    labels = json.loads((OUT / 'label_specs.json').read_text())
    checks = json.loads((OUT / 'numeric_specs.json').read_text())
    seeds = read_jsonl(ROOT / 'data/evaluation/user_seeds_v2.jsonl')
    ids = [f'U{i:02}' for i in range(1,21)]
    require([x['id'] for x in answers] == [x['id'] for x in labels] == [x['id'] for x in seeds] == ids,
            'Expected exactly U01-U20 in original order')
    for check in checks:
        for item in check['inputs']:
            if item.get('unit') == 'fiscal_days' and 'source_phrase' in item:
                require('fiscal_year' in item, 'Fiscal day input missing year')
    numeric = validate_numeric(sources, checks, seeds)
    questions, rubrics, samples, queries = [], [], [], []
    docs_md = ['# 20题开发 Golden Dataset v2', '',
               '用户已授权按复核意见修订并发布。全部20题为dev，非独立holdout。参考答案不限唯一措辞；U16允许部分回答并明确缺项。', '',
               '召回、事实/口径、计算、引用和边界分别评估；轻微舍入不扣检索分。完整评分规则见README。', '']
    for answer, label, seed in zip(answers, labels, seeds):
        case_id = answer['id']
        as_of = (seed.get('confirmed_context') or {}).get('as_of', '2026-10-11')
        aliases = list(dict.fromkeys(REF.findall(answer['answer_markdown'])))
        require(aliases, f'Uncited reference: {case_id}')
        for alias in aliases:
            entry = sources.resolve(alias)
            require(entry['filed_at'] <= as_of, f'Future reference: {case_id}/{alias}')
        groups, group_meta = [], []
        for i, group in enumerate(label['evidence_groups']):
            require(group['alternatives'], 'Empty evidence OR group')
            selectors = group['alternatives']
            evs = [sources.evidence(x, as_of) for x in selectors]
            groups.append(evs)
            group_meta.append({'id': f'{case_id}:g{i}', 'criterion': group['criterion'],
                               'logic': 'any_one_alternative', 'selectors': selectors})
        scoped_docs = sorted({sources.resolve(x)['document_id'] for x in aliases} |
                             {e['document_id'] for group in groups for e in group})
        if case_id == 'U14':
            require(scoped_docs == ['NVDA_FY2024'], 'U14 scope changed')
        reference = REF.sub(lambda m: f'[{m[1]}]({sources.catalog[m[1]]["source_url"]})', answer['answer_markdown'])
        check_ids = [x['id'] for x in numeric if case_id in x['case_ids']]
        question = Question(id=case_id, question=seed['question'], question_en='', category='complex_financial_analysis',
                            family=label['family'], split='dev', documents=scoped_docs, reference=reference,
                            evidence_groups=groups, outcome='answer', as_of=as_of,
                            review_status='user_review_accepted_agent_revised',
                            derivation={'numeric_check_ids': check_ids, 'answerability': label['answerability'],
                                        'scope': 'annual_reports_only', 'confirmed_context': seed.get('confirmed_context'),
                                        'no_english_rewrite_track': True})
        row = question.model_dump()
        row.update(dataset_role='development_golden', ready_for_scoring=True,
                   answerability=label['answerability'], reference_evidence_ids=aliases,
                   evidence_group_metadata=group_meta, approval=answer['approval'])
        questions.append(row)
        # Original text plus explicit context is the query contract. No answer/evidence leaks.
        queries.append({'id':case_id, 'question':seed['question'], 'reading_context':seed['reading_context'],
                        'confirmed_context':seed.get('confirmed_context'), 'as_of':as_of,
                        'corpus_scope': {'MU':[2024,2025,2026], 'NVDA':[2024,2025,2026], 'AMD':[2023,2024,2025]} if case_id!='U14' else {'NVDA':[2024]}})
        rubrics.append({'id':case_id, 'answerability':label['answerability'],
                        'mandatory_facts':[{'id':f'{case_id}:f{i+1}', 'expected':fact, 'score':{'0':'遗漏或实质错误','0.5':'部分正确','1':'充分且口径正确'}} for i,fact in enumerate(label['mandatory_facts'])],
                        'required_evidence_group_ids':[x['id'] for x in group_meta],
                        'evidence_criteria':group_meta, 'numeric_check_ids':check_ids,
                        'expected_limits':label['expected_limits'], 'material_errors':label['material_errors'],
                        'limitations':answer['limitations'], 'annotation_review':'agent_curated_under_user_publication_authorization',
                        'optional_reference_evidence_ids':sorted(set(aliases)-{s['alias'] for g in label['evidence_groups'] for s in g['alternatives']})})
        sample = SingleTurnSample(user_input=seed['question'], reference=reference,
                                  reference_contexts=[group[0]['quote'] for group in groups],
                                  reference_context_ids=[x['id'] for x in group_meta])
        samples.append(sample)
        linked = REF.sub(lambda m:f'[{m[1]}](#e-{m[1].lower().replace(".","-")})', answer['answer_markdown'])
        docs_md += [f'## {case_id}', '', '**原始问题：** '+seed['question'], '', f'**资料截止：** {as_of}；仅在库年报。', '',
                    linked, '', '**边界：** '+'；'.join(answer['limitations']), '', '**必答事实：**', '']
        docs_md.extend(f'- {fact}' for fact in label['mandatory_facts'])
        docs_md += ['', '**不应出现：** '+'；'.join(label['material_errors']), '',
                    f'**发布状态：** 已按用户反馈修订，可用于开发评测；{len(groups)}个必需证据组，{len(check_ids)}项数值检查。', '']
    # RAGAS validates supported field types. ID recall must still map retrieved spans to
    # group IDs (finrag.evaluation.score), not hand the list of raw document IDs to RAGAS.
    evaluation_dataset = EvaluationDataset(samples=samples)
    require(len(evaluation_dataset.samples) == 20, 'RAGAS sample count mismatch')
    docs_md += ['## 原文证据目录', '']
    for alias, e in sorted(sources.catalog.items()):
        docs_md += [f'<a id="e-{alias.lower().replace(".","-")}"></a>', '', f'### {alias}', '',
                    f'[{e["document_id"]} SEC原文]({e["source_url"]}) · filed_at={e["filed_at"]} · accession={e["accession"]}', '',
                    f'Block：`{e["block_id"]}`；区间：`{e["start"]}:{e["end"]}`；DOM：`{e["locator"]["xpath"]}`', '',
                    '```text', e['quote'], '```', '']
    payloads = {'golden.jsonl':jsonl_bytes(questions), 'rubrics.jsonl':jsonl_bytes(rubrics),
                'evaluation_dataset.jsonl':jsonl_bytes([s.model_dump(exclude_none=True) for s in samples]),
                'retrieval_queries.jsonl':jsonl_bytes(queries), 'numeric_checks.jsonl':jsonl_bytes(numeric),
                'evidence_catalog.jsonl':jsonl_bytes([e for _,e in sorted(sources.catalog.items())]),
                'reference_answers.md':('\n'.join(docs_md)+'\n').encode()}
    # Preserve and identify the previous released evaluation state.
    protected = ['data/evaluation/golden_v1.jsonl','data/evaluation/freeze_v1.json',
                 'data/evaluation/ragas_reference.jsonl','configs/best.json','reports/test_release.json']
    input_paths = [OUT/x for x in ['SPEC.md','README.md','answer_specs.json','label_specs.json','numeric_specs.json','user_feedback.json']]
    input_paths += [Path(__file__), ROOT/'data/sources.jsonl', ROOT/'data/evaluation/user_seeds_v2.jsonl',
                    ROOT/'data/evaluation/review_v2/review.md',ROOT/'data/evaluation/review_v2/human_review.jsonl']
    summary = {'questions':len(questions), 'mandatory_evidence_groups':sum(len(x['evidence_groups']) for x in questions),
               'alternative_groups':sum(len(g)>1 for x in questions for g in x['evidence_groups']),
               'evidence_blocks':len(sources.catalog),'numeric_checks':len(numeric)}
    manifest = {'version':'user-research-golden-v2.0','schema_version':'question-compatible-plus-rubrics-v1',
                'status':'released_development_golden','created_date':'2026-10-26','summary':summary,
                'splits':{'dev':20,'test':0}, 'families':dict(Counter(x['family'] for x in questions)),
                'approval':'User accepted specified review corrections and authorized dataset publication; final rubric/qrels are agent-authored, not separately line-by-line human signed.',
                'source_hashes':{d:sources.filings[d]['sha256'] for d in sorted(sources.blocks)},
                'inputs_sha256':{str(p.relative_to(ROOT)):sha(p.read_bytes()) for p in input_paths},
                'outputs_sha256':{name:sha(body) for name,body in payloads.items()},
                'protected_v1_sha256':{p:sha((ROOT/p).read_bytes()) for p in protected if (ROOT/p).exists()},
                'validation':{'raw_source_hash':True,'raw_DOM':True,'canonical_and_subquote_spans':True,
                              'as_of_all_references_and_numeric_sources':True,'u14_only_nvda_fy2024':True,
                              'decimal_arithmetic_and_rounding':True,'question_schema':True,'ragas_sample_schema':True},
                'runtime_loader':'Existing fr-rag golden/dev/test still use v1; explicitly load this file for v2.',
                'evaluation_not_run':True,'paid_api_called':False,'database_called':False,
                'limitations':['Development material, not an independent holdout or benchmark score.',
                               'Required groups are curated sufficient evidence; alternative list is not exhaustive.',
                               'Absence of disclosure is a scoped review conclusion, not proven by one negative snippet.',
                               'Do not infer answer accuracy from evidence recall. Numeric checks do not automatically parse generated prose.',
                               'RAGAS export keeps the first alternative; use golden.jsonl with the span scorer to honor all alternatives.',
                               'U16 is a partial answer; no unsupported market-share values required.',
                               'Quarterly series absent from annual reports is a scope limit, not a retrieval error.']}
    payloads['manifest.json'] = json_bytes(manifest)
    return payloads, summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='Read-only validation against published bytes')
    args = parser.parse_args()
    payloads, summary = build_payloads()
    released = (OUT/'manifest.json').exists()
    if args.check or released:
        for name, expected in payloads.items():
            path = OUT/name
            require(path.exists() and path.read_bytes()==expected, f'Release mismatch: {name}; create a new version for edits.')
        print(json.dumps({'status':'validated_read_only',**summary},ensure_ascii=False))
    else:
        for name, body in payloads.items():
            require(not (OUT/name).exists(), f'Unexpected preexisting output: {name}')
        for name, body in payloads.items():
            (OUT/name).write_bytes(body)
        print(json.dumps({'status':'released',**summary},ensure_ascii=False))


if __name__ == '__main__':
    main()
