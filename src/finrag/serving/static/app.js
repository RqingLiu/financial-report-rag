/* No model credentials or provider requests in the browser. Untrusted text uses textContent. */
"use strict";
const $ = (id) => document.getElementById(id);
const nodes = [
  [
    "catalog_snapshot",
    "已入库年报",
    "Catalog / disclosure cutoff",
    "serving/store.py",
    "从 PostgreSQL 读取已发布到当前索引的年报元数据，按披露截止日限制可用资料。这里不是代码仓库的文件目录，也不是临时让模型搜索互联网。",
  ],
  [
    "query_plan",
    "问题规划",
    "DeepSeek / validated JSON",
    "planning.py",
    "将原问拆成证据需求和检索任务，验证公司、财年、排除条件与调用预算；必要时返回澄清。",
  ],
  [
    "embed_queries",
    "查询向量化",
    "Voyage / query embedding",
    "planned_retrieval.py",
    "将子查询编码为向量；缓存命中时可复用向量，不在页面或 trace 中记录向量本身。",
  ],
  [
    "retrieve",
    "分组检索",
    "pgvector / scoped searches",
    "planned_retrieval.py",
    "按任务、公司和报告财年执行受限检索。下方展示每次 SQL 搜索的实际 query、范围与命中；当前实现按任务顺序发起搜索。",
  ],
  [
    "fusion",
    "候选融合",
    "RRF / task interleaving",
    "planned_retrieval.py",
    "合并检索结果、去重并在任务之间交错分配候选。融合分数与原始向量距离、精排分数不能直接比较。",
  ],
  [
    "rerank",
    "候选精排",
    "DeepSeek / LLM reranking",
    "reranking.py",
    "对配置限定的候选重排；当前默认由 DeepSeek Flash 做真实 LLM 评分，并标记 need 与相关行。缓存命中时复用评分，不发新请求；这不是专用 CrossEncoder 模型。",
  ],
  [
    "context_build",
    "上下文构建",
    "Evidence / token budget",
    "rerank_context.py",
    "在证据与完整提示预算内选择内容，处理来源重复、表格上下文与裁剪，记录每一项被选中或排除的原因。",
  ],
  [
    "generation",
    "引用答案",
    "DeepSeek / cited sections",
    "answering.py",
    "根据实际上下文逐项回答，区分可支持、部分支持和缺证据。校验 need 和引用编号；事实与计算的正确性仍需评测。",
  ],
];
const tabs = [
  ["catalog", "年报清单"],
  ["planner", "Planner"],
  ["search", "检索记录"],
  ["ranking", "候选与精排"],
  ["context", "最终上下文"],
  ["answer", "引用答案"],
  ["events", "全部调用"],
  ["code-map", "代码地图"],
];
let state = {
  data: null,
  tab: "planner",
  inspectorTab: "overview",
  span: null,
  node: "query_plan",
  busy: false,
  historical: false,
};
let componentRefs = {};
let currentCatalog = null;
let focusedSymbol = null;
let rankingFilter = "",
  selectedOnly = false;

function el(tag, cls, text) {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  if (text !== undefined && text !== null) n.textContent = String(text);
  return n;
}
function tag(text, cls = "") {
  return el("span", `tag ${cls}`, text);
}
function note(text, error = false) {
  $("notice").hidden = !text;
  $("notice").textContent = text;
  $("notice").className = `notice${error ? " error" : ""}`;
}
function panel(title, file) {
  const p = el("article", "panel"),
    heading = el("div", "panel-heading");
  heading.append(el("h3", "", title));
  if (file) heading.append(el("span", "file-tag", file));
  p.append(heading);
  return p;
}
function empty(text) {
  const n = el("div", "empty");
  n.append(el("div", "empty-mark", "◇"), el("div", "", text));
  return n;
}
function raw(value, title = "查看实际输入 / 输出 JSON") {
  const d = el("details", "stage-details");
  d.append(
    el("summary", "", title),
    el("pre", "raw", JSON.stringify(value, null, 2)),
  );
  return d;
}
function seconds(n) {
  return Number.isFinite(n) ? `${n.toFixed(2)}s` : "—";
}
function stages(name) {
  return (state.data?.stages || []).filter((s) => !name || s.name === name);
}
function latest(name) {
  return stages(name).at(-1);
}
function plan() {
  return (
    state.data?.plan ||
    latest("evidence_regroup")?.outputs.validated_plan ||
    latest("query_plan")?.outputs.validated_plan
  );
}
function searches() {
  return state.data?.search_records?.length
    ? state.data.search_records
    : stages()
        .filter((s) => s.name.startsWith("retrieve."))
        .map((s) => ({
          ...s.inputs,
          ...s.outputs,
          duration_seconds: s.duration_seconds,
          status: s.status,
        }));
}
function context() {
  return (
    state.data?.retrieval?.metadata || latest("context_build")?.outputs || {}
  );
}
function evidence() {
  return state.data?.evidence?.length
    ? state.data.evidence
    : latest("context_build")?.outputs.evidence || [];
}
function ranks() {
  return (
    state.data?.retrieval?.ranked_hits ||
    latest("fusion")?.outputs.ranked_hits ||
    []
  );
}
function resultAnswer() {
  return state.data?.generation || latest("generation")?.outputs;
}
function statusClass(status) {
  return status === "error"
    ? "error"
    : status === "running"
      ? "running"
      : ["ok", "retrieved", "generated"].includes(status)
        ? "ok"
        : "";
}
function setBusy(busy) {
  state.busy = busy;
  for (const id of ["submit", "load", "refresh", "history"])
    $(id).disabled = busy;
  $("submit").firstElementChild.textContent = busy ? "查询执行中…" : "运行查询";
}

