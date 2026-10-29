/* No model credentials or provider requests in the browser. Untrusted text uses textContent. */
"use strict";
const $ = (id) => document.getElementById(id);
const nodes = [
  [
    "catalog_snapshot",
    "资料目录",
    "Catalog / disclosure cutoff",
    "serving/runtime.py",
    "确认可用公司、报告财年与公开日期。截止日限制可见资料，报告财年与数据事实期间分别处理。",
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
    "Top shortlist / reranker",
    "reranking.py",
    "对配置限定的候选重排；当前默认使用 LLM 评分，并标记对应 need 与相关行。模型判断尚不是人工验证的证据。",
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
  ["overview", "组件概览"],
  ["planner", "Planner"],
  ["search", "检索记录"],
  ["ranking", "候选与精排"],
  ["context", "最终上下文"],
  ["answer", "引用答案"],
  ["events", "执行日志"],
];
let state = {
  data: null,
  tab: "overview",
  node: "query_plan",
  busy: false,
  historical: false,
};
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
  $("pipeline").replaceChildren();
  nodes.forEach(([name, label, tech], i) => {
    const spans = stages(name),
      last = spans.at(-1);
    const status =
      last?.status || (d && d.status !== "running" ? "skipped" : "pending");
    const button = el(
      "button",
      `node ${status}${state.node === name ? " active" : ""}`,
    );
    button.setAttribute("aria-label", `${label}：${status}`);
    button.append(
      el("span", "node-number", String(i + 1).padStart(2, "0")),
      el("span", "node-state"),
      el("strong", "", label),
      el("small", "", tech),
      el(
        "span",
        "node-time",
        last
          ? seconds(last.duration_seconds)
          : status === "skipped"
            ? "未执行"
            : "等待执行",
      ),
    );
    button.onclick = () => {
      state.node = name;
      state.tab =
        name === "query_plan"
          ? "planner"
          : name === "retrieve"
            ? "search"
            : name === "rerank" || name === "fusion"
              ? "ranking"
              : name === "context_build"
                ? "context"
                : name === "generation"
                  ? "answer"
                  : "overview";
      render();
    };
    $("pipeline").append(button);
  });
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

function overview() {
  const n = nodes.find((n) => n[0] === state.node),
    p = panel(n[1], n[3]);
  p.append(el("p", "", n[4]));
  const s = latest(n[0]);
  if (s) {
    p.append(
      tag(s.status, statusClass(s.status) === "ok" ? "green" : "orange"),
      tag(seconds(s.duration_seconds)),
      raw(s),
    );
  } else
    p.append(
      empty(
        state.data
          ? "这一阶段未执行，或尚未开始。"
          : "运行新查询，或打开一条历史 trace，查看实际数据。",
      ),
    );
  return p;
}
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
  overview,
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
    state.historical = true;
    state.tab = "planner";
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
  state.historical = false;
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
      render();
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
refreshHistory();
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
