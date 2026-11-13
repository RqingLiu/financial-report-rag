import {
  $,
  el,
  json,
  table,
  seconds,
  tabs
} from './dom.js';
import {
  request
} from './transport.js';
import {
  state,
  selectedTransition,
  nodeStages
} from './state.js';
const cache = new Map();
let renderToken = 0;
export async function renderInspector(render) {
  const node = state.workflow.nodes.find(n => n.id === state.node),
    t = selectedTransition(),
    token = ++renderToken;
  $('step-title').textContent = node?.label || state.node;
  $('step-description').textContent = node?.description || '';
  $('step-timing').textContent = t ? seconds(t.duration_seconds) : '尚未执行';
  tabs($('step-tabs'), [
    ['overview', '概要'],
    ['state', 'State'],
    ['calls', '内部调用'],
    ['code', '代码位置']
  ], state.stepTab, id => {
    state.stepTab = id;
    render();
  });
  const body = $('step-content');
  body.replaceChildren();
  if (!t && state.stepTab !== 'code') {
    body.append(el('p', 'empty', '该节点尚未执行、未启用或未被这条历史记录捕获。'));
    return;
  }
  if (state.stepTab === 'overview') {
    body.append(table(['观测项', '值'], [
      ['状态', t.status],
      ['节点耗时（含子调用）', seconds(t.duration_seconds)],
      ['开始', t.started_at || '历史未记录'],
      ['结束', t.ended_at || '运行中 / 历史未记录'],
      ['本步变更', (t.changed_fields || []).join(', ') || '历史未记录'],
      ['operation ID', t.operation_id || '历史未记录']
    ]));
    if (t.output) body.append(json(t.output, '记录的输出摘要'));
    if (t.error) body.append(json(t.error, '实际错误'));
    body.append(el('p', 'hint', t.state_capture_version ? '已记录白名单业务 state；大候选集以ID和计数表示，正文在下方结果区。' : '此历史trace只有节点计数/摘要，没有完整state快照。未使用当前数据库补写历史。'));
  }
  if (state.stepTab === 'state') {
    if (!t.state_capture_version) {
      body.append(el('p', 'notice', '历史未记录完整业务state；以下仅为当时保存的计数摘要。'), json(t.input, '输入摘要'), json(t.output, '输出摘要'));
    } else {
      body.append(el('p', 'hint', '捕获的业务state，不包含连接、密钥、向量或系统prompt。大列表会标明截断。'));
      const keys = t.changed_fields || [];
      if (keys.length) body.append(table(['变更字段', '之前', '之后'], keys.map(k => [k, json(t.state_before?.[k], '展开'), json(t.state_after?.[k], '展开')])));
      else body.append(el('p', 'subtle', '无已记录的业务字段变化。'));
      const before = json(t.state_before, '运行前 State'),
        after = json(t.state_after, '运行后 State');
      after.open = true;
      body.append(before, after);
    }
  }
  if (state.stepTab === 'calls') {
    const rows = [...new Map(nodeStages(state.node).map(s => [s.id, s])).values()];
    if (!rows.length) body.append(el('p', 'empty', '没有已记录的内部span；缓存命中可能没有新的模型调用。'));
    rows.forEach(s => {
      const d = el('details', 'call');
      d.append(el('summary', '', `${s.name} · ${s.status} · ${seconds(s.duration_seconds)}`), json(s.inputs, '输入'), json(s.outputs, '输出'));
      if (s.source) d.append(json(s.source, '记录的调用位置'));
      body.append(d);
    });
  }
  if (state.stepTab === 'code') {
    body.append(el('p', 'hint', '适配器负责该node；算法可能在其他模块。代码片段来自当前checkout；仅匹配hash时能核对为当时版本。'));
    if (t?.source) body.append(json(t.source, '该次记录的节点源码身份'));
    try {
      const id = `node_${state.node}`;
      if (!cache.has(id)) cache.set(id, await request(`/code/${id}`));
      if (token !== renderToken) return;
      cache.get(id).snippets.forEach(s => {
        const d = el('details', 'code');
        d.open = s === cache.get(id).snippets[0];
        d.append(el('summary', '', `${s.path}:${s.start_line} · ${s.symbol}`), el('p', 'subtle', s.role));
        if (t?.source?.path === s.path) d.append(el('p', 'hint', t.source.sha256 === s.sha256 ? '文件hash与该次记录一致。' : '文件已变更；此处为当前代码，非历史源码快照。'));
        const lines = s.text.split('\n').map((line, i) => `${String(s.start_line+i).padStart(4)}  ${line}`).join('\n');
        d.append(el('pre', 'source-code', lines));
        if (s.truncated) d.append(el('p', 'hint', '长函数片段已截断。'));
        body.append(d);
      });
    } catch (e) {
      if (token === renderToken) body.append(el('p', 'notice', `代码位置暂不可读：${e.message}`));
    }
  }
}