function render() {
  const d = state.data;
  $("run-title").textContent =
    d?.inputs?.original_question || "一次查询，八个可观察的阶段";
  $("run-label").textContent = state.historical
    ? "SAVED TRACE / READ ONLY"
    : d
      ? "LIVE QUERY / OBSERVED EVENTS"
      : "PIPELINE AT A GLANCE";
  $("run-meta").textContent = d
    ? `截止日 ${d.inputs?.as_of || "—"} · ${d.query_id || "等待分配 ID"} · ${d.created_at ? new Date(d.created_at).toLocaleString() : ""}`
    : "点击流程节点查看组件职责；运行后可检查实际输入、输出和耗时。";
  $("run-status").textContent = (d?.status || "idle").toUpperCase();
  $("run-status").className = `status-pill ${statusClass(d?.status)}`;
  $("session-badge").textContent = state.historical
    ? "历史记录 · 不消耗 API"
    : state.busy
      ? "实时事件接收中"
      : d
        ? "运行已结束"
        : "准备就绪";
  renderGraph();
  renderInspector();
  const cost =
    stages("llm_call").reduce(
      (n, s) => n + Number(s.outputs.peak_list_cost_usd || 0),
      0,
    ) +
    stages("embed_queries")
      .flatMap((s) => s.outputs.usage_events || [])
      .reduce((n, e) => n + Number(e.peak_list_cost_usd || 0), 0);
  const duration = stages()
    .filter((s) => !s.parent_id)
    .reduce((n, s) => n + (s.duration_seconds || 0), 0);
  $("stats").replaceChildren();
  const stats = [
    [searches().length || "—", "实际检索次数"],
    [
      ranks().length || latest("fusion")?.outputs.retained || "—",
      "融合后候选数",
    ],
    [evidence().length || "—", "最终证据项"],
    [context().evidence_tokens ?? "—", "证据 tokens · 代理计数"],
    [
      d ? seconds(duration) : "—",
      `阶段耗时合计 · 记录调用约 $${cost.toFixed(4)}`,
    ],
  ];
  stats.forEach(([v, l]) => {
    const n = el("div", "stat");
    n.append(el("div", "stat-value", v), el("div", "stat-label", l));
    $("stats").append(n);
  });
  $("tabs").replaceChildren();
  tabs.forEach(([id, label]) => {
    const b = el("button", `tab${state.tab === id ? " active" : ""}`, label);
    b.onclick = () => {
      state.tab = id;
      render();
    };
    $("tabs").append(b);
  });
  $("content").replaceChildren(views[state.tab]());
}

