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
const STOP_TOAST_MS = 15000; // 按 Esc 停下后的提示多留一会儿：问你是不是助手哪里没做好
const THANKS_MS = 1500;
// 原因选项（交给自我改进）：stop = 按 Esc 停下以后，bad = 点了 👎 以后。不答就当不是助手的问题
const REASONS = {
  stop: [['wrong', '做错了'], ['slow', '太慢 / 卡住了'], ['misunderstood', '没懂我的意思'], ['not_assistant', '不是助手的问题']],
  bad: [['wrong', '答错了'], ['screen', '没看懂屏幕'], ['verbose', '太啰嗦'], ['slow', '太慢']],
};
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
  pillAnim: null, // 胶囊正在展开或收起
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
  document.body.classList.remove('parked');
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
    const code = pre.innerText.replace(/\s+$/, ''); // 不带结尾的换行：粘到终端里不会直接执行
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
  updateFades(answer);
}

// 只在还有内容没露出来的那一边渐隐：滚到顶时第一行、滚到底时最后一行都是清楚的
function updateFades(box) {
  const overflow = box.scrollHeight > box.clientHeight + 1;
  box.classList.toggle('fade-top', overflow && box.scrollTop > 1);
  box.classList.toggle('fade-bottom', overflow && box.scrollTop + box.clientHeight < box.scrollHeight - 1);
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
  $('#bad-reasons').hidden = true;
}

// 一行原因：几个选项 + 一句补充。选了或回车就交出去，显示一句"谢谢"后收起
function showReasons(box, kind, onDone) {
  box.innerHTML = '';
  const send = (choice, text) => {
    if (bridge && choice !== 'not_assistant') bridge.reason(kind, choice, text);
    box.innerHTML = '';
    const thanks = el('span', 'thanks');
    thanks.textContent = choice === 'not_assistant' ? I18N.t('好的') : I18N.t('谢谢，助手会据此改进自己');
    box.append(thanks);
    state.timers.push(setTimeout(() => { box.hidden = true; onDone(); }, THANKS_MS));
  };
  if (kind === 'bad') {
    const q = el('span', 'reasons-q');
    q.textContent = I18N.t('哪里不好？');
    box.append(q);
  }
  for (const [choice, label] of REASONS[kind]) {
    const chip = el('button', 'reason-chip');
    chip.textContent = I18N.t(label);
    chip.addEventListener('click', () => send(choice, input.value.trim()));
    box.append(chip);
  }
  const input = el('input', 'reason-input');
  input.type = 'text';
  input.spellcheck = false;
  input.placeholder = I18N.t('说说原因（可选），回车');
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && input.value.trim()) {
      e.preventDefault();
      e.stopPropagation();
      send('', input.value.trim());
    }
  });
  input.addEventListener('focus', () => clearTimeout(state.toastTimer));
  box.append(input);
  box.hidden = false;
}

function startCard(question) {
  stopAll();
  resetRating();
  Object.assign(live, { question, draft: '', statuses: [], done: false, error: '' });
  $('#question').textContent = question;
  $('#question').title = '';
  $('#answer').innerHTML = '';
  $('#answer').classList.remove('scrollable', 'fade-top', 'fade-bottom');
  $('#steps').hidden = true;
  $('#followup').value = '';
  setStatus(I18N.t('正在看你的屏幕…'));
  $('#card-view').classList.add('thinking');
  show('card');
}

function startPill(task) {
  stopAll();
  Object.assign(live, { question: task, draft: '', statuses: [], done: false, error: '' });
  $('#pill').classList.remove('open');
  $('#pill-row').title = I18N.t('展开');
  $('#pill-task').textContent = task;
  $('#pill-steps').innerHTML = '';
  $('#pill-text').textContent = I18N.t('正在理解任务…');
  $('#pill-time').textContent = '0:00';
  const note = $('#pill-note');
  note.hidden = false;
  note.classList.remove('faded');
  show('pill');
  requestAnimationFrame(() => reportPillArea());
  later(PILL_NOTE_MS).then(() => {
    note.classList.add('faded');
    return later(450);
  }).then(() => {
    note.hidden = true;
    reportPillArea();
  });
  const t0 = Date.now();
  state.ticker = setInterval(() => {
    const s = Math.floor((Date.now() - t0) / 1000);
    $('#pill-time').textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }, 250);
}

