// Super Aide 前端：输入框 → 回答卡片 / 操作胶囊 → 结果提示。
// 在桌面宿主（PySide6 + QtWebEngine）里通过 QWebChannel 与 Python 通信，回答来自真实引擎；
// 在普通浏览器里打开时进入预览模式，用底部按钮和模拟数据切换各状态。

'use strict';

const $ = (sel) => document.querySelector(sel);
const html = document.documentElement;

const VIEWS = ['input', 'card', 'pill', 'toast', 'dock'];
// 界面文字都写中文，用的时候经 I18N.t() 换成当前语言
const PLACEHOLDER = { ask: '这个报错是什么原因？', act: '帮我修好它' };
const FOLLOWUP = { ask: '继续问…', act: '照这个帮我做' };
const MODE_LABEL = { ask: '问答', act: '操作' };
const ENGINE_NAME = { claude: 'Claude', codex: 'Codex', dsh: 'DeepSeek' };
const TOAST_MS = 8000;
const PILL_NOTE_MS = 10000; // 操作中"可以继续用电脑"的提示显示这么久
const DOCK_IDLE_MS = 10 * 60 * 1000; // 贴边的步骤 10 分钟没有交互就消失

let bridge = null;
const state = {
  mode: 'ask',
  view: null,
  run: 0,
  timers: [],
  ticker: null,
  toastTimer: null,
  dockTimer: null,
  placeholders: {}, // 宿主给的推荐问题（已经是当前语言）；没给的用 PLACEHOLDER
  hasRecent: false,
};
// 当前这一轮的回答
const live = { question: '', draft: '', statuses: [], route: null, done: true, error: '', renderTimer: null };

// ---------- 基础 ----------

function later(ms) {
  return new Promise((resolve) => state.timers.push(setTimeout(resolve, ms)));
}

function stopAll() {
  state.run += 1;
  state.timers.forEach(clearTimeout);
  state.timers = [];
  clearInterval(state.ticker);
  clearTimeout(state.toastTimer);
  clearTimeout(state.dockTimer);
  clearTimeout(live.renderTimer);
  state.ticker = null;
}

function el(tag, cls) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  return node;
}