let renderPending = false;
function scheduleRender() {
  if (renderPending) return;
  renderPending = true;
  requestAnimationFrame(() => {
    renderPending = false;
    render();
  });
}
const nodeView = {
  query_plan: "planner",
  retrieve: "search",
  fusion: "ranking",
  rerank: "ranking",
  context_build: "context",
  generation: "answer",
  catalog_snapshot: "catalog",
  embed_queries: "events",
};
const graph = { scale: 1, x: 0, y: 0, width: 920, height: 330, fitted: false };
function layoutGraph(fit = false) {
  const viewport = $("graph-viewport");
  const narrow = viewport.clientWidth < 520;
  const coordinates = narrow
    ? [
        [15, 20],
        [245, 20],
        [245, 180],
        [15, 180],
        [15, 340],
        [245, 340],
        [245, 500],
        [15, 500],
      ]
    : [
        [15, 30],
        [245, 30],
        [475, 30],
        [705, 30],
        [705, 190],
        [475, 190],
        [245, 190],
        [15, 190],
      ];
  graph.width = narrow ? 465 : 920;
  graph.height = narrow ? 650 : 330;
  viewport.classList.toggle("narrow-graph", narrow);
  viewport.style.height = narrow
    ? `${Math.round(graph.height * Math.min((viewport.clientWidth - 12) / graph.width, 1)) + 20}px`
    : "";
  $("graph-world").style.width = `${graph.width}px`;
  $("graph-world").style.height = `${graph.height}px`;
  const svg = $("edges");
  svg.setAttribute("viewBox", `0 0 ${graph.width} ${graph.height}`);
  svg.style.width = `${graph.width}px`;
  svg.style.height = `${graph.height}px`;
  svg
    .querySelector(".edge")
    .setAttribute(
      "d",
      narrow
        ? "M220 75H245 M347 130V180 M245 235H220 M117 290V340 M220 395H245 M347 450V500 M245 555H220"
        : "M220 85H245 M450 85H475 M680 85H705 M807 140V190 M705 245H680 M475 245H450 M245 245H220",
    );
  $("pipeline")
    .querySelectorAll(".node")
    .forEach((n, i) => {
      n.style.left = `${coordinates[i][0]}px`;
      n.style.top = `${coordinates[i][1]}px`;
    });
  if (fit || !graph.fitted) {
    graph.scale = Math.min(
      (viewport.clientWidth - 12) / graph.width,
      (viewport.clientHeight - 28) / graph.height,
      1.15,
    );
    graph.x = (viewport.clientWidth - graph.width * graph.scale) / 2;
    graph.y = Math.max(
      0,
      (viewport.clientHeight - 26 - graph.height * graph.scale) / 2,
    );
    graph.fitted = true;
  }
  transformGraph();
}
function transformGraph() {
  $("graph-world").style.transform =
    `translate(${graph.x}px,${graph.y}px) scale(${graph.scale})`;
  $("zoom-label").textContent = `${Math.round(graph.scale * 100)}%`;
}
function zoomGraph(factor) {
  const v = $("graph-viewport"),
    next = Math.max(0.35, Math.min(1.8, graph.scale * factor));
  const cx = v.clientWidth / 2,
    cy = v.clientHeight / 2;
  graph.x = cx - ((cx - graph.x) * next) / graph.scale;
  graph.y = cy - ((cy - graph.y) * next) / graph.scale;
  graph.scale = next;
  transformGraph();
}
function renderGraph() {
  if (!$("pipeline").children.length)
    nodes.forEach(([name, label, tech], i) => {
      const b = el("button", "node");
      b.dataset.node = name;
      b.append(
        el("span", "node-number", String(i + 1).padStart(2, "0")),
        el("span", "node-state"),
        el("strong", "", label),
        el("small", "", tech),
        el("span", "node-time"),
      );
      b.onclick = () => {
        state.node = name;
        state.span = null;
        focusedSymbol = null;
        state.tab = nodeView[name];
        render();
      };
      $("pipeline").append(b);
    });
  nodes.forEach(([name, label], i) => {
    const b = $("pipeline").children[i],
      span = latest(name);
    const status =
      span?.status ||
      (state.data && state.data.status !== "running" ? "skipped" : "pending");
    const ref = componentRefs[name]?.[0];
    if (ref) {
      b.querySelector("small").textContent =
        `${ref.path.split("/").at(-1)} · ${ref.symbol}`;
      b.title = `${ref.path}:${ref.start_line}\n${ref.symbol} — ${ref.role}`;
    }
    b.className = `node ${status}${state.node === name ? " active" : ""}`;
    b.setAttribute("aria-label", `${label}：${status}`);
    b.setAttribute("aria-pressed", String(state.node === name));
    const count = stages().filter((s) => s.parent_id === span?.id).length;
    b.querySelector(".node-time").textContent = span
      ? `${seconds(span.duration_seconds)}${count ? ` · ${count} 个子调用` : ""}`
      : status === "skipped"
        ? "本次未执行"
        : "等待执行";
  });
  layoutGraph();
}
function tree(value, key = "payload", depth = 0) {
  if (value !== null && typeof value === "object") {
    const entries = Object.entries(value),
      d = el("details", "tree");
    d.open = depth < 1;
    d.append(
      el(
        "summary",
        "",
        `${key} ${Array.isArray(value) ? `[${entries.length}]` : `{${entries.length}}`}`,
      ),
    );
    const children = el("div", "tree-children");
    // Lazy materialization prevents large candidate payloads blocking each SSE update.
    let built = false;
    const build = () => {
      if (built || !d.open) return;
      built = true;
      entries.forEach(([k, v]) => children.append(tree(v, k, depth + 1)));
    };
    d.addEventListener("toggle", build);
    d.append(children);
    build();
    return d;
  }
  return el(
    "div",
    "tree-value",
    `${key}: ${value === null ? "null" : String(value)}`,
  );
}
const codeCache = new Map();
async function sourcePanel(body, component, span, symbol = null) {
  body.append(
    el(
      "p",
      "source-note",
      span?.source
        ? `本次记录的调用点：${span.source.path}:${span.source.line} · ${span.source.function}`
        : "此 trace 未记录执行源码身份。以下是当前检出版本的组件参考，不代表当时运行的源码。",
    ),
  );
  try {
    if (!codeCache.has(component))
      codeCache.set(
        component,
        jsonFetch(`/code/${encodeURIComponent(component)}`),
      );
    const data = await codeCache.get(component);
    if (!body.isConnected) return;
    data.snippets
      .filter((sn) => !symbol || sn.symbol === symbol)
      .forEach((sn) => {
        const block = el("section", "code-block");
        const sameFile = span?.source?.path === sn.path;
        const version = sameFile
          ? span.source.sha256 === sn.sha256
            ? "文件哈希与该次调用记录一致"
            : "当前文件已不同于该次调用记录"
          : "当前实现参考 · 非历史快照";
        block.append(
          el(
            "div",
            "code-title",
            `${sn.path}:${sn.start_line} · ${sn.symbol}\n${sn.role}\n${version}`,
          ),
        );
        const pre = el("pre", "code-lines");
        sn.text.split("\n").forEach((line, i) => {
          const row = el("span", "code-line");
          row.append(
            el("span", "line-number", sn.start_line + i),
            document.createTextNode(line),
          );
          pre.append(row);
        });
        block.append(pre);
        if (sn.truncated)
          block.append(el("p", "source-note", "函数较长，仅展示前 140 行。"));
        body.append(block);
      });
  } catch {
    body.append(empty("当前组件源码暂不可读。"));
    codeCache.delete(component);
  }
}
function currentSpan() {
  const root = latest(state.node);
  const children = stages().filter((s) => s.parent_id === root?.id);
  return [root, ...children].find((s) => s?.id === state.span) || root;
}
function renderInspector() {
  const n = nodes.find((n) => n[0] === state.node),
    root = latest(state.node),
    children = stages().filter((s) => s.parent_id === root?.id),
    span = currentSpan();
  $("step-title").textContent = n[1];
  $("step-meta").replaceChildren(
    tag(span?.name || state.node),
    tag(span?.status || "未执行"),
    tag(seconds(span?.duration_seconds)),
  );
  const calls = $("call-list");
  calls.replaceChildren();
  if (children.length) {
    const select = el("select", "call-select");
    select.setAttribute("aria-label", "选择实际子调用");
    [root, ...children].forEach((s, i) => {
      const o = el(
        "option",
        "",
        i
          ? `↳ ${s.name} · ${s.inputs.purpose || s.inputs.query?.slice(0, 45) || ""} · ${seconds(s.duration_seconds)}`
          : "阶段汇总",
      );
      o.value = s.id;
      select.append(o);
    });
    select.value = span.id;
    select.onchange = () => {
      state.span = select.value;
      focusedSymbol = null;
      renderInspector();
    };
    calls.append(select);
  }
  const nav = $("inspector-tabs");
  nav.replaceChildren();
  [
    ["overview", "概览"],
    ["input", "Input"],
    ["output", "Output"],
    ["code", "代码"],
  ].forEach(([id, label]) => {
    const b = el("button", state.inspectorTab === id ? "active" : "", label);
    b.setAttribute("aria-pressed", String(state.inspectorTab === id));
    b.onclick = () => {
      state.inspectorTab = id;
      focusedSymbol = null;
      renderInspector();
    };
    nav.append(b);
  });
  const body = $("inspector-body");
  body.replaceChildren();
  if (state.inspectorTab === "code") {
    const component =
      span?.name === "llm_call"
        ? "llm_call"
        : state.node === "rerank" && root?.inputs.method === "crossencoder"
          ? "crossencoder"
          : state.node;
    // A detached per-selection container prevents a slow code response appending
    // to another node's inspector after the user switches tabs.
    const code = el("div");
    body.append(code);
    sourcePanel(code, component, span, focusedSymbol);
    return;
  }
  if (state.inspectorTab === "input" || state.inspectorTab === "output") {
    const value = span?.[state.inspectorTab === "input" ? "inputs" : "outputs"];
    body.append(
      el(
        "p",
        "source-note",
        state.inspectorTab === "input"
          ? "已记录的业务输入。原始系统提示词与服务配置不在此视图展示。"
          : "已记录的阶段输出。展开字段查看具体内容；候选文本截断会另行标记。",
      ),
    );
    if (value && Object.keys(value).length) body.append(tree(value));
    else
      body.append(
        empty(
          span
            ? "此步骤没有记录可展示的字段；可展开子调用检查。"
            : "本次未执行该步骤，暂无数据。",
        ),
      );
    if (span?.name === "llm_call" && state.inspectorTab === "output")
      body.append(
        el(
          "p",
          "io-note",
          "此处展示模型、用量和结束状态。模型原文未透传；经校验的计划 / 评分 / 答案在父阶段 Output 中。",
        ),
      );
    return;
  }
  body.append(el("p", "", n[4]));
  if (span) {
    [
      ["实际调用", span.name],
      [
        "开始时间",
        span.started_at ? new Date(span.started_at).toLocaleTimeString() : "—",
      ],
      ["执行耗时", seconds(span.duration_seconds)],
    ].forEach(([k, v]) => {
      const row = el("div", "metric");
      row.append(el("span", "", k), el("strong", "", v));
      body.append(row);
    });
    if (span.error_type)
      body.append(el("p", "io-note", `执行失败：${span.error_type}`));
    if (root?.outputs.cached)
      body.append(
        el("p", "io-note", "缓存命中：没有新的模型调用并不代表漏记了步骤。"),
      );
    const summary = stageSummary(state.node);
    if (summary) body.append(el("p", "io-note", summary));
    if (span.source)
      body.append(
        el(
          "p",
          "source-note",
          `已记录调用点：${span.source.path}:${span.source.line} · ${span.source.function}`,
        ),
      );
  } else body.append(empty("该步骤尚未执行。仍可切换“代码”查看实现。"));
  body.append(codeLinks(state.node));
  const jump = el(
    "button",
    "jump-button",
    `查看${{ catalog: "年报清单", planner: "计划与子查询", search: "全部搜索命中", ranking: "候选排序与去留", context: "最终证据", answer: "引用答案", events: "执行记录" }[nodeView[state.node]]} ↓`,
  );
  jump.onclick = () => {
    state.tab = nodeView[state.node];
    render();
    $("content").scrollIntoView({ behavior: "smooth", block: "start" });
  };
  body.append(jump);
}
function stageSummary(name) {
  const s = latest(name);
  if (!s) return "";
  if (name === "catalog_snapshot")
    return `本次目录包含 ${s.outputs.documents ?? "—"} 份已发布年报。`;
  if (name === "query_plan")
    return `${plan()?.needs?.length || 0} 项证据需求 · ${plan()?.tasks?.length || 0} 个检索任务 · action: ${plan()?.action || "—"}`;
  if (name === "embed_queries")
    return `${s.inputs.queries?.length || 0} 条去重查询 · ${s.inputs.model || "embedding"} · 向量本身不记录。`;
  if (name === "retrieve")
    return `${searches().length} 次已记录搜索；子调用包含每次 query、公司 / 财年、k 和命中。`;
  if (name === "fusion")
    return `${s.outputs.raw_candidates ?? "—"} 个去重候选，保留 ${s.outputs.retained ?? "—"} 个。`;
  if (name === "rerank")
    return `${s.inputs.candidates ?? "—"} 个精排候选 · method: ${s.inputs.method || "—"}。分数为模型判断。`;
  if (name === "context_build")
    return `${evidence().length} 项最终证据 · ${context().evidence_tokens ?? "—"} / ${context().evidence_token_cap ?? "—"} tokens。`;
  return "答案基于本次选定的证据生成。引用标识通过校验仍不等于事实正确。";
}
$("zoom-in").onclick = () => zoomGraph(1.2);
$("zoom-out").onclick = () => zoomGraph(1 / 1.2);
$("fit").onclick = () => layoutGraph(true);
let drag = null;
$("graph-viewport").addEventListener("pointerdown", (e) => {
  if (e.target.closest("button") || e.button !== 0) return;
  drag = { x: e.clientX, y: e.clientY, gx: graph.x, gy: graph.y };
  e.currentTarget.setPointerCapture(e.pointerId);
  e.currentTarget.classList.add("dragging");
});
$("graph-viewport").addEventListener("pointermove", (e) => {
  if (!drag) return;
  graph.x = drag.gx + e.clientX - drag.x;
  graph.y = drag.gy + e.clientY - drag.y;
  transformGraph();
});
for (const name of ["pointerup", "pointercancel"])
  $("graph-viewport").addEventListener(name, (e) => {
    drag = null;
    e.currentTarget.classList.remove("dragging");
  });
