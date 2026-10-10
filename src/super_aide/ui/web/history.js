// Super Aide 历史记录窗口：左边按天列出以前的问答，右边看完整内容。
// 在普通浏览器里打开时进入预览模式，用模拟数据。

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const html = document.documentElement;
const MODE_LABEL = { ask: '问答', act: '操作' }; // 显示时经 I18N.t() 换成当前语言
const ENGINE_NAME = { claude: 'Claude', codex: 'Codex', dsh: 'DeepSeek' };

let bridge = null;
const state = { items: [], current: null, conversation: null, searchTimer: null };

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
    row.addEventListener('click', () => select(item.id));
    list.append(row);
  }
}

function markActive() {
  for (const row of document.querySelectorAll('.item')) row.classList.toggle('active', row.dataset.id === state.current);
  $('.item.active')?.scrollIntoView({ block: 'nearest' });
}

// ---------- 详情 ----------

async function select(id) {
  state.current = id || null;
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
  if (first.engine) meta.append(el('span', '', `${ENGINE_NAME[first.engine] || first.engine} · ${first.model}`));
  detail.append(meta);

  for (const turn of conv.turns) {
    const box = el('section', 'turn');
    box.append(el('div', 'turn-q', turn.question));
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
  actions.append(copy, folder);
  detail.append(actions);
  detail.scrollTop = 0;
}

// ---------- 事件 ----------

$('#search').addEventListener('input', () => {
  clearTimeout(state.searchTimer);
  state.searchTimer = setTimeout(reload, 200);
});

document.addEventListener('keydown', (e) => {
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

window.historyView = { reload };

// ---------- 浏览器预览：模拟数据 ----------

const now = Date.now();
const PREVIEW = [
  { id: 'a', started: new Date(now - 3600e3).toISOString(), mode: 'ask', turns: [
    { question: '这个报错是什么原因？', ok: true, engine: 'claude', model: 'claude-opus-5-5',
      answer: '当前内核用的 Python 环境里没有装 `pandas`。\n\n1. 在 notebook 里运行：\n\n   ```\n   %pip install pandas\n   ```\n\n2. 重启内核，再运行这个单元格。' },
    { question: '装了还是不行', ok: true, engine: 'claude', model: 'claude-opus-5-5',
      answer: '多半是装到了别的 Python。先运行 `import sys; print(sys.executable)` 看内核用的是哪个。' }] },
  { id: 'b', started: new Date(now - 7200e3).toISOString(), mode: 'act', turns: [
    { question: '帮我修好它', ok: false, error: '浏览器操作还没接通：在 Codex 应用的插件页里安装「Chrome」插件。',
      engine: 'codex', model: 'gpt-6-astra', answer: '没完成：浏览器操作还没接通。\n本次没有改动任何东西。' }] },
  { id: 'c', started: new Date(now - 90000e3).toISOString(), mode: 'act', turns: [
    { question: '帮我把这个软件卸载干净', ok: true, engine: 'codex', model: 'gpt-6-astra',
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
