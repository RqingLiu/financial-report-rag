import {
  $,
  el,
  note
} from './dom.js';
import {
  request,
  streamQuery
} from './transport.js';
import {
  state,
  transitions,
  receive
} from './state.js';
import {
  renderWorkflow
} from './workflow.js';
import {
  renderInspector
} from './inspector.js';
import {
  renderResults
} from './results.js';
let timer = null,
  scheduled = false;

function render() {
  renderWorkflow(id => {
    state.node = id;
    render();
  });
  renderInspector(render);
  renderResults(render);
  const d = state.data;
  $('run-heading').textContent = d ? `${d.query_id||'新请求'} · ${d.inputs?.original_question||''}` : '选择历史记录，或运行一个新问题。';
  $('submit').disabled = state.busy || state.budgetBlocked;
  $('cancel').hidden = !state.busy;
  $('load').disabled = state.busy;
  $('refresh').disabled = state.busy;
}

function schedule() {
  if (scheduled) return;
  scheduled = true;
  requestAnimationFrame(() => {
    scheduled = false;
    render();
  });
}

function stop() {
  clearInterval(timer);
  timer = null;
  state.playing = false;
}

function position(n) {
  state.cursor = Math.min(transitions().length, Math.max(0, n));
  const t = transitions()[Math.max(0, state.cursor - 1)];
  if (t) state.node = t.node;
  render();
}
$('previous').onclick = () => {
  stop();
  position((state.cursor ?? transitions().length) - 1);
};
$('next').onclick = () => {
  stop();
  position((state.cursor ?? transitions().length) + 1);
};
$('scrubber').oninput = () => {
  stop();
  position(Number($('scrubber').value));
};
$('play').onclick = () => {
  if (state.playing) {
    stop();
    render();
    return;
  }
  state.playing = true;
  if (state.cursor === null || state.cursor >= transitions().length) position(0);
  timer = setInterval(() => {
    position((state.cursor ?? 0) + 1);
    if (state.cursor >= transitions().length) {
      stop();
      render();
    }
  }, 1000);
  render();
};
$('show-optional').onchange = render;
$('close-dialog').onclick = () => $('detail-dialog').close();

function cases() {
  const run = state.runs.find(r => r.id === $('run-select').value);
  $('case-select').replaceChildren();
  for (const c of run?.cases || []) {
    const o = el('option', '', c.id);
    o.value = c.id;
    $('case-select').append(o);
  }
}
$('run-select').onchange = cases;
async function refresh() {
  const data = await request('/runs');
  state.runs = data.runs;
  const previous = $('run-select').value;
  $('run-select').replaceChildren();
  state.runs.forEach(r => {
    const o = el('option', '', `${r.label} (${r.cases.length})`);
    o.value = r.id;
    $('run-select').append(o);
  });
  const match = state.runs.find(r => r.id === previous && r.cases.length) || state.runs.find(r => r.kind === 'evaluation' && r.label.includes('baseline41')) || state.runs.find(r => r.cases.length);
  if (match) $('run-select').value = match.id;
  cases();
}
async function load() {
  if (state.busy) return;
  stop();
  const run = $('run-select').value,
    id = $('case-select').value;
  if (!id) {
    note('没有可打开的记录。');
    return;
  }
  state.data = await request(`/runs/${encodeURIComponent(run)}/cases/${encodeURIComponent(id)}`);
  state.saved = true;
  state.cursor = null;
  state.lastSequence = 0;
  state.gap = false;
  state.node = transitions().some(t => t.node === 'plan') ? 'plan' : transitions()[0]?.node || 'plan';
  state.stepTab = 'overview';
  state.resultTab = 'answer';
  note(state.data.observation_mode === 'offline_contract_fixture' ? '离线受控测试：mock取证与模型输出，用于验证新State展示，非真实财报分析，不调用API。' : '已打开真实保存记录，无模型调用。旧trace未记录的State会明确标为未记录。');
  render();
}
$('load').onclick = () => load().catch(e => note(e.message, true));
$('refresh').onclick = () => refresh().catch(e => note(e.message, true));
$('cancel').onclick = async () => {
  if (state.data?.query_id) {
    try {
      await request(`/queries/${state.data.query_id}/cancel`, {
        method: 'POST'
      });
      note('已请求取消；在途调用可能仍需完成结算。');
    } catch (e) {
      note(e.message, true);
    }
  }
};
$('query-form').onsubmit = async event => {
  event.preventDefault();
  if (state.busy || state.budgetBlocked) return;
  let confirmed;
  try {
    confirmed = $('confirmed').value.trim() ? JSON.parse($('confirmed').value) : null;
    if (confirmed !== null && (typeof confirmed !== 'object' || Array.isArray(confirmed))) throw new Error('确认范围须为JSON对象');
  } catch (e) {
    note(`确认范围无效：${e.message}`, true);
    return;
  }
  const input = {
    question: $('question').value.trim(),
    as_of: $('as-of').value,
    reading_context: $('background').value.trim(),
    confirmed_context: confirmed
  };
  stop();
  state.busy = true;
  state.saved = false;
  state.cursor = null;
  state.lastSequence = 0;
  state.gap = false;
  state.node = 'catalog';
  state.data = {
    inputs: {
      original_question: input.question,
      ...input
    },
    status: 'running',
    stages: [],
    agent: {
      transitions: []
    }
  };
  note('正在执行真实查询。每步输出在该步完成后展示。');
  render();
  try {
    await streamQuery(input, $('mode').value === 'answer', (kind, data) => {
      receive(kind, data);
      if (kind === 'result') note(data.status === 'error' ? `运行失败：${data.error?.code||data.error?.type}` : state.gap ? '部分实时事件缺失，已用最终记录校准。' : '本次执行已结束；节点完成不代表财务结论已审核。', data.status === 'error');
      schedule();
    });
  } catch (e) {
    state.data.status = 'error';
    note(e.message, true);
  } finally {
    state.busy = false;
    render();
    await refresh();
    await readiness();
  }
};
async function readiness() {
  try {
    const b = await request('/readiness');
    state.budgetBlocked = b.status !== 'available';
    $('budget').textContent = b.status === 'blocked' ? `新运行已被预算停止线阻止：已知 $${b.known_usd} + 未结预留 $${b.held_usd}，停止线 $${b.stop_usd}。仍可免费回放；不会自动提高上限。` : b.status === 'available' ? `新运行可能收费 · 单请求上限 $${b.request_cap_usd} · 回放不收费` : '预算未就绪；仍可查看历史。请检查本地配置。';
    render();
  } catch {
    state.budgetBlocked = true;
    $('budget').textContent = '预算状态暂不可用；仍可查看历史。';
    render();
  }
}
const today = new Date();
$('as-of').value = `${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,'0')}-${String(today.getDate()).padStart(2,'0')}`;
try {
  state.workflow = await request('/workflow');
  render();
  await refresh();
  if ($('case-select').options.length) {
    if ([...$('case-select').options].some(o => o.value === 'U03.01')) $('case-select').value = 'U03.01';
    await load();
  }
} catch (e) {
  note(`页面初始化：${e.message}`, true);
}
request('/health').then(d => {
  $('health').textContent = `数据库已连接 · ${d.published_documents}份资料 · ${d.ann}`;
}).catch(() => {
  $('health').textContent = '数据库未就绪 · 可查看保存记录';
});
await readiness();
setInterval(() => {
  if (state.busy) renderWorkflow(id => {
    state.node = id;
    render();
  });
}, 500);
