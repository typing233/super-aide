// Super Aide 准备窗口（前置检查）。状态全由宿主（setup_window.py）给出，这里只负责显示和把操作交回去；
// 在普通浏览器里打开时进入预览模式，用模拟数据。

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const html = document.documentElement;

const ORDER = ['claude', 'codex', 'dsh'];
const TITLE = { claude: 'Claude Code', codex: 'Codex', dsh: 'DeepSeek Harness' };
// 界面文字都写中文，显示时经 I18N.t() 换成当前语言
const PLACEHOLDER = {
  claude: { base: 'https://api.example.com（留空 = Anthropic 官方 API）', model: '可选，例如 claude-opus-5-5' },
  codex: { base: 'https://api.example.com/v1（留空 = OpenAI 官方 API）', model: '服务列不出模型时要填，例如 gpt-6-astra' },
};
// 自定义服务地址的表单：DeepSeek Harness 只要一个 DeepSeek API Key
const FIELDS = {
  claude: [['base', '服务地址', 'text'], ['key', '密钥', 'password'], ['model', '模型', 'text']],
  codex: [['base', '服务地址', 'text'], ['key', '密钥', 'password'], ['model', '模型', 'text']],
  dsh: [['key', 'API Key', 'password']],
};

let bridge = null;
const state = {
  data: null,
  forms: {},   // 打开着的自定义服务地址表单：工具 → {base, key, model, msg, cls, saving}
  typed: {},   // 这次保存成功的地址和密钥：另一个工具可以一键沿用
  changing: new Set(), // 已经配好、但点了"更改"的
  saved: {},   // 刚保存的结果：表单收起后留在那一行下面，原来 1.4 秒就跟着表单一起消失、来不及看
};

// ---------- 基础 ----------

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

function button(text, cls, onClick) {
  const node = el('button', cls, text);
  node.addEventListener('click', onClick);
  return node;
}

// ---------- 显示 ----------

function update(data) {
  state.data = typeof data === 'string' ? JSON.parse(data) : data;
  if (state.data.lang !== I18N.lang) I18N.setLang(state.data.lang); // 宿主给的语言（zh / en）
  render();
}

function render() {
  const d = state.data;
  html.dataset.theme = d.resolved_theme;
  $('#title').textContent = d.first_run ? I18N.t('准备超级助手') : I18N.t('环境检查');
  $('#start').textContent = d.first_run ? I18N.t('开始使用') : I18N.t('完成');
  $('#decide').hidden = !d.ask;
  renderTools();
  const busy = Object.keys(d.busy).length > 0;
  $('#start').disabled = !d.can_start;
  $('#hint').textContent = d.can_start ? (busy ? I18N.t('还在安装，可以先开始用') : '')
    : (busy ? I18N.t('正在安装…') : I18N.t('至少配好一个引擎才能开始'));
  $('#note').textContent = d.note || '';
}

function renderTools() {
  const root = $('#tools');
  // 正在输入的表单不能因为一次刷新丢掉：先把输入框里的值收回来
  for (const [name, form] of Object.entries(state.forms)) {
    const box = root.querySelector(`.tool[data-tool="${name}"] .form`);
    if (box) for (const field of ['base', 'key', 'model']) {
      const input = box.querySelector(`[data-field="${field}"]`);
      if (input) form[field] = input.value;
    }
  }
  const focused = document.activeElement && document.activeElement.dataset.field
    ? [document.activeElement.closest('.tool').dataset.tool, document.activeElement.dataset.field] : null;
  root.innerHTML = '';
  for (const name of ORDER) {
    const t = state.data.tools[name];
    if (name === 'dsh' && !t.installed) continue; // DSH 是可选的：没装就不提
    root.append(toolRow(name, t));
  }
  if (focused) {
    const input = root.querySelector(`.tool[data-tool="${focused[0]}"] [data-field="${focused[1]}"]`);
    if (input) input.focus();
  }
}