function copyText(text) {
  if (bridge) bridge.copy(text);
  else navigator.clipboard?.writeText(text);
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function placeholderFor(mode) {
  return state.placeholders[mode] || I18N.t(PLACEHOLDER[mode]);
}

function setMode(mode) {
  state.mode = mode;
  html.dataset.mode = mode;
  $('#mode-chip').textContent = I18N.t(MODE_LABEL[mode]);
  $('#input').placeholder = placeholderFor(mode);
  $('#followup').placeholder = I18N.t(FOLLOWUP[mode]);
  $('#followup-hint').textContent = mode === 'ask' ? I18N.t('Tab 让我来做') : I18N.t('Tab 只问不做');
}

function show(view) {
  for (const v of VIEWS) $(`#${v}-view`).hidden = v !== view;
  const node = $(`#${view}-view`);
  node.style.animation = 'none';
  void node.offsetWidth; // 重新触发出现动画
  node.style.animation = '';
  state.view = view;
  if (bridge) bridge.setView(view);
}

function dismiss() {
  stopAll();
  if (bridge) bridge.cancel();
  else app.showInput({ mode: state.mode });
}

// ---------- Markdown ----------

if (window.marked) {
  marked.use({
    gfm: true,
    breaks: true, // 模型的单个换行就是换行（操作汇报一行一件事），不合并成一段
    renderer: {
      html(token) { return escapeHtml(token.text ?? token.raw ?? ''); }, // 模型输出里的原始 HTML 一律转义
    },
  });
}

const caret = el('span', 'caret');

function renderMarkdown(target, markdown, streaming) {
  target.innerHTML = window.marked ? marked.parse(markdown) : `<p>${escapeHtml(markdown)}</p>`;
  for (const pre of target.querySelectorAll('pre')) {
    const code = pre.innerText;
    const btn = el('button', 'icon-btn copy');
    btn.title = I18N.t('复制');
    btn.innerHTML = $('#copy-all').innerHTML;
    btn.addEventListener('click', () => copyText(code));
    pre.appendChild(btn);
  }
  for (const a of target.querySelectorAll('a[href]')) {
    a.addEventListener('click', (e) => {
      e.preventDefault();
      if (bridge) bridge.openUrl(a.href);
    });
  }
  if (streaming) {
    const last = target.lastElementChild;
    const host = last && last.tagName === 'PRE' ? last.querySelector('code') || last : last || target;
    (host.tagName === 'OL' || host.tagName === 'UL' ? host.lastElementChild || host : host).appendChild(caret);
  }
  keepScrolled();
}

function keepScrolled() {
  const answer = $('#answer');
  const overflow = answer.scrollHeight > answer.clientHeight + 1;
  answer.classList.toggle('scrollable', overflow);
  if (overflow && !live.done) answer.scrollTop = answer.scrollHeight;
}

function scheduleRender() {
  if (live.renderTimer) return;
  live.renderTimer = setTimeout(() => {
    live.renderTimer = null;
    renderMarkdown($('#answer'), live.draft, !live.done);
  }, 40);
}

// ---------- 真实回答：卡片和胶囊 ----------

function resetRating() {
  $('#card-view').classList.remove('rated');
  for (const btn of document.querySelectorAll('.rate')) btn.classList.remove('chosen');
}

function startCard(question) {
  stopAll();
  resetRating();
  Object.assign(live, { question, draft: '', statuses: [], done: false, error: '' });
  $('#question').textContent = question;
  $('#question').title = '';
  $('#answer').innerHTML = '';
  $('#answer').classList.remove('scrollable');
  $('#steps').hidden = true;
  $('#followup').value = '';
  setStatus(I18N.t('正在看你的屏幕…'));
  $('#card-view').classList.add('thinking');
  show('card');
}

function startPill(task) {
  stopAll();
  Object.assign(live, { question: task, draft: '', statuses: [], done: false, error: '' });
  $('#pill-text').textContent = I18N.t('正在理解任务…');
  $('#pill-time').textContent = '0:00';
  const note = $('#pill-note');
  note.hidden = false;
  note.classList.remove('faded');
  show('pill');
  later(PILL_NOTE_MS).then(() => {
    note.classList.add('faded');
    return later(450);
  }).then(() => { note.hidden = true; });
  const t0 = Date.now();
  state.ticker = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    $('#pill-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }, 250);
}

function setStatus(text, isError = false) {
  const line = $('#status-line');
  line.innerHTML = text ? `<span class="${isError ? 'error-text' : 'shimmer'}">${escapeHtml(text)}</span>` : '';
}

function onEvent(ev) {
  switch (ev.type) {
    case 'route': {
      live.route = ev;
      $('#question').title = I18N.t('由 {engine} · {model} · 思考强度 {effort} 回答',
        { engine: ENGINE_NAME[ev.engine] || ev.engine, model: ev.model, effort: ev.effort });
      break;
    }
    case 'status': {
      if (!ev.text) break;
      if (live.statuses[live.statuses.length - 1] !== ev.text) live.statuses.push(ev.text);
      if (state.view === 'pill') $('#pill-text').textContent = ev.text;
      else if (state.view === 'card' && !live.draft) setStatus(ev.text);
      break;
    }
    case 'new_message':
    case 'retract': {
      live.draft = '';
      if (state.view === 'card') scheduleRender();
      break;
    }
    case 'delta': {
      live.draft += ev.text;
      if (state.view === 'card') {
        setStatus('');
        scheduleRender();
      }
      break;
    }
    case 'error': {
      live.error = ev.text;
      if (state.view === 'card') setStatus(ev.text, true);
      else if (state.view === 'pill') $('#pill-text').textContent = ev.text;
      break;
    }
    case 'done': {
      finish(ev);
      break;
    }
    default:
      break;
  }
}

function summaryLine(markdown) {
  const line = markdown.split('\n').map((s) => s.replace(/^[#>*\-\d.\s`]+/, '').trim()).find(Boolean);
  return line ? (line.length > 40 ? `${line.slice(0, 39)}…` : line) : '';
}

function finish(ev) {
  live.done = true;
  clearInterval(state.ticker);
  if (!ev.ok && !live.error && ev.reason === 'interrupted') live.error = I18N.t('已停止');
  if (!ev.ok && !live.error && ev.error) live.error = ev.error;
  if (ev.hint) live.error = ev.hint; // 没办成的原因是环境没就绪（比如浏览器操作没接通）：直接告诉你怎么修
  if (state.view === 'card') {
    clearTimeout(live.renderTimer);
    live.renderTimer = null;
    renderMarkdown($('#answer'), live.draft, false);
    caret.remove();
    $('#card-view').classList.remove('thinking');
    setStatus(live.error && (!live.draft || ev.hint) ? live.error : '', Boolean(live.error));
    $('#followup').focus();
  } else if (state.view === 'pill') {
    const ok = ev.ok && !live.error;
    // 汇报自己写了"没完成：…"（英文 Not done: …）或者是修法提示的，原样显示，不再套一层"没有完成"
    const failed = /^(没完成|未完成|暂未|未能|没能|浏览器操作|not done|not completed|couldn't|could not|unable to|failed|browser control)/i
      .test(live.error) ? live.error
      : I18N.t('没有完成：{reason}', { reason: live.error || I18N.t('出错了') });
    showToast(ok ? (summaryLine(live.draft) || I18N.t('已完成')) : failed, ok);
  }
}

function showToast(title, ok = true) {
  $('#toast-title').textContent = title;
  $('#toast-view').classList.toggle('failed', !ok);
  show('toast');
  armToastTimer();
}

function armToastTimer() {
  clearTimeout(state.toastTimer);
  state.toastTimer = setTimeout(() => {
    if (state.view === 'toast') dismiss();
  }, TOAST_MS);
}

function openResultCard(focusFollowup) {
  stopAll();
  resetRating();
  $('#question').textContent = live.question;
  setStatus(live.error || '', Boolean(live.error));
  const steps = $('#steps');
  steps.innerHTML = '';
  for (const s of live.statuses) {
    const row = el('div');
    const text = el('span');
    text.textContent = s;
    row.title = s;
    row.appendChild(text);
    steps.appendChild(row);
  }
  steps.hidden = live.statuses.length === 0;
  $('#card-view').classList.remove('thinking');
  setMode('ask');
  show('card');
  renderMarkdown($('#answer'), live.draft, false);
  if (focusFollowup) $('#followup').focus();
}

// ---------- 贴边步骤 ----------

function armDockTimer() {
  clearTimeout(state.dockTimer);
  state.dockTimer = setTimeout(() => {
    if (state.view === 'dock') dismiss();
  }, DOCK_IDLE_MS);
}

function dock() {
  stopAll();
  const box = $('#dock-steps');
  renderMarkdown(box, live.draft, false);
  for (const child of [...box.children]) if (child.tagName !== 'OL') child.remove(); // 只留编号步骤
  $('#dock-title').textContent = live.question;
  show('dock');
  armDockTimer();
}

// ---------- 交互 ----------

function submit(raw, continueLast = false) {
  const text = raw.trim() || $('#input').placeholder;
  if (bridge) {
    if (continueLast) bridge.continueLast(text, state.mode);
    else bridge.submit(text, state.mode);
    if (state.mode === 'ask') startCard(text);
    else startPill(text);
  } else if (state.mode === 'ask') {
    mockAnswer(text);
  } else {
    mockAct(text);
  }
}

function followup(raw) {
  const text = raw.trim() || (state.mode === 'act' ? $('#followup').placeholder : '');
  if (!text) return;
  if (bridge) {
    bridge.followup(text, state.mode);
    if (state.mode === 'ask') startCard(text);
    else startPill(text);
  } else if (state.mode === 'ask') {
    mockAnswer(text);
  } else {
    mockAct(text);
  }
}

$('#input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    submit(e.target.value, e.ctrlKey && state.hasRecent);
  } else if (e.key === 'Tab') {
    e.preventDefault();
    setMode(state.mode === 'ask' ? 'act' : 'ask');
    if (bridge) bridge.setView('input'); // 让宿主同步浮层的模式色
  }
});

$('#followup').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    e.preventDefault();
    followup(e.target.value);
  } else if (e.key === 'Tab') {
    e.preventDefault();
    setMode(state.mode === 'ask' ? 'act' : 'ask');
  }
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    e.preventDefault();
    dismiss();
  }
});

