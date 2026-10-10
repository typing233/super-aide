// Super Aide 新手指引。状态全由宿主（shell/tour_window.py，步骤在 tour.py）给出，这里只负责显示：
// 欢迎页在屏幕正中；开始以后是一个小气泡，贴在要你看的东西旁边（宿主摆位置、告诉尾巴朝哪），只写要按的键和一两个词。
// 在普通浏览器里打开时进入预览模式，用模拟数据。

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const html = document.documentElement;

const CHECK = '<svg viewBox="0 0 20 20"><path d="M5 10.5l3.2 3.2L15 7"/></svg>';

let bridge = null;
const state = { data: null, key: '' };

// ---------- 基础 ----------

function call(method, ...args) {
  if (bridge) bridge[method](...args);
  else if (preview[method]) preview[method](...args);
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

function replay(node, cls) {
  node.classList.remove(cls);
  void node.offsetWidth; // 重新触发动画
  node.classList.add(cls);
}

// ---------- 显示 ----------

function update(data) {
  state.data = data;
  if (data.lang !== I18N.lang) I18N.setLang(data.lang);
  html.dataset.theme = data.theme;
  html.dataset.layout = data.layout;
  document.body.classList.remove('parked');
  if (data.layout === 'welcome') renderWelcome();
  else renderBubble();
}

function renderWelcome() {
  html.dataset.mode = 'ask';
  $('#bubble').hidden = true;
  const box = $('#welcome');
  box.classList.remove('leaving');
  box.hidden = false;
  // *…* 包着的几个字用模式色渐变强调
  $('#w-title').innerHTML = escapeHtml(I18N.t('按一个键，说一句话，*就办好。*')).replace(/\*([^*]+)\*/g, '<em>$1</em>');
  state.key = '';
  reportSize(); // 窗口这时还藏着（藏着的网页不跑 requestAnimationFrame）：直接量一次报上去，宿主才摆好、显示
  $('#w-start').focus();
}

function renderBubble() {
  const d = state.data;
  $('#welcome').hidden = true;
  const bubble = $('#bubble');
  const key = JSON.stringify([d.stage, d.step, d.target, d.lang]);
  if (key !== state.key || bubble.hidden) {
    state.key = key;
    bubble.hidden = false;
    bubble.className = 'bubble pending'; // 宿主摆好位置（place）以前不露面：不会在旧位置闪一下新内容
    html.dataset.mode = d.step ? d.step.mode : 'ask';
    const main = $('#b-main');
    main.innerHTML = '';
    if (d.stage === 'done') {
      const check = el('span', 'b-check');
      check.innerHTML = CHECK;
      main.append(check, el('span', 'b-label', I18N.t('都会了')));
      $('#b-meta').hidden = true;
    } else {
      const s = d.step;
      if (s.keys.length) {
        const keys = el('span', 'b-keys');
        for (const k of s.keys) keys.append(el('kbd', '', k));
        main.append(keys);
      }
      main.append(label(s.label));
      const dots = $('#b-dots');
      dots.innerHTML = '';
      for (let i = 0; i < d.stages; i += 1) dots.append(el('i', i === s.dot ? 'on' : ''));
      $('#b-meta').hidden = false;
      $('#b-skip').hidden = s.last; // 最后一步：不是"跳过"，是"完成"
      $('#b-done').hidden = !s.last;
    }
    bubble.classList.toggle('big', d.target === 'center' && d.stage !== 'done');
  }
  reportSize();
}

// 文字里的 ● 画成托盘图标那样的小圆点
function label(text) {
  const span = el('span', 'b-label');
  text.split('●').forEach((part, i) => {
    if (i) span.append(el('span', 'orb'));
    if (part.trim()) span.append(part.trim());
  });
  return span;
}

// 宿主摆好了窗口：尾巴朝哪（up / down / left / right / none）、尾巴尖在窗口里的位置
function place(p) {
  const bubble = $('#bubble');
  bubble.dataset.tail = p.tail;
  const r = bubble.getBoundingClientRect();
  const at = p.tail === 'up' || p.tail === 'down' ? p.at - r.left : p.at - r.top;
  bubble.style.setProperty('--tail-at', `${Math.round(at)}px`);
  if (p.pop || bubble.classList.contains('pending')) {
    bubble.classList.remove('pending');
    replay(bubble, 'pop');
  }
}

function reportSize() {
  const r = $('#root').getBoundingClientRect();
  if (bridge) bridge.contentSize(Math.ceil(r.width), Math.ceil(r.height));
}

// ---------- 交互 ----------

function start() {
  $('#welcome').classList.add('leaving');
  setTimeout(() => {
    document.body.classList.add('parked'); // 宿主把窗口挪走之前什么都不画
    call('start');
  }, 120);
}

$('#w-start').addEventListener('click', start);
$('#w-skip').addEventListener('click', () => call('close', 'skipped'));
$('#b-skip').addEventListener('click', () => call('close', 'closed'));
$('#b-done').addEventListener('click', () => call('done'));

document.addEventListener('keydown', (e) => {
  if (html.dataset.layout !== 'welcome' || $('#welcome').hidden) return;
  if (e.key === 'Enter' && !(document.activeElement instanceof HTMLButtonElement)) { // 按钮上的回车照常点那个按钮
    e.preventDefault();
    start();
  } else if (e.key === 'Escape') {
    e.preventDefault();
    call('close', 'skipped');
  }
});

// ---------- 宿主调用的接口 ----------

window.tour = { update, place };

// ---------- 浏览器预览：模拟数据（宿主给的文字已经是当前语言；这里只放中文） ----------

const PREVIEW_STEPS = [
  { key: 'ask', target: 'center', keys: ['Alt', 'Q'], label: '提问', mode: 'ask', dot: 0 },
  { key: 'send', target: 'input', keys: ['↵'], label: '发送', mode: 'ask', dot: 0, tail: 'up' },
  { key: 'close', target: 'card', keys: ['Esc'], label: '关闭', mode: 'ask', dot: 0, tail: 'up' },
  { key: 'act', target: 'center', keys: ['Alt', 'W'], label: '让它动手', mode: 'act', dot: 1 },
  { key: 'go', target: 'input', keys: ['↵'], label: '开始', mode: 'act', dot: 1, tail: 'up' },
  { key: 'stop', target: 'pill', keys: ['Esc'], label: '随时停下', mode: 'act', dot: 1, tail: 'down' },
  { key: 'tray', target: 'tray', keys: [], label: '右键 ● 打开设置', mode: 'ask', dot: 2, tail: 'down', last: true },
];

function previewShow(i) {
  const theme = matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
  const lang = new URLSearchParams(location.search).get('lang') === 'en' ? 'en' : 'zh';
  if (i === 'welcome') {
    update({ stage: 'welcome', stages: 3, layout: 'welcome', theme, lang });
    return;
  }
  const s = i === 'done' ? null : PREVIEW_STEPS[i];
  update({ stage: s ? 'step' : 'done', stages: 3, step: s, layout: 'bubble', theme, lang, target: s ? s.target : 'center' });
  const r = $('#bubble').getBoundingClientRect();
  place({ tail: s && s.tail ? s.tail : 'none', at: r.left + Math.min(60, r.width / 2), pop: true });
}

const preview = {
  start: () => previewShow(0),
  close: () => previewShow('welcome'),
  done: () => previewShow('done'),
};

// ---------- 启动 ----------

if (window.qt && qt.webChannelTransport && window.QWebChannel) {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    bridge.ready();
  });
} else {
  document.body.classList.add('preview');
  const demo = $('#demo');
  demo.hidden = false;
  for (const [i, text] of [['welcome', '欢迎'], ...PREVIEW_STEPS.map((s, n) => [n, s.label]), ['done', '都会了']]) {
    const btn = el('button', '', text);
    btn.addEventListener('click', () => previewShow(i));
    demo.append(btn);
  }
  previewShow('welcome');
}