new ResizeObserver(() => layoutGraph(true)).observe($("graph-viewport"));

function openSource(component, ref) {
  // Main phases select the matching graph node; shared files use the source dialog.
  if (nodes.some((n) => n[0] === component)) {
    state.node = component;
    state.span = null;
    state.inspectorTab = "code";
    focusedSymbol = ref.symbol;
    render();
    $("inspector-body").scrollTop = 0;
    document
      .querySelector(".inspector")
      .scrollIntoView({ behavior: "smooth", block: "nearest" });
  } else {
    const body = el("div");
    openDialog(`${ref.path}:${ref.start_line}`, [body]);
    sourcePanel(body, component, null, ref.symbol);
  }
}
function codeLinks(component) {
  const box = el("section", "code-links");
  box.append(el("h4", "", "关联仓库文件 / 函数"));
  const refs = componentRefs[component] || [];
  if (!refs.length) {
    box.append(el("p", "muted small", "代码地图加载中…"));
    return box;
  }
  refs.forEach((ref) => {
    const b = el("button", "code-reference");
    b.append(
      el("span", "code-ref-path", `${ref.path}:${ref.start_line}`),
      el("strong", "", `${ref.symbol} ↗`),
      el("span", "muted", ref.role),
    );
    b.onclick = () => openSource(component, ref);
    box.append(b);
  });
  return box;
}
function codeMapView() {
  const root = el("div"),
    intro = panel("工作流 → 仓库代码");
  intro.append(
    el(
      "p",
      "muted",
      "所有路径均相对于 financial-report-rag/ 仓库根目录。一个步骤通常调用多个文件；runtime.execute 负责总编排，具体实现与共享模型适配器分开。点击函数查看源码；在编辑器中可用 Cmd+P 输入路径定位。行号来自当前检出版本，不是历史执行快照；关联函数涉及缓存与可选分支，不表示本次全部执行。",
    ),
  );
  root.append(intro);
  const groups = [
    ["entry", "入口与总编排"],
    ...nodes.map((n) => [n[0], n[1]]),
    ["ingestion", "年报入库（不属于在线查询步骤）"],
    ["crossencoder", "可选专用 reranker（当前默认未启用）"],
  ];
  groups.forEach(([component, label]) => {
    const p = panel(label),
      wrap = el("div", "table-wrap"),
      table = el("table"),
      head = el("tr");
    ["仓库路径 / 函数", "负责什么"].forEach((t) =>
      head.append(el("th", "", t)),
    );
    const thead = el("thead");
    thead.append(head);
    table.append(thead);
    const tbody = el("tbody");
    (componentRefs[component] || []).forEach((ref) => {
      const row = el("tr"),
        file = el("td"),
        b = el("button", "source-link");
      b.append(
        el("span", "code-ref-path", `${ref.path}:${ref.start_line}`),
        el("strong", "", `${ref.symbol} ↗`),
      );
      b.onclick = () => openSource(component, ref);
      file.append(b);
      row.append(file, el("td", "", ref.role));
      tbody.append(row);
    });
    table.append(tbody);
    wrap.append(table);
    p.append(wrap);
    root.append(p);
  });
  const data = panel("数据与配置的位置");
  [
    ["configs/serving.json", "当前检索、精排、ANN 与上下文预算配置"],
    [
      "data/sources.jsonl / data/generalization/sources.jsonl",
      "已下载语料的来源元数据；已跟踪进 Git",
    ],
    ["data/raw/*.html", "本地年报 HTML；被 gitignore，GitHub 仓库不包含原文"],
    [
      "PostgreSQL: documents + publications + blocks + chunks",
      "已入库年报元数据、发布索引、原文块与带向量的 chunk",
    ],
    ["logs/serving/<query_id>.json", "本机实际 trace；被 gitignore"],
  ].forEach(([path, role]) => {
    const line = el("div", "data-location");
    line.append(el("code", "", path), el("span", "muted", role));
    data.append(line);
  });
  root.append(data);
  return root;
}
function recordedCatalog() {
  const recorded = latest("catalog_snapshot")?.outputs.catalog;
  if (recorded) return { rows: recorded, source: "本次 trace 记录的目录快照" };
  const plannerSpan = latest("query_plan");
  const child = stages().find(
    (s) =>
      s.parent_id === plannerSpan?.id && s.inputs?.business_payload?.catalog,
  );
  return child
    ? {
        rows: child.inputs.business_payload.catalog,
        source:
          "同次 Planner 调用实际收到的目录；可能因目录预算而收窄，并不一定是完整数据库",
      }
    : null;
}
function catalogView() {
  const root = el("div"),
    intro = panel("已入库年报 · Published filings");
  intro.append(
    el(
      "p",
      "muted",
      "查询从 PostgreSQL 已发布索引读取可用年报元数据。原始 HTML 通常保存在本机 data/raw/，已被 gitignore；GitHub 上公开的是代码与来源清单，不能把二者当作同一目录。这里没有联网搜索或模型造数据。",
    ),
  );
  const button = el(
    "button",
    "secondary",
    "查看当前数据库入库清单（不调用模型）",
  );
  button.onclick = async () => {
    button.disabled = true;
    try {
      const asof = state.data?.inputs.as_of || $("as-of").value;
      currentCatalog = await jsonFetch(
        `/catalog?as_of=${encodeURIComponent(asof)}`,
      );
      state.tab = "catalog";
      render();
    } catch (e) {
      note(`入库清单读取失败：${e.message}`, true);
      button.disabled = false;
    }
  };
  intro.append(button);
  root.append(intro);
  const recorded = recordedCatalog();
  let rows = [],
    label;
  if (currentCatalog) {
    rows = currentCatalog.filings;
    label = `当前数据库 · 截止 ${currentCatalog.as_of} · ${currentCatalog.documents} 份${currentCatalog.truncated ? `（仅显示前 ${currentCatalog.returned_documents} 份）` : ""}（不是历史执行快照）`;
  } else if (recorded) {
    rows = recorded.rows.flatMap((c) =>
      (c.reports || []).map((r) => ({
        ...r,
        ticker: c.ticker,
        fiscal_year: r.report_fy,
      })),
    );
    label = recorded.source;
  }
  if (!label) {
    root.append(
      empty("旧 trace 未记录具体年报列表；可按上方按钮读取当前数据库。"),
    );
    return root;
  }
  const p = panel(label),
    wrap = el("div", "table-wrap"),
    table = el("table"),
    head = el("tr");
  ["公司 / 文档", "报告财年 / 期末", "公开日期", "原文位置"].forEach((t) =>
    head.append(el("th", "", t)),
  );
  const thead = el("thead");
  thead.append(head);
  table.append(thead);
  const body = el("tbody");
  rows.forEach((r) => {
    const tr = el("tr"),
      path = el("td");
    if (r.local_raw_path) path.append(el("code", "", r.local_raw_path));
    const link = sourceLink(r.source_url);
    if (link) path.append(link);
    if (!path.children.length) path.textContent = "该次目录未记录路径 / URL";
    tr.append(
      el("td", "", `${r.ticker} · ${r.id}`),
      el("td", "", `FY${r.fiscal_year} · ${r.period_end}`),
      el("td", "", r.filed_at),
      path,
    );
    body.append(tr);
  });
  table.append(body);
  wrap.append(table);
  p.append(wrap);
  root.append(p, codeLinks("catalog_snapshot"));
  return root;
}
$("open-code-map").onclick = () => {
  state.tab = "code-map";
  render();
  $("content").scrollIntoView({ behavior: "smooth", block: "start" });
};