$('#close').addEventListener('click', dismiss);
// 👍 / 👎：回传给路由，让它学会哪类任务该交给谁
for (const [id, value] of [['#rate-good', 1], ['#rate-bad', -1]]) {
  $(id).addEventListener('click', () => {
    if ($('#card-view').classList.contains('rated')) return;
    $(id).classList.add('chosen');
    $('#card-view').classList.add('rated');
    if (bridge) bridge.feedback(value);
  });
}
$('#copy-all').addEventListener('click', () => copyText(live.draft || $('#answer').innerText));
$('#dock-close').addEventListener('click', dismiss);
$('#dock-expand').addEventListener('click', () => {
  if (bridge) bridge.expandDock(); // 宿主先让窗口能拿到焦点，再切回卡片
  else app.restore();
});
$('#dock-view').addEventListener('mousemove', armDockTimer);
$('#dock-steps').addEventListener('click', (e) => {
  armDockTimer();
  if (e.target.closest('pre, a, button')) return;
  const li = e.target.closest('li');
  if (li) li.classList.toggle('done');
});
$('#toast-view').addEventListener('mouseenter', () => clearTimeout(state.toastTimer));
$('#toast-view').addEventListener('mouseleave', armToastTimer);
$('#toast-detail').addEventListener('click', (e) => { e.preventDefault(); openResultCard(false); });
$('#toast-followup').addEventListener('click', (e) => { e.preventDefault(); openResultCard(true); });

