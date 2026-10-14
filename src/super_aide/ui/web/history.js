// Super Aide 历史记录窗口：左边按天列出以前的问答，右边看完整内容。
// 在普通浏览器里打开时进入预览模式，用模拟数据。

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const html = document.documentElement;
const MODE_LABEL = { ask: '问答', act: '操作' }; // 显示时经 I18N.t() 换成当前语言
const ENGINE_NAME = { claude: 'Claude', codex: 'Codex', dsh: 'DeepSeek' };

const UNDO_MS = 6000; // 删掉以后"撤销"留这么久
const TRASH_ICON = '<svg viewBox="0 0 20 20"><path d="M4.5 6h11M8.2 6V4.6h3.6V6M6.2 6l.7 9.1a1.5 1.5 0 0 0 1.5 1.4h3.2a1.5 1.5 0 0 0 1.5-1.4L13.8 6"/></svg>';

let bridge = null;
// selected：Ctrl / Shift 点选出来的多条（只选了一条时就是 current）；anchor：Shift 连选的起点；undo：刚删掉、还能撤销的
const state = { items: [], current: null, conversation: null, searchTimer: null, selected: new Set(), anchor: null,
                undo: null, removedAt: 0 };

function call(method, ...args) {
  return new Promise((resolve) => {
    if (bridge) bridge[method](...args, resolve);
    else resolve(preview[method] ? preview[method](...args) : undefined);
  });
}

function el(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text !== undefined) node.textContent = text;
  return node;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

if (window.marked) {
  marked.use({ gfm: true, breaks: true, renderer: { html(token) { return escapeHtml(token.text ?? token.raw ?? ''); } } });
}

function renderMarkdown(target, markdown) {
  target.innerHTML = window.marked ? marked.parse(markdown || '') : `<p>${escapeHtml(markdown)}</p>`;
  for (const pre of target.querySelectorAll('pre')) {
    const code = pre.innerText;
    const btn = el('button', 'icon-btn copy');
    btn.title = I18N.t('复制');
    btn.innerHTML = '<svg viewBox="0 0 20 20"><rect x="7" y="7" width="9.5" height="9.5" rx="2"/><path d="M13 7V5.5A1.5 1.5 0 0 0 11.5 4h-6A1.5 1.5 0 0 0 4 5.5v6A1.5 1.5 0 0 0 5.5 13H7"/></svg>';
    btn.addEventListener('click', () => call('copy', code));
    pre.appendChild(btn);
  }
  for (const a of target.querySelectorAll('a[href]')) {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      call('openUrl', a.href);
    });
  }
}

// ---------- 时间 ----------

function dayLabel(iso) {
  const d = new Date(iso);
  const today = new Date();
  const days = Math.round((new Date(today.toDateString()) - new Date(d.toDateString())) / 86400000);
  if (days === 0) return I18N.t('今天');
  if (days === 1) return I18N.t('昨天');
  // 英文的月份用名字（Oct 7），中文用数字（10 月 7 日）
  const date = { year: d.getFullYear(), day: d.getDate(),
                 month: I18N.lang === 'en' ? d.toLocaleString('en-US', { month: 'short' }) : d.getMonth() + 1 };
  return d.getFullYear() === today.getFullYear() ? I18N.t('{month} 月 {day} 日', date)
    : I18N.t('{year} 年 {month} 月 {day} 日', date);
}

// 由谁、用哪个模型、多大的思考强度答的：Claude · claude-opus-5-5 · 思考强度 high
function configLabel(turn) {
  if (!turn.engine) return '';
  const parts = [ENGINE_NAME[turn.engine] || turn.engine, turn.model];
  if (turn.effort) parts.push(I18N.t('思考强度 {effort}', { effort: turn.effort }));
  return parts.filter(Boolean).join(' · ');
}