// 胶囊点开成小窗：看得到任务和做过的每一步；点底下那一行收回去。窗口大小不变，只是页面里的形变动画
function setPillOpen(open) {
  const pill = $('#pill');
  if (state.view !== 'pill' || state.pillAnim || pill.classList.contains('open') === open) return;
  const from = pill.getBoundingClientRect();
  pill.classList.add('open');
  if (open) {
    $('#pill-note').hidden = true;
    renderPillSteps();
  }
  const big = pill.getBoundingClientRect();
  pill.classList.toggle('open', open);
  const to = pill.getBoundingClientRect();
  pill.classList.add('open'); // 收起的时候内容先留着，跟着缩回去，结束后再收
  reportPillArea(big); // 动画期间窗口形状取展开后的大小
  const ease = 'cubic-bezier(0.2, 0.8, 0.2, 1)';
  const morph = pill.animate([
    { width: `${from.width}px`, height: `${from.height}px` },
    { width: `${to.width}px`, height: `${to.height}px` },
  ], { duration: open ? 280 : 220, easing: ease, fill: 'forwards' });
  const fade = $('#pill-detail').animate(open ? [{ opacity: 0 }, { opacity: 1 }] : [{ opacity: 1 }, { opacity: 0 }],
    { duration: open ? 200 : 120, delay: open ? 70 : 0, easing: 'ease-out', fill: 'both' });
  state.pillAnim = morph;
  morph.finished.catch(() => {}).then(() => {
    state.pillAnim = null;
    pill.classList.toggle('open', open);
    morph.cancel(); // 动画停在最后一帧，换好样式再撤掉：中间不会露出一帧原来的大小
    fade.cancel();
    $('#pill-row').title = I18N.t(open ? '收起' : '展开');
    reportPillArea();
  });
}

function stepRows(box, statuses, current = -1) {
  box.innerHTML = '';
  statuses.forEach((s, i) => {
    const row = el('div', i === current ? 'now' : '');
    const text = el('span');
    text.textContent = s;
    row.title = s;
    row.appendChild(text);
    box.appendChild(row);
  });
}

function renderPillSteps() {
  const box = $('#pill-steps');
  stepRows(box, live.statuses, live.done ? -1 : live.statuses.length - 1);
  box.scrollTop = box.scrollHeight;
}

// 宿主只保留胶囊（展开时是小窗）连同阴影的那一块窗口，别处的点击穿过去
function reportPillArea(rect) {
  if (!bridge || state.view !== 'pill') return;
  let { left, top, right, bottom } = rect || $('#pill').getBoundingClientRect();
  const note = $('#pill-note');
  if (!note.hidden) {
    const n = note.getBoundingClientRect();
    left = Math.min(left, n.left);
    right = Math.max(right, n.right);
    bottom = Math.max(bottom, n.bottom);
  }
  const pad = 16;
  bridge.pillArea(Math.floor(left - pad), Math.floor(top - pad), Math.ceil(right - left) + 2 * pad,
    Math.ceil(bottom - top) + 2 * pad);
}

function setStatus(text, isError = false) {
  const line = $('#status-line');
  line.innerHTML = text ? `<span class="${isError ? 'error-text' : 'shimmer'}">${escapeHtml(text)}</span>` : '';
}

function showRoute(ev) {
  $('#question').title = ev ? I18N.t('由 {engine} · {model} · 思考强度 {effort} 回答',
    { engine: ENGINE_NAME[ev.engine] || ev.engine, model: ev.model, effort: ev.effort }) : '';
}