function toolRow(name, t) {
  const d = state.data;
  const box = el('div', 'tool');
  box.dataset.tool = name;
  const row = el('div', 'row');
  const label = el('div', 'label', t.title);
  const small = el('small');
  const pill = el('span', 'status-pill');
  const actions = el('div', 'tool-actions');
  const busy = d.busy[name];
  const error = d.errors[name];
  const waiting = d.waiting.includes(name);
  const core = name !== 'dsh';
  let more = null;

  if (busy) {
    setPill(pill, 'busy', I18N.t('安装中'));
    small.textContent = busy;
    small.classList.add('shimmer');
  } else if (error) {
    setPill(pill, 'bad', I18N.t('没装上'));
    small.textContent = d.manual[name]
      ? I18N.t('{error}。也可以自己运行：{command}', { error, command: d.manual[name] }) : error;
    small.classList.add('error');
    actions.append(button(I18N.t('重试'), 'text-btn outline', () => install([name])));
  } else if (!t.installed) {
    setPill(pill, 'idle', I18N.t('未安装'));
    small.textContent = d.use_dsh ? I18N.t('不装也行：现在先用 DeepSeek Harness') : I18N.t('还没装');
    if (!d.ask) actions.append(button(I18N.t('安装'), 'text-btn outline', () => install([name]))); // 上面问着的时候不重复给按钮
  } else if (!t.configured && waiting) {
    setPill(pill, 'busy', I18N.t('等待登录'));
    small.textContent = I18N.t('在弹出的窗口里完成登录，好了这里会自动显示');
    actions.append(button(I18N.t('重新打开登录窗口'), 'text-btn', () => login(name)));
    if (core) actions.append(button(I18N.t('改用自定义服务地址'), 'text-btn', () => openForm(name)));
  } else if (!t.configured || state.changing.has(name)) {
    if (t.configured) {
      setPill(pill, 'ok', core ? I18N.t('已就绪') : I18N.t('可用'));
      small.textContent = t.detail;
    } else {
      setPill(pill, 'idle', core ? I18N.t('未配置模型') : I18N.t('未登录'));
      small.textContent = t.detail;
    }
    if (core) {
      actions.append(button(I18N.t('用账号登录'), 'text-btn outline', () => login(name)));
      actions.append(button(I18N.t('自定义服务地址'), 'text-btn outline', () => openForm(name)));
      if (state.changing.has(name) && !state.forms[name]) actions.append(button(I18N.t('取消'), 'text-btn', () => closeForm(name)));
    } else {
      actions.append(button(I18N.t('打开 DeepSeek Harness 登录'), 'text-btn outline', () => login(name)));
      actions.append(button(I18N.t('填 DeepSeek API Key'), 'text-btn outline', () => openForm(name)));
    }
  } else {
    setPill(pill, 'ok', core ? I18N.t('已就绪') : (d.use_dsh ? I18N.t('使用中') : I18N.t('可用')));
    small.textContent = core ? t.detail : I18N.t('可选替代 · {detail}', { detail: t.detail });
    if (core) {
      more = button(I18N.t('更改'), 'text-btn more-btn', () => {
        state.changing.add(name);
        render();
      });
    }
  }
  label.append(small);
  if (state.saved[name] && !state.forms[name]) label.append(el('small', 'confirmed', state.saved[name]));
  row.append(label);
  if (more) row.append(more);
  row.append(pill);
  box.append(row, actions);
  if (state.forms[name]) box.append(customForm(name));
  return box;
}

function setPill(pill, cls, text) {
  pill.className = `status-pill ${cls}`;
  pill.textContent = text;
}

// ---------- 自定义服务地址 ----------

function openForm(name) {
  delete state.saved[name];
  state.forms[name] = state.forms[name] || { base: '', key: '', model: '', msg: '', cls: '' };
  render();
  const input = $(`.tool[data-tool="${name}"] [data-field="${FIELDS[name][0][0]}"]`);
  if (input) input.focus();
}

function closeForm(name) {
  delete state.forms[name];
  state.changing.delete(name);
  render();
}

function customForm(name) {
  const f = state.forms[name];
  const form = el('div', 'form');
  for (const [field, text, type] of FIELDS[name]) {
    const label = el('label', '', I18N.t(text));
    const input = el('input');
    input.type = type;
    input.dataset.field = field;
    input.value = f[field] || '';
    input.placeholder = field === 'key' ? (name === 'dsh' ? I18N.t('sk-…，在 platform.deepseek.com 创建') : I18N.t('必填'))
      : I18N.t(PLACEHOLDER[name][field]);
    input.spellcheck = false;
    input.autocomplete = 'off';
    input.addEventListener('input', () => { f[field] = input.value; });
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') save(name);
    });
    form.append(label, input);
  }
  const other = name === 'claude' ? 'codex' : 'claude';
  if (name !== 'dsh' && state.typed[other] && !f.base && !f.key) {
    form.append(button(I18N.t('用和 {name} 一样的地址和密钥', { name: TITLE[other] }), 'text-btn copy-link', () => {
      f.base = state.typed[other].base;
      f.key = state.typed[other].key;
      render();
    }));
  }
  const foot = el('div', 'form-foot');
  const msg = el('span', `form-msg ${f.cls || ''}`, f.saving ? I18N.t('正在测试连接…') : f.msg);
  if (f.saving) msg.classList.add('shimmer');
  const save_ = button(I18N.t('测试并保存'), 'primary small', () => save(name));
  save_.disabled = Boolean(f.saving);
  foot.append(msg, button(I18N.t('取消'), 'text-btn', () => closeForm(name)), save_);
  form.append(foot);
  return form;
}

