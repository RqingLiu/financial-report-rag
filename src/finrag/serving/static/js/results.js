import {
  $,
  el,
  json,
  table,
  dialog,
  external,
  tabs
} from './dom.js';
import {
  state,
  visibleAnswer
} from './state.js';
export function source(e) {
  const nodes = [el('p', 'subtle', `${e.ticker||''} · ${e.document_id} · report FY${e.fiscal_year||'—'} · 公开 ${e.filed_at||'—'}`), external(e.source_url, '打开SEC原始年报 ↗'), el('pre', 'source-text', e.text), json(e.source_spans, '原始block / 字符位置')];
  if (e.text_truncated) nodes.push(el('p', 'hint', '预览已截断，完整源文仍在本地trace。'));
  dialog(`${e.citation} · 原始证据`, nodes);
}

function withCitations(target, text) {
  for (const part of String(text).split(/(\[E\d+\])/g)) {
    if (/^\[E\d+\]$/.test(part)) {
      const b = el('button', 'citation', part);
      b.onclick = () => {
        const e = (state.data?.evidence || []).find(e => e.citation === part.slice(1, -1));
        if (e) source(e);
      };
      target.append(b);
    } else target.append(document.createTextNode(part));
  }
}

function answerNode(text) {
  const box = el('div', 'answer-body');
  const lines = String(text).split('\n');
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i];
    if (!line.trim()) continue;
    if (line.trim().startsWith('|') && lines[i + 1]?.match(/^\s*\|?[\s:|-]+\|\s*$/)) {
      const headers = line.trim().split('|').slice(1, -1).map(s => s.trim()),
        rows = [];
      i += 2;
      while (i < lines.length && lines[i].trim().startsWith('|')) {
        rows.push(lines[i].trim().split('|').slice(1, -1).map(s => {
          const cell = el('span');
          withCitations(cell, s.trim());
          return cell;
        }));
        i++;
      }
      i--;
      box.append(table(headers, rows));
      continue;
    }
    const heading = line.match(/^#{1,4}\s+(.+)$/);
    const p = el(heading ? 'h3' : 'p');
    withCitations(p, heading ? heading[1] : line);
    box.append(p);
  }
  return box;
}
export function renderResults(render) {
  tabs($('result-tabs'), [
    ['answer', '最终回答'],
    ['evidence', '来源证据'],
    ['candidates', '候选与去留'],
    ['plan', '查询计划'],
    ['input', '原始问题']
  ], state.resultTab, id => {
    state.resultTab = id;
    render();
  });
  const body = $('result-content');
  body.replaceChildren();
  const data = state.data;
  if (!data) {
    body.append(el('p', 'empty', '打开保存的运行可以免费查看真实结果。'));
    return;
  }
  if (state.resultTab === 'answer') {
    if (!visibleAnswer()) {
      body.append(el('p', 'empty', '回放尚未到达回答步骤。'));
      return;
    }
    if (data.generation?.answer) {
      body.append(el('span', 'badge', data.observation_mode === 'offline_contract_fixture' ? '受控测试输出 · 非真实模型回答' : '实际模型输出 · 非人工审核答案'), answerNode(data.generation.answer));
    } else if (data.error) {
      body.append(el('p', 'notice error', `本次未交付答案：${data.error.code||data.error.type}`), el('p', 'hint', '错误并不代表年报没有披露；仍可检查已完成步骤。'));
    } else if (data.plan?.action === 'clarify') {
      body.append(el('h3', '', '需要补充范围'), el('p', '', data.plan.clarification_questions?.join('\n') || '请补充公司、报告财年或所需指标。'));
    } else body.append(el('p', 'empty', state.busy ? '正在运行，最终回答将在生成完成后展示。' : '该记录未生成答案；可能为仅检索或资料不足。'));
    if (data.fallback?.type) body.append(json(data.fallback, '证据兜底，不是生成答案'));
  }
  if (state.resultTab === 'input') body.append(json(data.inputs, '原始输入'));
  if (state.resultTab === 'plan') {
    const p = data.plan;
    if (!p) {
      body.append(el('p', 'empty', '没有通过校验的计划；如规划失败，可在plan的内部调用查看已记录输入。'));
      return;
    }
    body.append(table(['公司', '报告财年'], (p.companies || []).map(c => [c.ticker, c.report_years.join(', ')])), json(p, '完整实际计划'));
  }
  if (state.resultTab === 'evidence') {
    const rows = data.evidence || [];
    if (!rows.length) body.append(el('p', 'empty', '没有已保存的最终证据。'));
    rows.forEach(e => {
      const b = el('button', 'evidence-card');
      b.append(el('strong', '', `${e.citation} · ${e.document_id}`), el('span', '', e.text.slice(0, 220)));
      b.onclick = () => source(e);
      body.append(b);
    });
  }
  if (state.resultTab === 'candidates') {
    const hits = data.retrieval?.ranked_hits || data.stages?.find(s => s.name === 'fusion')?.outputs?.ranked_hits || [];
    if (!hits.length) {
      body.append(el('p', 'empty', '没有已记录的融合候选。'));
      return;
    }
    const search = el('input', 'filter');
    search.placeholder = '按公司、chunk ID或文本过滤';
    body.append(search);
    const results = el('div');
    body.append(results);
    const decisions = data.retrieval?.metadata?.decisions || [];
    const grades = data.stages?.find(s => s.name === 'rerank')?.outputs?.scores || {};
    const draw = () => {
      const query = search.value.toLowerCase();
      const found = hits.map((h, i) => ({
        h,
        i
      })).filter(({
        h
      }) => JSON.stringify(h.chunk).toLowerCase().includes(query));
      results.replaceChildren(el('p', 'hint', `共${hits.length}条融合候选；本页展示前80条匹配。精排grade是模型预测，不是已验证相关性。`), table(['粗排名', '来源', 'RRF分', '精排', 'context决策'], found.slice(0, 80).map(({
        h,
        i
      }) => {
        const c = h.chunk,
          d = decisions.find(d => d.parent_chunk_id === c.id),
          b = el('button', 'text-button', c.document_id);
        b.onclick = () => dialog(c.id, [el('pre', 'source-text', c.text), json(h, '候选数据'), json(grades[c.id], '精排预测'), json(d, '去留原因')]);
        return [i + 1, b, Number(h.score).toPrecision(4), grades[c.id]?.s ?? '—', d?.decision || '未进入选择 / 未记录'];
      })));
    };
    search.oninput = draw;
    draw();
  }
}