function planner() {
  const root = el("div"),
    p = plan();
  if (!p)
    return empty("Planner 尚未返回有效计划。可在执行日志查看失败或修复调用。");
  const summary = panel("问题范围与时间口径", "planning.py");
  summary.append(tag(`action: ${p.action}`, "green"));
  (p.companies || []).forEach((c) =>
    summary.append(
      tag(
        `${c.ticker} · ${(c.report_years || []).map((y) => `FY${y}`).join(" / ")}`,
      ),
    ),
  );
  summary.append(el("p", "muted", p.period_interpretation || p.period_basis));
  [...(p.clarification_questions || []), ...(p.limitations || [])].forEach(
    (t) => summary.append(el("p", "", t)),
  );
  if (p.excluded_tickers?.length)
    summary.append(el("p", "", `排除公司：${p.excluded_tickers.join(", ")}`));
  root.append(summary);
  const grid = el("div", "grid-two"),
    needs = panel("证据目标 · Needs"),
    tasks = panel("检索任务 · Tasks");
  (p.needs || []).forEach((n) => {
    const r = el("div", "need");
    r.append(el("span", "need-id", n.id), el("span", "", n.description));
    needs.append(r);
  });
  (p.tasks || []).forEach((t) => {
    const r = el("div", "mini");
    r.append(
      tag(t.id, "green"),
      tag((t.tickers || []).join(" + ")),
      tag((t.need_ids || []).join(", ")),
      el("p", "muted small", `route: ${t.route}`),
    );
    (t.dense_queries || []).forEach((q) =>
      r.append(el("div", "query-text", q)),
    );
    if (t.keywords?.length)
      r.append(el("p", "muted", `关键词：${t.keywords.join(" · ")}`));
    tasks.append(r);
  });
  grid.append(needs, tasks);
  root.append(grid, raw(p, "查看验证后的 QueryPlan"));
  return root;
}
function searchView() {
  const root = el("div"),
    rows = searches();
  if (!rows.length)
    return empty(
      "尚无搜索记录。每条记录对应一次实际的公司 / 财年 / query 检索。",
    );
  const intro = panel(
    `${rows.length} 次受范围约束的检索`,
    "planned_retrieval.py",
  );
  intro.append(
    el(
      "p",
      "muted",
      "dense 的原始 score 为向量距离（越小越近）；RRF 融合分数越大越靠前。不同类型分数不可直接比较。",
    ),
  );
  root.append(intro);
  rows.forEach((r, i) => {
    const p = panel(
      `搜索 ${String(i + 1).padStart(2, "0")} · ${r.task_id}`,
      r.method,
    );
    p.append(
      tag((r.group || []).join(" · ")),
      tag(`k=${r.k}`),
      tag(`${(r.hits || []).length} hits`),
      tag(seconds(r.duration_seconds)),
      el("div", "query-text", r.query),
      el("p", "mono muted", (r.documents || []).join(" · ")),
    );
    const d = el("details", "stage-details");
    d.append(el("summary", "", `查看命中片段（${(r.hits || []).length}）`));
    (r.hits || []).forEach((h, j) => {
      const b = el("button", "evidence-card");
      b.append(
        tag(`#${j + 1}`),
        tag(String(h.score)),
        el("strong", "", `${h.chunk.document_id} · ${h.chunk.section}`),
        el("div", "preview", h.chunk.text.slice(0, 240)),
      );
      b.onclick = () => showHit(h);
      d.append(b);
    });
    p.append(d);
    root.append(p);
  });
  return root;
}
function ranking() {
  const root = panel(
      "从融合候选到最终上下文",
      "reranking.py → rerank_context.py",
    ),
    rows = ranks();
  root.append(
    el(
      "p",
      "muted",
      "粗排序号为融合与任务交错后的顺序；grade 为模型相关性等级，need 为模型匹配的证据目标。点击一行查看文本和选择原因。未进入精排的候选以 — 标记。",
    ),
  );
  if (!rows.length) {
    root.append(empty("候选融合完成后显示排名与去留。"));
    return root;
  }
  const tools = el("div", "tools"),
    input = el("input"),
    select = el("select");
  input.placeholder = "筛选公司、章节或文本…";
  input.value = rankingFilter;
  input.setAttribute("aria-label", "筛选候选");
  [
    ["all", "全部候选"],
    ["selected", "仅最终入选"],
  ].forEach(([v, t]) => {
    const o = el("option", "", t);
    o.value = v;
    select.append(o);
  });
  select.value = selectedOnly ? "selected" : "all";
  select.setAttribute("aria-label", "候选范围");
  const wrap = el("div", "table-wrap");
  tools.append(input, select);
  root.append(tools, wrap);
  function draw() {
    const table = el("table"),
      head = el("tr");
    [
      "粗排 #",
      "公司 / 报告",
      "章节",
      "融合 score",
      "精排 grade",
      "need",
      "上下文决定",
    ].forEach((t) => head.append(el("th", "", t)));
    const thead = el("thead");
    thead.append(head);
    const body = el("tbody");
    const grades = latest("rerank")?.outputs.scores || {},
      decisions = context().decisions || [];
    rows.forEach((h, i) => {
      const c = h.chunk,
        ds = decisions.filter((d) => d.parent_chunk_id === c.id),
        chosen = ds.some((d) => d.decision === "selected"),
        g = grades[c.id];
      if (selectedOnly && !chosen) return;
      if (
        rankingFilter &&
        !`${c.document_id} ${c.section} ${c.text}`
          .toLowerCase()
          .includes(rankingFilter.toLowerCase())
      )
        return;
      const tr = el("tr");
      tr.dataset.chunk = c.id;
      tr.tabIndex = 0;
      [
        String(i + 1),
        c.document_id,
        c.section,
        Number(h.score).toFixed(6),
        typeof g === "number" ? g.toFixed(3) : (g?.s ?? "—"),
        g?.n?.join(", ") || "—",
        chosen
          ? "✓ selected"
          : ds.map((d) => d.decision).join(", ") ||
            (g?.s === 0
              ? "相关性等级为 0"
              : g !== undefined
                ? "未选用"
                : "未进入精排"),
      ].forEach((t, j) =>
        tr.append(
          el(
            "td",
            j === 0 ? "rank" : j === 6 && chosen ? "selected-dot" : "",
            t,
          ),
        ),
      );
      const open = () =>
        showHit(h, { coarse_rank: i + 1, rerank: g, context_decisions: ds });
      tr.onclick = open;
      tr.onkeydown = (e) => {
        if (e.key === "Enter") open();
      };
      body.append(tr);
    });
    table.append(thead, body);
    wrap.replaceChildren(table);
  }
  input.oninput = () => {
    rankingFilter = input.value;
    draw();
  };
  select.onchange = () => {
    selectedOnly = select.value === "selected";
    draw();
  };
  draw();
  return root;
}
function contextView() {
  const root = el("div"),
    rows = evidence(),
    meta = context(),
    info = panel("实际提供给生成模型的证据", "rerank_context.py");
  info.append(
    el(
      "p",
      "muted",
      `证据预算：${meta.evidence_tokens ?? "—"} / ${meta.evidence_token_cap ?? "—"} tokens；完整提示：${meta.full_prompt_proxy_tokens ?? "—"} / ${meta.full_prompt_cap ?? "—"} 代理 tokens。证据编号可从答案中点击打开。`,
    ),
  );
  root.append(info);
  if (!rows.length) {
    root.append(empty("尚未构建上下文，或本次没有获得足够证据。"));
    return root;
  }
  const grid = el("div", "evidence-list");
  rows.forEach((e) => {
    const b = el("button", "evidence-card");
    b.append(
      tag(e.citation, "green"),
      tag(e.ticker),
      el("strong", "", `${e.document_id} · 披露 ${e.filed_at}`),
      el("div", "preview", e.text.slice(0, 220)),
    );
    b.onclick = () => showEvidence(e);
    grid.append(b);
  });
  root.append(grid, raw(meta, "查看上下文预算与所有取舍决策"));
  return root;
}
function answerView() {
  const root = el("div"),
    gen = resultAnswer();
  if (!gen?.answer) {
    const p = panel("引用答案", "answering.py");
    p.append(
      empty(
        state.data?.status === "retrieved"
          ? "本次仅执行检索，未调用答案生成。切换执行范围后可运行新的完整查询。"
          : "尚无答案。可先查看 Planner、候选和最终证据。",
      ),
    );
    return p;
  }
  const structured = gen.structured_answer;
  if (structured?.sections)
    structured.sections.forEach((s) => {
      const p = panel(
        `${s.need_id} · ${plan()?.needs?.find((n) => n.id === s.need_id)?.description || "回答"}`,
      );
      p.append(tag(s.status, s.status === "supported" ? "green" : "orange"));
      const text = el("div", "answer-text");
      appendCitations(text, s.answer);
      p.append(text);
      (s.missing_evidence || []).forEach((t) =>
        p.append(el("p", "muted", `缺项：${t}`)),
      );
      root.append(p);
    });
  else {
    const p = panel("答案");
    const text = el("div", "answer-text");
    appendCitations(text, gen.answer);
    p.append(text);
    root.append(p);
  }
  if (structured?.limitations?.length) {
    const p = panel("范围与口径");
    structured.limitations.forEach((t) => p.append(el("p", "muted", t)));
    root.append(p);
  }
  return root;
}
function appendCitations(parent, text) {
  const parts = String(text).split(/(\[E\d+\])/g);
  parts.forEach((t) => {
    if (/^\[E\d+\]$/.test(t)) {
      const b = el("button", "citation", t);
      b.onclick = () => {
        const e = evidence().find((e) => e.citation === t.slice(1, -1));
        if (e) showEvidence(e);
        else note("该引用没有对应的本次证据。");
      };
      parent.append(b);
    } else parent.append(document.createTextNode(t));
  });
}
function eventView() {
  const root = panel("真实执行事件与嵌套调用", "tracing.py");
  root.append(
    el(
      "p",
      "muted",
      "时间来自服务端 span；嵌套调用时间已包含在父阶段中。缓存命中的阶段可能没有新的模型调用。API 费用为 trace 中本次记录的调用估算，不能替代服务商账单。",
    ),
  );
  if (!stages().length) {
    root.append(empty("尚无事件。"));
    return root;
  }
  stages().forEach((s) => {
    const details = el("details"),
      r = el("summary", `event-row${s.parent_id ? " nested" : ""}`);
    r.append(
      el("span", "mono", s.name),
      el("span", "", s.status),
      el("span", "mono", seconds(s.duration_seconds)),
    );
    details.append(r, el("pre", "raw", JSON.stringify(s, null, 2)));
    root.append(details);
  });
  return root;
}
const views = {
  catalog: catalogView,
  "code-map": codeMapView,
  planner,
  search: searchView,
  ranking,
  context: contextView,
  answer: answerView,
  events: eventView,
};