function onEvent(ev) {
  switch (ev.type) {
    case 'route': {
      live.route = ev;
      showRoute(ev);
      break;
    }
    case 'status': {
      if (!ev.text) break;
      // "正在思考…"这类只是让你知道它在想，不算一步，不进步骤列表
      if (!ev.transient && live.statuses[live.statuses.length - 1] !== ev.text) live.statuses.push(ev.text);
      if (state.view === 'pill') {
        $('#pill-text').textContent = ev.text;
        if ($('#pill').classList.contains('open') && !ev.transient) renderPillSteps();
      } else if (state.view === 'card' && !live.draft) setStatus(ev.text);
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

// 结果提示的一句话：汇报的第一行，去掉 Markdown 记号（`代码`、**加粗**、[链接](地址)）和"已完成："这个前缀（对勾已经说明了）。
// 开头只去掉列表、引用、标题的记号（"1. "这种编号也算）；"3 个文件已删除"开头的数字是正文，原来被当成编号删掉了
function summaryLine(markdown) {
  const line = markdown.split('\n').map((s) => s.replace(/^(?:[#>*\-\s`]|\d+[.)](?=\s|$))+/, '')
    .replace(/\[([^\]]*)\]\([^)]*\)/g, '$1').replace(/\*\*|__|`/g, '')
    .replace(/^(已完成|done)\s*[:：]\s*/i, '').trim()).find(Boolean);
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
    if (ev.stopped) { // 你按 Esc 停下的：问一句是不是助手哪里没做好（不答就当不是）
      showToast(I18N.t('已停止 · 是助手哪里没做好吗？'), true, true);
      return;
    }
    const ok = ev.ok && !live.error;
    // 汇报自己写了"没完成：…"（英文 Not done: …）或者是修法提示的，原样显示，不再套一层"没有完成"
    const failed = /^(没完成|未完成|暂未|未能|没能|浏览器操作|not done|not completed|couldn't|could not|unable to|failed|browser control)/i
      .test(live.error) ? live.error
      : I18N.t('没有完成：{reason}', { reason: live.error || I18N.t('出错了') });
    showToast(ok ? (summaryLine(live.draft) || I18N.t('已完成')) : failed, ok);
  }
}

function showToast(title, ok = true, stopped = false) {
  $('#toast-title').textContent = title;
  const toast = $('#toast-view');
  toast.classList.toggle('failed', !ok);
  toast.classList.toggle('stopped', stopped);
  const reasons = $('#stop-reasons');
  if (stopped) showReasons(reasons, 'stop', dismiss);
  else reasons.hidden = true;
  show('toast');
  armToastTimer();
}

function armToastTimer() {
  clearTimeout(state.toastTimer);
  const asking = !$('#stop-reasons').hidden;
  state.toastTimer = setTimeout(() => {
    if (state.view === 'toast' && document.activeElement?.className !== 'reason-input') dismiss();
  }, asking ? STOP_TOAST_MS : TOAST_MS);
}

function openResultCard(focusFollowup) {
  stopAll();
  resetRating();
  $('#question').textContent = live.question;
  setStatus(live.error || '', Boolean(live.error));
  const steps = $('#steps');
  stepRows(steps, live.statuses);
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
    if (state.mode === 'ask') {
      startCard(text);
      showRoute(live.route); // 接着问还是同一个对话：悬停问题照样看得到由谁回答（换了配置会再报上来）
    } else {
      startPill(text);
    }
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
    if (value < 0) { // 👎：这次没答好（交给自我改进）。原因可选，填了分析得更准
      showReasons($('#bad-reasons'), 'bad', () => {});
      $('#bad-reasons .reason-input').focus();
    }
  });
}
$('#copy-all').addEventListener('click', () => copyText(live.draft || $('#answer').innerText));
$('#answer').addEventListener('scroll', (e) => updateFades(e.currentTarget), { passive: true });
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
$('#pill-row').addEventListener('click', () => setPillOpen(!$('#pill').classList.contains('open')));
new ResizeObserver(() => { if (!state.pillAnim) reportPillArea(); }).observe($('#pill')); // 步骤说明变长变短
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
      $('#followup').focus(); // 找回来就能接着问，不用先点一下追问框
    }
  },
  mode() { return state.mode; },
  submit(text = '') { submit(text); },
  setTheme(theme) { html.dataset.theme = theme; },
  dock,
  // 宿主把窗口收到屏幕外时调用：什么都不画。下次召唤窗口一挪回来，网页重画好之前露出的是窗口最后的一帧，
  // 不能是上一次的输入框或卡片（不然旧画面会先闪一下）
  park() {
    stopAll();
    document.body.classList.add('parked');
  },
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
    else if (action === 'stopped') { setMode('act'); live.question = placeholderFor('act'); showToast(I18N.t('已停止 · 是助手哪里没做好吗？'), true, true); }
    else if (action === 'dock') { Object.assign(live, { question: placeholderFor('ask'), draft: MOCK_ANSWER, done: true }); dock(); }
    else if (action === 'theme') html.dataset.theme = html.dataset.theme === 'dark' ? 'light' : 'dark';
  });
}
