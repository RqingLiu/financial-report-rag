export const state = {
  data: null,
  workflow: {
    nodes: [],
    edges: []
  },
  node: 'plan',
  stepTab: 'overview',
  resultTab: 'answer',
  busy: false,
  saved: true,
  cursor: null,
  lastSequence: 0,
  gap: false,
  runs: [],
  playing: false
};
export const stageNodes = {
  catalog_snapshot: 'catalog',
  query_plan: 'plan',
  evidence_regroup: 'regroup',
  embed_queries: 'retrieve',
  retrieve: 'retrieve',
  fusion: 'fusion',
  rerank: 'context',
  context_build: 'context',
  calculation_prepare: 'calculate',
  generation: 'answer'
};
export function transitions() {
  return state.data?.agent?.transitions || [];
}
export function visibleTransitions() {
  const all = transitions();
  return state.saved && state.cursor !== null ? all.slice(0, state.cursor) : all;
}
export function selectedTransition() {
  return visibleTransitions().filter(r => r.node === state.node).at(-1);
}
export function nodeStages(node) {
  const rows = state.data?.stages || [],
    t = selectedTransition();
  return rows.filter(s => t?.operation_id && s.operation_id ? s.operation_id === t.operation_id : stageNodes[s.name] === node || (s.name.startsWith('retrieve.') && node === 'retrieve')).concat(rows.filter(s => s.name === 'llm_call' && rows.some(p => p.id === s.parent_id && stageNodes[p.name] === node)));
}
export function visibleAnswer() {
  return !state.saved || state.cursor === null || visibleTransitions().some(t => t.node === 'answer' && t.status === 'ok');
}
export function receive(kind, data) {
  if (data.sequence) {
    if (data.sequence <= state.lastSequence) return;
    if (state.lastSequence && data.sequence > state.lastSequence + 1) state.gap = true;
    state.lastSequence = data.sequence;
  }
  if (kind === 'accepted') {
    state.data.query_id = data.query_id;
    return;
  }
  if (kind === 'result') {
    state.data = data;
    return;
  }
  if (kind === 'failure') {
    state.data.status = 'error';
    state.data.error = data.error;
    return;
  }
  if (kind.startsWith('node_')) {
    state.data.agent ||= {
      transitions: []
    };
    const rows = state.data.agent.transitions,
      idx = rows.findIndex(r => r.operation_id === data.operation_id);
    if (idx < 0) rows.push(data);
    else rows[idx] = data;
    state.node = data.node;
    return;
  }
  if (kind.startsWith('stage_')) {
    const rows = state.data.stages,
      idx = rows.findIndex(r => r.id === data.id);
    if (idx < 0) rows.push(data);
    else rows[idx] = data;
    if (data.name === 'query_plan' && data.outputs?.validated_plan) state.data.plan = data.outputs.validated_plan;
    if (data.name === 'context_build' && data.outputs?.evidence) state.data.evidence = data.outputs.evidence;
    if (data.name === 'generation' && data.status === 'ok') state.data.generation = data.outputs;
  }
}