function openDialog(title, children) {
  $("evidence-title").textContent = title;
  $("evidence-body").replaceChildren(...children);
  if (!$("evidence-dialog").open) $("evidence-dialog").showModal();
}
function sourceLink(url) {
  try {
    const u = new URL(url);
    if (u.protocol !== "https:") return null;
    const a = el("a", "small", "打开原始年报 ↗");
    a.href = u.href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
    return a;
  } catch {
    return null;
  }
}
function showEvidence(e) {
  const info = el(
      "p",
      "muted small",
      `${e.ticker} · 报告 FY${e.fiscal_year} · 期末 ${e.period_end} · 公开 ${e.filed_at}`,
    ),
    children = [info],
    link = sourceLink(e.source_url);
  if (link) children.push(link);
  children.push(
    el("p", "mono muted", e.chunk_id),
    el("pre", "source-text", e.text),
    raw(e.source_spans, "来源 block 与字符范围"),
  );
  if (e.text_truncated)
    children.push(
      el("p", "muted", "浏览器视图截断了超长文本，完整内容仍在本地 trace。"),
    );
  openDialog(`${e.citation} · ${e.document_id}`, children);
}
function showHit(h, extra) {
  const c = h.chunk;
  const children = [
    el("p", "mono muted", c.id),
    el("pre", "source-text", c.text),
  ];
  if (c.text_truncated)
    children.push(
      el("p", "muted", "此视图为截断片段；最终入选证据可在“最终上下文”查看。"),
    );
  if (extra) children.push(raw(extra, "排名与选择详情"));
  const e = evidence().find((e) => e.chunk_id === c.id);
  if (e) {
    const b = el("button", "secondary", `打开生成使用的 ${e.citation} 证据`);
    b.onclick = () => showEvidence(e);
    children.push(b);
  }
  openDialog(`${c.document_id} · ${c.section}`, children);
}
$("close-evidence").onclick = () => $("evidence-dialog").close();