async function save(name) {
  const f = state.forms[name];
  if (!f || f.saving) return;
  if (!f.key.trim()) {
    f.msg = I18N.t('请填写密钥');
    f.cls = 'error';
    render();
    return;
  }
  f.saving = true;
  f.msg = '';
  render();
  call('saveCustom', name, (f.base || '').trim(), f.key.trim(), (f.model || '').trim());
}

function saved(name, result) {
  const f = state.forms[name];
  if (!f) return;
  f.saving = false;
  f.msg = result.message;
  f.cls = result.ok ? 'ok' : 'error';
  if (result.ok) {
    state.typed[name] = { base: f.base, key: f.key };
    state.saved[name] = result.message;
    setTimeout(() => { if (state.forms[name] && !state.forms[name].saving) closeForm(name); }, 1400);
  }
  render();
}

// ---------- 操作 ----------

function install(tools) {
  call('install', JSON.stringify(tools));
}

function login(name) {
  state.changing.delete(name);
  call('login', name);
}

$('#install-all').addEventListener('click', () => install(['claude', 'codex'].filter((n) => !state.data.tools[n].installed)));
$('#use-dsh').addEventListener('click', () => call('chooseDsh'));
$('#recheck').addEventListener('click', () => call('recheck'));
$('#start').addEventListener('click', () => call('finish'));
$('#close').addEventListener('click', () => call('close'));
$('#titlebar').addEventListener('mousedown', (e) => {
  if (e.button === 0 && !e.target.closest('button')) call('startDrag');
});

document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  const open = Object.keys(state.forms);
  if (open.length) closeForm(open[open.length - 1]);
  else call('close');
}, true);

// ---------- 宿主调用的接口 ----------

window.setup = { update, saved };

// ---------- 浏览器预览：模拟数据 ----------

const PREVIEW_LANG = new URLSearchParams(location.search).get('lang') === 'en' ? 'en' : 'zh'; // ?lang=en 预览英文
const hostText = (zh, en) => (PREVIEW_LANG === 'en' ? en : zh); // 宿主给的文字已经是当前语言，预览里也一样

const PREVIEW_DATA = {
  first_run: true,
  lang: PREVIEW_LANG,
  resolved_theme: matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark',
  tools: {
    claude: { title: 'Claude Code', installed: true, configured: false,
              detail: hostText('还没配置模型', 'No model set up yet'), via: 'cli' },
    codex: { title: 'Codex', installed: false, configured: false,
             detail: hostText('还没配置模型', 'No model set up yet'), via: '' },
    dsh: { title: 'DeepSeek Harness', installed: true, configured: true,
           detail: hostText('DeepSeek 账号登录', 'Signed in with a DeepSeek account'), via: 'desktop' },
  },
  busy: {},
  errors: {},
  waiting: [],
  manual: { claude: 'npm i -g @anthropic-ai/claude-code', codex: 'npm i -g @openai/codex' },
  ask: true,
  use_dsh: false,
  can_start: true,
  note: '',
};

const preview = {
  load: () => JSON.stringify(PREVIEW_DATA),
  install: (tools) => {
    PREVIEW_DATA.ask = false;
    for (const t of JSON.parse(tools)) {
      PREVIEW_DATA.busy[t] = hostText('正在从国内镜像 npmmirror 安装…', 'Installing from the npmmirror mirror (China)…');
    }
    update(PREVIEW_DATA);
  },
  chooseDsh: () => {
    PREVIEW_DATA.ask = false;
    PREVIEW_DATA.use_dsh = true;
    update(PREVIEW_DATA);
  },
  login: (name) => {
    PREVIEW_DATA.waiting.push(name);
    update(PREVIEW_DATA);
  },
  saveCustom: (name) => setTimeout(() => saved(name, {
    ok: true, message: hostText('连接成功，找到 12 个模型', 'Connected, found 12 models') }), 800),
};

// ---------- 启动 ----------

async function start() {
  update(await call('load'));
  if (bridge) bridge.rendered(); // 宿主等画好了再显示窗口
}

if (window.qt && qt.webChannelTransport && window.QWebChannel) {
  new QWebChannel(qt.webChannelTransport, (channel) => {
    bridge = channel.objects.bridge;
    start();
  });
} else {
  document.body.classList.add('preview');
  if (PREVIEW_LANG === 'en') I18N.setLang('en');
  start();
}
