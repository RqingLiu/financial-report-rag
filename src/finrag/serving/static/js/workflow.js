import {
  $,
  el,
  seconds
} from './dom.js';
import {
  state,
  transitions,
  visibleTransitions
} from './state.js';
export function renderWorkflow(select) {
  const target = $('workflow');
  target.replaceChildren();
  const visible = visibleTransitions(),
    all = transitions();
  state.workflow.nodes.filter(n => n.enabled || $('show-optional').checked || all.some(t => t.node === n.id)).forEach(n => {
    const t = visible.filter(t => t.node === n.id).at(-1),
      recorded = all.find(t => t.node === n.id);
    let status = t?.status || (!n.enabled ? 'disabled' : (!state.busy && state.data && (state.cursor === null || state.cursor === all.length) && !recorded ? 'skipped' : 'pending'));
    const b = el('button', `workflow-node ${status} ${state.node===n.id?'selected':''}`);
    b.setAttribute('aria-pressed', String(state.node === n.id));
    const dot = el('span', 'node-dot', status === 'ok' ? '✓' : status === 'error' ? '!' : status === 'running' ? '•' : '');
    const content = el('div', 'node-label');
    content.append(el('strong', '', n.label), el('span', 'mono', n.id));
    const timing = el('span', 'node-time', t?.status === 'running' && t.started_at ? `${((Date.now()-Date.parse(t.started_at))/1000).toFixed(1)}s…` : t ? seconds(t.duration_seconds) : ({
      disabled: '未启用',
      skipped: '未执行',
      pending: '等待'
    })[status]);
    b.append(dot, content, timing);
    b.onclick = () => select(n.id);
    target.append(b);
  });
  const ext = (state.data?.stages || []).filter(s => !s.operation_id && s.name === 'resource_setup');
  if (ext.length) target.append(el('p', 'hint', `图外资源初始化 ${seconds(ext[0].duration_seconds)}；请求总耗时另计。`));
  if (visible.length) target.append(el('p', 'hint', `已走路径：${visible.map(t=>t.node).join(' → ')}`));
  const max = all.length;
  $('scrubber').max = max;
  $('scrubber').value = state.cursor ?? max;
  $('scrubber').disabled = state.busy || !max;
  $('play-position').textContent = max ? `${state.cursor??max} / ${max} 已记录节点` : '暂无节点记录';
  for (const id of ['previous', 'next', 'play']) $(id).disabled = state.busy || !max;
  $('play').textContent = state.playing ? '暂停回放' : '播放记录';
  $('view-mode').textContent = state.busy ? 'LIVE · 实时执行' : state.saved ? 'RECORDED · 只读回放' : 'LIVE · 执行结束';
  const counts = state.data?.agent?.usage;
  const stats = $('stats');
  stats.replaceChildren();
  const completed = state.cursor === null || state.cursor === max;
  [
    ['请求总耗时', completed ? seconds(state.data?.duration_seconds) : '回放中'],
    ['已确认节点', `${visible.filter(t=>t.status==='ok').length} / ${max||'—'}`],
    ['整次 provider 尝试', counts?.provider_calls ?? '未记录'],
    ['整次已知费用', counts?.paid_known_usd !== undefined ? `$${counts.paid_known_usd}` : '未记录']
  ].forEach(([k, v]) => {
    const x = el('div');
    x.append(el('span', 'small', k), el('strong', 'mono', v));
    stats.append(x);
  });
}