function timeLabel(iso) {
  const d = new Date(iso);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// ---------- 列表 ----------

async function reload() {
  const data = JSON.parse(await call('list', $('#search').value));
  html.dataset.theme = data.theme;
  if (data.lang !== I18N.lang) I18N.setLang(data.lang); // 宿主给的语言（zh / en）；下面的列表和详情都重画
  state.items = data.items;
  renderList();
  const keep = state.items.some((item) => item.id === state.current);
  await select(keep ? state.current : state.items[0]?.id);
  if (bridge) bridge.rendered(); // 第一次打开时，宿主等画好了再显示窗口
}

function renderList() {
  const list = $('#list');
  list.innerHTML = '';
  if (!state.items.length) {
    list.append(el('div', 'empty-state', $('#search').value.trim() ? I18N.t('没有找到') : I18N.t('还没有记录')));
    return;
  }
  let day = '';
  for (const item of state.items) {
    const label = dayLabel(item.started);
    if (label !== day) {
      day = label;
      list.append(el('div', 'day', label));
    }
    const row = el('div', `item ${item.mode}${item.ok === false ? ' failed' : ''}`);
    row.dataset.id = item.id;
    row.append(el('span', 'dot'), el('span', 'q', item.question), el('span', 'time', timeLabel(item.started)),
      el('span', 'p', item.ok === false && !/^(没完成|未完成|暂未|未能|没能)/.test(item.preview)
        ? (item.preview ? I18N.t('没完成 · {preview}', { preview: item.preview }) : I18N.t('没完成')) : item.preview));
    row.title = item.question;
    const del = el('button', 'icon-btn del');
    del.title = I18N.t('删除（Delete）');
    del.innerHTML = TRASH_ICON;
    del.addEventListener('click', (e) => {
      e.stopPropagation();
      // 删掉后下一条正好移到鼠标下：顺手双击不该连删两条
      if (performance.now() - state.removedAt < 500) return;
      remove(state.selected.has(item.id) && state.selected.size > 1 ? [...state.selected] : [item.id]);
    });
    row.append(del);
    row.addEventListener('click', (e) => pick(item.id, e));
    list.append(row);
  }
}

function markActive() {
  for (const row of document.querySelectorAll('.item')) {
    row.classList.toggle('active', state.selected.size > 1 ? state.selected.has(row.dataset.id) : row.dataset.id === state.current);
  }
  $(`.item[data-id="${state.current}"]`)?.scrollIntoView({ block: 'nearest' });
}

// ---------- 选择：单击看一条；Ctrl 点选加减一条，Shift 点选连着选一段（和资源管理器一样） ----------

function pick(id, e) {
  if (e.ctrlKey || e.metaKey) {
    if (state.selected.size === 0 && state.current) state.selected.add(state.current);
    if (state.selected.has(id) && state.selected.size > 1) state.selected.delete(id);
    else state.selected.add(id);
    state.anchor = id;
    showSelection();
  } else if (e.shiftKey && state.anchor) {
    const ids = state.items.map((item) => item.id);
    const [a, b] = [ids.indexOf(state.anchor), ids.indexOf(id)].sort((x, y) => x - y);
    state.selected = new Set(a < 0 ? [id] : ids.slice(a, b + 1));
    showSelection();
  } else {
    select(id);
  }
}

function selectAll() {
  if (!state.items.length) return;
  state.selected = new Set(state.items.map((item) => item.id));
  showSelection();
}

function showSelection() {
  if (state.selected.size <= 1) {
    select([...state.selected][0] || state.current);
    return;
  }
  markActive();
  const detail = $('#detail');
  detail.innerHTML = '';
  const n = state.selected.size;
  const box = el('div', 'selection');
  box.append(el('div', 'sel-count', I18N.t('已选 {n} 条', { n })));
  const list = el('ul', 'sel-list');
  const chosen = state.items.filter((item) => state.selected.has(item.id));
  for (const item of chosen.slice(0, 6)) list.append(el('li', '', item.question));
  if (chosen.length > 6) list.append(el('li', '', '…'));
  const actions = el('div', 'actions');
  const del = el('button', 'text-btn danger', I18N.t('删除这 {n} 条', { n }));
  del.addEventListener('click', () => remove([...state.selected]));
  const cancel = el('button', 'text-btn', I18N.t('取消选择'));
  cancel.addEventListener('click', () => select(state.current));
  actions.append(del, cancel);
  box.append(list, actions);
  detail.append(box);
}

// ---------- 删除：一下就删（不弹确认），几秒内可以撤销 ----------

async function remove(ids) {
  if (!ids.length) return;
  const removed = JSON.parse(await call('remove', JSON.stringify(ids)) || '[]');
  if (!removed.length) return;
  state.removedAt = performance.now();
  const gone = new Set(removed);
  const order = state.items.map((item) => item.id);
  const last = Math.max(...removed.map((id) => order.indexOf(id)));
  const left = state.items.filter((item) => !gone.has(item.id));
  const next = left.find((item) => order.indexOf(item.id) > last) || left[left.length - 1];
  state.items = left;
  renderList();
  await select(next?.id);
  showUndo(removed);
}

function showUndo(removed) {
  clearTimeout(state.undo?.timer);
  const ids = [...(state.undo?.ids || []), ...removed]; // 撤销条还在时又删了几条：一起撤销
  const bar = $('#undo');
  $('#undo-text').textContent = I18N.t('已删除 {n} 条', { n: ids.length });
  bar.hidden = false;
  state.undo = { ids, timer: setTimeout(() => {
    bar.hidden = true;
    state.undo = null;
    call('purge', Math.round(UNDO_MS / 1000)); // 撤销不了了：真删掉
  }, UNDO_MS) };
}

async function undo() {
  const pending = state.undo;
  if (!pending) return;
  clearTimeout(pending.timer);
  state.undo = null;
  $('#undo').hidden = true;
  await call('restore', JSON.stringify(pending.ids));
  await reload();
  await select(pending.ids[0]);
}

// ---------- 详情 ----------

async function select(id) {
  state.current = id || null;
  state.selected = new Set(id ? [id] : []);
  state.anchor = id || null;
  markActive();
  const detail = $('#detail');
  detail.innerHTML = '';
  if (!id) {
    detail.append(el('div', 'empty-state', state.items.length || $('#search').value.trim()
      ? '' : I18N.t('还没有记录。用快捷键提一个问题，回答会出现在这里。')));
    return;
  }
  const conv = JSON.parse(await call('load', id));
  if (!conv || state.current !== id) return;
  state.conversation = conv;
  html.dataset.mode = conv.mode === 'act' ? 'act' : 'ask';

  const first = conv.turns[0] || {};
  const meta = el('div', 'meta');
  meta.append(el('span', 'mode-chip', I18N.t(MODE_LABEL[conv.mode] || '问答')),
    el('span', '', `${dayLabel(conv.started)} ${timeLabel(conv.started)}`));
  let shown = configLabel(first);
  if (shown) meta.append(el('span', '', shown));
  detail.append(meta);

  for (const turn of conv.turns) {
    const box = el('section', 'turn');
    box.append(el('div', 'turn-q', turn.question));
    // 这一轮换了配置（上一轮没办成时加强、模型服务出错时换了一个）：写在这一问下面
    const label = configLabel(turn);
    if (label && label !== shown) {
      box.append(el('div', 'turn-meta', label));
      shown = label;
    }
    if (!turn.ok && turn.error) box.append(el('div', 'error', turn.error));
    const answer = el('div', 'answer-body md');
    renderMarkdown(answer, turn.answer);
    box.append(answer);
    detail.append(box);
  }

  const actions = el('div', 'actions');
  const copy = el('button', 'text-btn', I18N.t('复制回答'));
  copy.addEventListener('click', () => {
    call('copy', conv.turns.map((t) => t.answer).filter(Boolean).join('\n\n'));
    copy.textContent = I18N.t('已复制');
    setTimeout(() => { copy.textContent = I18N.t('复制回答'); }, 1200);
  });
  const folder = el('button', 'text-btn', I18N.t('打开会话文件夹'));
  folder.addEventListener('click', () => call('openFolder', id));
  const del = el('button', 'text-btn danger-hover', I18N.t('删除'));
  del.title = I18N.t('删除（Delete）。按住 Ctrl 或 Shift 点选，可以一次删多条');
  del.addEventListener('click', () => remove([id]));
  actions.append(copy, folder, del);
  detail.append(actions);
  detail.scrollTop = 0;
}

// ---------- 事件 ----------

$('#search').addEventListener('input', () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(reload, 200);
});