async function jsonFetch(url, options) {
  const r = await fetch(url, options);
  let d;
  try {
    d = await r.json();
  } catch {
    throw new Error(`HTTP ${r.status}`);
  }
  if (!r.ok)
    throw new Error(
      typeof d.detail === "string" ? d.detail : JSON.stringify(d.detail),
    );
  return d;
}
async function refreshHistory() {
  try {
    const { traces } = await jsonFetch("/traces"),
      previous = $("history").value;
    $("history").replaceChildren();
    const initial = el(
      "option",
      "",
      traces.length ? "选择一条记录…" : "暂无历史 trace",
    );
    initial.value = "";
    $("history").append(initial);
    traces.forEach((r) => {
      const o = el(
        "option",
        "",
        `${new Date(r.modified_at * 1000).toLocaleString()} · ${r.query_id.slice(0, 8)}`,
      );
      o.value = r.query_id;
      $("history").append(o);
    });
    $("history").value = previous;
  } catch (e) {
    note(`历史列表加载失败：${e.message}`, true);
  }
}
$("refresh").onclick = refreshHistory;
$("load").onclick = async () => {
  const id = $("history").value;
  if (!id) {
    note("先选择一条历史记录。");
    return;
  }
  try {
    state.data = await jsonFetch(`/traces/${encodeURIComponent(id)}`);
    currentCatalog = null;
    focusedSymbol = null;
    state.historical = true;
    state.tab = "planner";
    state.span = null;
    document.querySelector(".history-control").open = false;
    note("正在查看已保存的真实运行记录；没有发起新的模型调用。");
    render();
  } catch (e) {
    note(`无法打开 trace：${e.message}`, true);
  }
};

