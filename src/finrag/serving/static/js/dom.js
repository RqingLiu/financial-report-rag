export const $ = id => document.getElementById(id);
export function el(tag, cls = '', text = '') {
  const n = document.createElement(tag);
  if (cls) n.className = cls;
  n.textContent = String(text ?? '');
  return n;
}
export function seconds(n) {
  return typeof n === 'number' ? (n > 0 && n < 0.01 ? `${(n*1000).toFixed(1)}ms` : `${n.toFixed(2)}s`) : '未记录';
}
export function json(value, title = '查看记录 JSON') {
  const d = el('details', 'json');
  d.append(el('summary', '', title), el('pre', '', JSON.stringify(value ?? {
    available: false
  }, null, 2)));
  return d;
}
export function note(text, error = false) {
  $('notice').hidden = !text;
  $('notice').textContent = text;
  $('notice').className = `notice ${error?'error':''}`;
}
export function table(headers, rows) {
  const wrap = el('div', 'table-wrap'),
    t = el('table'),
    head = el('tr');
  headers.forEach(h => head.append(el('th', '', h)));
  const thead = el('thead');
  thead.append(head);
  t.append(thead);
  const body = el('tbody');
  rows.forEach(row => {
    const tr = el('tr');
    row.forEach(v => {
      const td = el('td');
      td.append(v instanceof Node ? v : document.createTextNode(String(v ?? '—')));
      tr.append(td);
    });
    body.append(tr);
  });
  t.append(body);
  wrap.append(t);
  return wrap;
}
export function external(url, label) {
  try {
    const u = new URL(url);
    if (u.protocol !== 'https:') return el('span', '', label);
    const a = el('a', '', label);
    a.href = u.href;
    a.target = '_blank';
    a.rel = 'noopener noreferrer';
    return a;
  } catch {
    return el('span', '', label);
  }
}
export function dialog(title, children) {
  $('detail-title').textContent = title;
  $('detail-content').replaceChildren(...children);
  if (!$('detail-dialog').open) $('detail-dialog').showModal();
}
export function tabs(target, items, selected, change) {
  target.replaceChildren();
  items.forEach(([id, label]) => {
    const b = el('button', id === selected ? 'active' : '', label);
    b.setAttribute('aria-pressed', String(id === selected));
    b.onclick = () => change(id);
    target.append(b);
  });
}