document.addEventListener('keydown', (e) => {
  const typing = Boolean(e.target.closest && e.target.closest('input, textarea'));
  const mod = e.ctrlKey || e.metaKey;
  if (e.key === 'Escape' && state.selected.size > 1) { // 先取消多选，再清空搜索、关窗口
    select(state.current);
    return;
  }
  if (!typing && e.key === 'Delete') {
    e.preventDefault();
    remove(state.selected.size ? [...state.selected] : (state.current ? [state.current] : []));
    return;
  }
  if (!typing && mod && e.key.toLowerCase() === 'a') {
    e.preventDefault();
    selectAll();
    return;
  }
  if (mod && e.key.toLowerCase() === 'z' && state.undo && !typing) {
    e.preventDefault();
    undo();
    return;
  }
  if (e.key === 'Escape') {
    const search = $('#search');
    if (search.value) {
      search.value = '';
      reload();
    } else {
      call('close');
    }
    return;
  }
  if ((e.key === 'ArrowDown' || e.key === 'ArrowUp') && state.items.length) {
    e.preventDefault();
    const index = state.items.findIndex((item) => item.id === state.current);
    const next = Math.max(0, Math.min(state.items.length - 1, index + (e.key === 'ArrowDown' ? 1 : -1)));
    select(state.items[next].id);
  }
});