async function readEvents(response, handler) {
  if (!response.ok) {
    let body;
    try {
      body = await response.json();
    } catch {
      body = {};
    }
    throw new Error(
      typeof body.detail === "string" ? body.detail : `HTTP ${response.status}`,
    );
  }
  const reader = response.body.getReader(),
    decoder = new TextDecoder();
  let buffer = "",
    terminal = false;
  try {
    while (true) {
      const { value, done } = await reader.read();
      buffer += decoder
        .decode(value || new Uint8Array(), { stream: !done })
        .replace(/\r\n/g, "\n");
      let idx;
      while ((idx = buffer.indexOf("\n\n")) >= 0) {
        const block = buffer.slice(0, idx);
        buffer = buffer.slice(idx + 2);
        let kind = "message",
          data = "";
        block.split("\n").forEach((line) => {
          if (line.startsWith("event:")) kind = line.slice(6).trim();
          if (line.startsWith("data:")) data += line.slice(5).trimStart();
        });
        if (data) {
          handler(kind, JSON.parse(data));
          if (kind === "result" || kind === "failure") terminal = true;
        }
      }
      if (done) break;
    }
  } finally {
    reader.releaseLock();
  }
  if (!terminal)
    throw new Error(
      "连接已断开。服务端任务可能仍在执行；稍后刷新历史记录查看，不要立即重复提交。",
    );
}
$("query-form").onsubmit = async (event) => {
  event.preventDefault();
  if (state.busy) return;
  const request = {
    question: $("question").value.trim(),
    as_of: $("as-of").value,
    reading_context: $("background").value.trim(),
    confirmed_context: {},
  };
  state.data = {
    inputs: { original_question: request.question, as_of: request.as_of },
    stages: [],
    status: "running",
    created_at: new Date().toISOString(),
  };
  currentCatalog = null;
  focusedSymbol = null;
  state.historical = false;
  state.span = null;
  state.node = "query_plan";
  state.tab = "planner";
  setBusy(true);
  note("");
  render();
  try {
    const response = await fetch(
      `/query/stream?generate=${$("mode").value === "answer"}`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(request),
      },
    );
    await readEvents(response, (kind, data) => {
      if (kind === "accepted") state.data.query_id = data.query_id;
      else if (kind === "stage_started" || kind === "stage_finished") {
        const index = state.data.stages.findIndex((s) => s.id === data.id);
        if (index < 0) state.data.stages.push(data);
        else state.data.stages[index] = data;
      } else if (kind === "result") {
        state.data = data;
        if (data.status === "generated") state.tab = "answer";
        if (data.status === "error")
          note(
            `运行失败：${data.error?.code || data.error?.type}。已完成的阶段仍可查看。`,
            true,
          );
      } else if (kind === "failure") {
        state.data.status = "error";
        note(`服务执行失败：${data.error?.code}。请检查本地配置或预算。`, true);
      }
      scheduleRender();
    });
  } catch (e) {
    state.data.status = "error";
    note(`查询未完成：${e.message}`, true);
  } finally {
    setBusy(false);
    render();
    await refreshHistory();
  }
};
const today = new Date();
$("as-of").value =
  `${today.getFullYear()}-${String(today.getMonth() + 1).padStart(2, "0")}-${String(today.getDate()).padStart(2, "0")}`;
render();
refreshHistory().then(async () => {
  // Opening a saved trace is read-only; never run the example question automatically.
  if (state.data || state.busy) return;
  const first = $("history").options[1];
  if (!first) return;
  $("history").value = first.value;
  $("load").click();
});
jsonFetch("/health")
  .then((d) => {
    $("health").textContent =
      `数据库已连接 · ${d.published_documents} 份年报 · ${d.ann}`;
    $("health-dot").classList.add("ok");
  })
  .catch(() => {
    $("health").textContent = "数据库未就绪 · 仍可查看历史";
    $("health-dot").classList.add("error");
  });

jsonFetch("/components")
  .then((data) => {
    componentRefs = data.components;
    render();
  })
  .catch(() => note("代码地图暂不可读；仍可查看历史 trace。", true));