// 宿主按内容尺寸调整窗口
new ResizeObserver(() => {
  const r = $('#root').getBoundingClientRect();
  if (bridge) bridge.contentSize(Math.ceil(r.width), Math.ceil(r.height));
}).observe($('#root'));

// ---------- 宿主调用的接口 ----------

const app = {
  showInput(opts = {}) {
    stopAll();
    if (opts.theme) html.dataset.theme = opts.theme;
    if (opts.lang) I18N.setLang(opts.lang);
    if (opts.answerMax) html.style.setProperty('--answer-max', `${opts.answerMax}px`);
    state.placeholders = { ...(opts.placeholders || {}) };
    state.hasRecent = Boolean(opts.hasRecent);
    setMode(opts.mode || 'ask');
    $('#recent-hint').hidden = !state.hasRecent;
    const input = $('#input');
    input.value = '';
    show('input');
    input.focus();
    requestAnimationFrame(() => requestAnimationFrame(() => bridge && bridge.shown()));
  },
  setPlaceholders(placeholders) {
    state.placeholders = { ...state.placeholders, ...placeholders };
    $('#input').placeholder = placeholderFor(state.mode);
  },
  // 换语言（zh / en）：静态文字由 I18N 换掉，这里再刷新脚本写上去的（模式标签、推荐问题、提示、按钮说明）
  setLang(code) {
    I18N.setLang(code);
    setMode(state.mode);
    for (const btn of document.querySelectorAll('.md pre .copy')) btn.title = I18N.t('复制');
  },
  onEvent,
  restore() {
    if (live.question) {
      show('card');
      renderMarkdown($('#answer'), live.draft, !live.done);
    }
  },
  mode() { return state.mode; },
  submit(text = '') { submit(text); },
  setTheme(theme) { html.dataset.theme = theme; },
  dock,
  stop() { stopAll(); },
};
window.app = app;

// ---------- 浏览器预览：模拟数据 ----------

const MOCK_STATUS = ['正在看截图…', '正在查看 Python 环境…'];
const MOCK_ANSWER = '运行这个脚本的 Python 环境里没有安装 pandas。\n\n1. 在同一个环境里安装：\n\n   ```\n   python -m pip install pandas\n   ```\n\n2. 重新运行脚本。\n\n如果装了还报错，多半是电脑上有好几个 Python，pandas 装到了别的环境里。';
const MOCK_STEPS = ['正在确认脚本用的是哪个 Python', '正在安装 pandas', '正在重新运行脚本'];

async function mockAnswer(question) {
  startCard(question);
  const run = state.run;
  for (const text of MOCK_STATUS) {
    onEvent({ type: 'status', text });
    await later(800);
    if (run !== state.run) return;
  }
  for (let i = 0; i < MOCK_ANSWER.length; i += 3) {
    onEvent({ type: 'delta', text: MOCK_ANSWER.slice(i, i + 3) });
    await later(16);
    if (run !== state.run) return;
  }
  onEvent({ type: 'done', ok: true });
}

async function mockAct(task) {
  startPill(task);
  const run = state.run;
  for (const text of MOCK_STEPS) {
    await later(1300);
    if (run !== state.run) return;
    onEvent({ type: 'status', text });
  }
  await later(1300);
  if (run !== state.run) return;
  onEvent({ type: 'delta', text: '已安装 pandas，脚本运行正常。\n\n想撤销的话：`python -m pip uninstall pandas`' });
  onEvent({ type: 'done', ok: true });
}

// ---------- 启动 ----------

if (window.qt && qt.webChannelTransport && window.QWebChannel) {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bridge.ready();
  });
} else {
  document.body.classList.add('preview');
  $('#demo').hidden = false;
  if (matchMedia('(prefers-color-scheme: light)').matches) html.dataset.theme = 'light';
  if (new URLSearchParams(location.search).get('lang') === 'en') app.setLang('en'); // ?lang=en 预览英文
  app.showInput({ mode: 'ask' });
  $('#demo').addEventListener('click', (e) => {
    const action = e.target.dataset.demo;
    if (action === 'ask' || action === 'act') app.showInput({ mode: action });
    else if (action === 'answer') { setMode('ask'); mockAnswer(placeholderFor('ask')); }
    else if (action === 'pill') { setMode('act'); mockAct(placeholderFor('act')); }
    else if (action === 'toast') { setMode('act'); live.question = placeholderFor('act'); showToast('已安装 pandas，脚本运行正常'); }
    else if (action === 'dock') { Object.assign(live, { question: placeholderFor('ask'), draft: MOCK_ANSWER, done: true }); dock(); }
    else if (action === 'theme') html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
  });
}