$('#titlebar').addEventListener('mousedown', (e) => {
  if (e.button === 0 && !e.target.closest('button, input')) call('startDrag');
});
$('#close').addEventListener('click', () => call('close'));
$('#undo-btn').addEventListener('click', undo);

window.historyView = { reload };

// ---------- 浏览器预览：模拟数据 ----------

const now = Date.now();
const PREVIEW = [
  { id: 'a', started: new Date(now - 3600e3).toISOString(), mode: 'ask', turns: [
    { question: '这个报错是什么原因？', ok: true, engine: 'claude', model: 'claude-opus-5-5', effort: 'medium',
      answer: '当前内核用的 Python 环境里没有装 `pandas`。\n\n1. 在 notebook 里运行：\n\n   ```\n   %pip install pandas\n   ```\n\n2. 重启内核，再运行这个单元格。' },
    { question: '装了还是不行', ok: true, engine: 'claude', model: 'claude-opus-5-5', effort: 'high',
      answer: '多半是装到了别的 Python。先运行 `import sys; print(sys.executable)` 看内核用的是哪个。' }] },
  { id: 'b', started: new Date(now - 7200e3).toISOString(), mode: 'act', turns: [
    { question: '帮我修好它', ok: false, error: '浏览器操作还没接通：在 Codex 应用的插件页里安装「Chrome」插件。',
      engine: 'codex', model: 'gpt-6-astra', effort: 'xhigh', answer: '没完成：浏览器操作还没接通。\n本次没有改动任何东西。' }] },
  { id: 'c', started: new Date(now - 90000e3).toISOString(), mode: 'act', turns: [
    { question: '帮我把这个软件卸载干净', ok: true, engine: 'codex', model: 'gpt-6-astra', effort: 'high',
      answer: '已完成：卸载了 Foo，清理了 3 处残留。\n想恢复的话需要重新安装。' }] },
];

const PREVIEW_LANG = new URLSearchParams(location.search).get('lang') === 'en' ? 'en' : 'zh'; // ?lang=en 预览英文

const preview = {
  list: (query) => JSON.stringify({
    theme: matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark',
    lang: PREVIEW_LANG,
    items: PREVIEW.filter((c) => !query || JSON.stringify(c).includes(query)).map((c) => ({
      id: c.id, started: c.started, mode: c.mode, question: c.turns[0].question,
      preview: c.turns.at(-1).answer.split('\n')[0].replace(/[`*#]/g, ''), ok: c.turns.at(-1).ok, turns: c.turns.length,
    })),
  }),
  load: (id) => JSON.stringify(PREVIEW.find((c) => c.id === id) || null),
  remove: (ids) => {
    const gone = JSON.parse(ids);
    preview.trash.push(...PREVIEW.filter((c) => gone.includes(c.id)));
    PREVIEW.splice(0, PREVIEW.length, ...PREVIEW.filter((c) => !gone.includes(c.id)));
    return JSON.stringify(gone);
  },
  restore: (ids) => {
    const back = JSON.parse(ids);
    PREVIEW.push(...preview.trash.filter((c) => back.includes(c.id)));
    PREVIEW.sort((a, b) => b.started.localeCompare(a.started));
    return JSON.stringify(back);
  },
  purge: () => { preview.trash = []; },
  trash: [],
};

// ---------- 启动 ----------

if (window.qt && qt.webChannelTransport && window.QWebChannel) {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    reload();
  });
} else {
  document.body.classList.add('preview');
  if (PREVIEW_LANG === 'en') I18N.setLang('en');
  reload();
}
