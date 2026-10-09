// Super Aide 设置窗口。在桌面宿主里通过 QWebChannel 读写配置，每个改动立即保存并生效；
// 在普通浏览器里打开时进入预览模式，用模拟数据。

'use strict';

const $ = (sel, root = document) => root.querySelector(sel);
const html = document.documentElement;

const ENGINES = { claude: 'Claude Code', codex: 'Codex', dsh: 'DeepSeek Harness' };
const EFFORTS = ['low', 'medium', 'high', 'xhigh', 'max'];
const HOTKEY_LABEL = { ask: '问答', act: '操作' }; // 显示时经 I18N.t() 换成当前语言
const MODIFIER_KEYS = new Set(['Control', 'Alt', 'Shift', 'Meta']);
// 浏览器的按键码 → hotkeys.py 认识的写法
const KEY_NAMES = {
  Space: 'Space', Enter: 'Enter', Tab: 'Tab', Backspace: 'Backspace', Insert: 'Insert', Delete: 'Delete',
  Home: 'Home', End: 'End', PageUp: 'PageUp', PageDown: 'PageDown', Pause: 'Pause',
  ArrowUp: 'Up', ArrowDown: 'Down', ArrowLeft: 'Left', ArrowRight: 'Right',
  Backquote: '`', Minus: '-', Equal: '=', BracketLeft: '[', BracketRight: ']', Semicolon: ';',
  Quote: "'", Comma: ',', Period: '.', Slash: '/', Backslash: '\\',
};
const ICON = {
  chevron: '<svg viewBox="0 0 12 12"><path d="M3 4.5l3 3 3-3"/></svg>',
  check: '<svg viewBox="0 0 12 12"><path d="M2.5 6.2l2.4 2.4L9.5 3.8"/></svg>',
  cross: '<svg viewBox="0 0 12 12"><path d="M3.5 3.5l5 5M8.5 3.5l-5 5"/></svg>',
};

let bridge = null;
const state = {
  data: null,
  recording: null,       // 正在录的快捷键：'ask' | 'act'
  expanded: new Set(),   // 展开了全部模型的引擎
  order: {},             // 每个引擎的显示顺序：打开窗口时排一次（已打开的在前），之后拨开关不重排
  menuAnchor: null,
  savedTimer: null,
  refreshTimer: null,
  update: null,          // 最近一次检查更新的结果
};

// ---------- 基础 ----------

function call(method, ...args) {
  return new Promise((resolve) => {
    if (bridge) bridge[method](...args, resolve);
    else resolve(preview[method] ? preview[method](...args) : undefined);
  });
}

function el(tag, cls) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  return node;
}

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
}

function switchEl(on, label, small = false) {
  const node = el('button', `switch${small ? ' small' : ''}${on ? ' on' : ''}`);
  node.setAttribute('role', 'switch');
  node.setAttribute('aria-label', label);
  return node;
}

function setSegment(sel, value) {
  for (const b of $(sel).children) b.classList.toggle('on', b.dataset.value === value);
}

function banner(text) {
  $('#banner').textContent = text;
  $('#banner').hidden = !text;
}

function flashSaved() {
  $('#saved').classList.add('show');
  clearTimeout(state.savedTimer);
  state.savedTimer = setTimeout(() => $('#saved').classList.remove('show'), 1200);
}

// ---------- 读取与保存 ----------

async function reload() {
  state.data = JSON.parse(await call('load'));
  state.order = {};
  state.expanded.clear();
  $('#model-filter').value = '';
  banner('');
  render();
  if (bridge) bridge.rendered(); // 第一次打开时，宿主等画好了再显示窗口
  if (state.update === null || (typeof state.update === 'object' && state.update.error)) checkUpdate(); // 打开设置时顺手查一下
}

async function save() {
  const resp = JSON.parse(await call('save', JSON.stringify(state.data)));
  html.dataset.theme = resp.data.resolved_theme;
  if (resp.errors.length) {
    // 没能生效的项（比如快捷键注册不上）以宿主返回的为准
    state.data = resp.data;
    render();
    banner(resp.errors.join('\n'));
  } else {
    if (resp.data.lang !== state.data.lang) {
      // 换了语言：整页按新语言重画（界面操作那一行的说明也由宿主按新语言重新给）
      Object.assign(state.data, { lang: resp.data.lang, browser: resp.data.browser });
      render();
    }
    banner('');
    flashSaved();
  }
}

function render() {
  const d = state.data;
  I18N.setLang(d.lang); // 宿主给的语言（zh / en）：静态文字随之换掉，下面画的也都用它
  if ($('#refresh').disabled) $('#refresh').textContent = I18N.t('正在获取…'); // 换语言会把它恢复成"刷新列表"
  html.dataset.theme = d.resolved_theme;
  renderHotkeys();
  setSegment('#theme', d.appearance.theme);
  setSegment('#language', d.appearance.language);
  setSegment('#clipboard', String(d.privacy.clipboard_max_age_s));
  renderEngines();
  renderBlocked();
  $('#shadow-eval').classList.toggle('on', d.router.shadow_eval !== false);
  $('#autostart').classList.toggle('on', Boolean(d.autostart));
  const browser = d.browser || { ready: true, problem: '', official: false };
  $('#browser-status').textContent = !browser.official ? I18N.t('自研')
    : (browser.ready ? I18N.t('已接通') : I18N.t('没接通'));
  $('#browser-status').className = `status-pill ${browser.ready ? 'ok' : 'bad'}`;
  $('#browser-note').textContent = !browser.official
    ? I18N.t('Codex 没用官方账号登录，用自研的：浏览器和桌面应用都能直接操作，不需要装插件')
    : browser.ready ? I18N.t('Codex 官方账号：用它自带的 Computer Use 和 Chrome 插件')
      : browser.problem.replace(/^(浏览器操作还没接通：|Browser control isn't connected yet: )/, '');
  $('#setup-note').textContent = setupNote(d.tools || {});
  renderUpdate();
}

// ---------- 版本和更新 ----------

function renderUpdate() {
  const u = state.update;
  const note = $('#version-note');
  const btn = $('#update-btn');
  const current = state.data.version || '';
  btn.classList.remove('accent');
  btn.disabled = false;
  if (u === 'checking') {
    note.textContent = I18N.t('当前 {version} · 正在检查…', { version: current });
    btn.textContent = I18N.t('检查更新');
    btn.disabled = true;
  } else if (u === 'updating') {
    note.textContent = I18N.t('正在启动安装器，超级助手会先退出，装好后自动重新打开');
    btn.textContent = I18N.t('更新中…');
    btn.disabled = true;
  } else if (u && u.error) {
    note.textContent = I18N.t('当前 {version} · 没查到：{error}', { version: current, error: u.error });
    btn.textContent = I18N.t('重试');
  } else if (u && u.newer && u.managed) {
    note.textContent = I18N.t('当前 {version} · 有新版本 {latest}（会先退出，装好后自动重新打开）',
      { version: current, latest: u.latest });
    btn.textContent = I18N.t('更新到 {latest}', { latest: u.latest });
    btn.classList.add('accent');
  } else if (u && u.newer) {
    note.textContent = I18N.t('当前 {version} · 有新版本 {latest}。这一份是从源码装的：拉取最新代码后重新运行 install.cmd',
      { version: current, latest: u.latest });
    btn.textContent = I18N.t('检查更新');
  } else if (u) {
    note.textContent = I18N.t('当前 {version} · 已是最新', { version: current });
    btn.textContent = I18N.t('检查更新');
  } else {
    note.textContent = I18N.t('当前 {version}', { version: current });
    btn.textContent = I18N.t('检查更新');
  }
}

function checkUpdate() {
  state.update = 'checking';
  renderUpdate();
  call('checkUpdate');
}

function updateChecked(result) {
  state.update = result;
  renderUpdate();
}

async function applyUpdate() {
  const latest = state.update;
  state.update = 'updating';
  renderUpdate();
  const problem = await call('applyUpdate');
  if (problem) {
    state.update = latest;
    renderUpdate();
    banner(problem);
  }
}

// 环境检查那一行的说明：哪些装好、配好了模型
function setupNote(tools) {
  const ready = Object.keys(ENGINES).filter((n) => tools[n] && tools[n].installed && tools[n].configured);
  const pending = ['claude', 'codex'].filter((n) => tools[n] && !(tools[n].installed && tools[n].configured));
  if (!pending.length) return I18N.t('{names} 都已就绪', { names: ready.map((n) => ENGINES[n]).join(I18N.t('、')) });
  return I18N.t('{names} 还没装好或没配模型', { names: pending.map((n) => ENGINES[n]).join(I18N.t('、')) });
}

// DeepSeek Harness 是可选的：装了（或者已经在用）才显示它的模型
function engineVisible(name) {
  if (name !== 'dsh') return true;
  const t = (state.data.tools || {}).dsh;
  return Boolean((t && t.installed) || state.data.engines.dsh.enabled);
}

// ---------- 快捷键 ----------

function keycapHtml(spec) {
  return spec.split('+').map((k) => `<kbd>${escapeHtml(k)}</kbd>`).join('');
}

function hotkeyNote(text, isError = false) {
  $('#hotkey-note').textContent = text;
  $('#hotkey-note').classList.toggle('error', isError);
}

function renderHotkeys() {
  for (const node of document.querySelectorAll('.keycap')) {
    const which = node.dataset.hotkey;
    node.classList.toggle('recording', state.recording === which);
    if (state.recording !== which) node.innerHTML = keycapHtml(state.data.hotkeys[which]);
  }
}

function showPrompt() {
  const prompt = escapeHtml(I18N.t('按下新的组合键'));
  $(`.keycap[data-hotkey="${state.recording}"]`).innerHTML = `<span class="prompt shimmer">${prompt}</span>`;
}

function startRecording(which) {
  if (state.recording === which) return;
  stopRecording();
  state.recording = which;
  renderHotkeys();
  showPrompt();
  hotkeyNote(I18N.t('按 Esc 取消'));
  call('pauseHotkeys'); // 先放开现在的快捷键，不然按下去会直接召唤出界面
}

function stopRecording() {
  if (!state.recording) return;
  state.recording = null;
  renderHotkeys();
  hotkeyNote('');
  call('resumeHotkeys');
}

function keyName(code) {
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^Digit[0-9]$/.test(code)) return code.slice(5);
  if (/^F([1-9]|1[0-9]|2[0-4])$/.test(code)) return code;
  return KEY_NAMES[code] || '';
}

function recordKey(e) {
  e.preventDefault();
  e.stopPropagation();
  const mods = [];
  if (e.ctrlKey) mods.push('Ctrl');
  if (e.altKey) mods.push('Alt');
  if (e.shiftKey) mods.push('Shift');
  if (e.metaKey) mods.push('Win');
  if (MODIFIER_KEYS.has(e.key)) {
    $(`.keycap[data-hotkey="${state.recording}"]`).innerHTML = keycapHtml([...mods, '…'].join('+'));
    return;
  }
  if (e.key === 'Escape' && !mods.length) {
    stopRecording();
    return;
  }
  const key = keyName(e.code);
  if (key) finishRecording([...mods, key].join('+'));
}

async function finishRecording(spec) {
  const which = state.recording;
  const other = which === 'ask' ? 'act' : 'ask';
  stopRecording(); // 先结束录制再检查：检查要等宿主回话，期间再按键不会重复触发
  const problem = spec.toLowerCase() === state.data.hotkeys[other].toLowerCase()
    ? I18N.t('和{mode}的快捷键重复', { mode: I18N.t(HOTKEY_LABEL[other]) })
    : await call('checkHotkey', spec);
  if (problem) {
    hotkeyNote(I18N.t('{spec}：{problem}', { spec, problem }), true);
    return;
  }
  if (spec === state.data.hotkeys[which]) return;
  state.data.hotkeys[which] = spec;
  renderHotkeys();
  save();
}

// ---------- 模型 ----------

function engineCount(name) {
  const models = state.data.engines[name].models;
  return I18N.t('已打开 {on} / {total}', { on: models.filter((m) => m.enabled).length, total: models.length });
}

function checkModels() {
  const any = Object.keys(ENGINES).some((name) => {
    const eng = state.data.engines[name];
    return eng && eng.enabled && eng.models.some((m) => m.enabled);
  });
  $('#model-note').textContent = any ? '' : I18N.t('至少要打开一个模型，不然没法回答问题。');
}

function displayOrder(name) {
  const models = state.data.engines[name].models;
  if (!state.order[name]) {
    state.order[name] = [...models].sort((a, b) => Number(b.enabled) - Number(a.enabled)).map((m) => m.id);
  }
  const known = new Set(state.order[name]);
  for (const m of models) if (!known.has(m.id)) state.order[name].push(m.id); // 刚发现的排在最后
  const byId = new Map(models.map((m) => [m.id, m]));
  return state.order[name].filter((id) => byId.has(id)).map((id) => byId.get(id));
}

function modelRow(name, m, head) {
  const row = el('div', `model${m.enabled ? ' on' : ''}`);
  const sw = switchEl(m.enabled, m.id, true);
  const id = el('span', 'model-id');
  id.textContent = m.id;
  id.title = m.id;
  const effort = el('button', 'effort');
  effort.title = I18N.t('思考强度上限');
  effort.innerHTML = `<span>${escapeHtml(m.max_effort)}</span>${ICON.chevron}`;
  sw.addEventListener('click', (e) => {
    e.stopPropagation();
    m.enabled = !m.enabled;
    row.classList.toggle('on', m.enabled);
    sw.classList.toggle('on', m.enabled);
    $('.engine-count', head).textContent = engineCount(name);
    checkModels();
    save();
  });
  row.addEventListener('click', (e) => { if (!e.target.closest('.effort')) sw.click(); });
  effort.addEventListener('click', (e) => {
    e.stopPropagation();
    if (state.menuAnchor === effort) closeMenu();
    else openMenu(effort, m);
  });
  row.append(sw, id, effort);
  return row;
}

function renderEngines() {
  closeMenu();
  const root = $('#engines');
  root.innerHTML = '';
  const filter = $('#model-filter').value.trim().toLowerCase();
  for (const [name, title] of Object.entries(ENGINES)) {
    const eng = state.data.engines[name];
    if (!eng || !engineVisible(name)) continue;
    const box = el('div', `tile engine${eng.enabled ? '' : ' off'}`);
    const head = el('div', 'engine-head');
    head.innerHTML = `<span class="engine-name">${title}</span><span class="engine-count">${engineCount(name)}</span>`;
    const master = switchEl(eng.enabled, I18N.t('使用 {name}', { name: title }));
    master.addEventListener('click', () => {
      eng.enabled = !eng.enabled;
      master.classList.toggle('on', eng.enabled);
      box.classList.toggle('off', !eng.enabled);
      checkModels();
      save();
    });
    head.append(master);
    box.append(head);

    const list = el('div', 'models');
    const showAll = Boolean(filter) || state.expanded.has(name);
    let folded = 0;
    for (const m of displayOrder(name)) {
      if (filter && !m.id.toLowerCase().includes(filter)) continue;
      if (!showAll && !m.enabled) {
        folded += 1;
        continue;
      }
      list.append(modelRow(name, m, head));
    }
    if (!list.children.length && !folded) {
      const empty = el('div', 'empty');
      empty.textContent = filter ? I18N.t('没有匹配的模型') : I18N.t('还没有模型，点「刷新列表」获取');
      list.append(empty);
    }
    if (showAll && !filter) list.append(addModelRow(name));
    if (folded || (state.expanded.has(name) && !filter)) {
      const more = el('button', `more${folded ? '' : ' less'}`);
      const text = folded ? I18N.t('其它 {n} 个模型', { n: folded }) : I18N.t('收起');
      more.innerHTML = `<span>${escapeHtml(text)}</span>${ICON.chevron}`;
      more.addEventListener('click', () => {
        if (folded) state.expanded.add(name);
        else state.expanded.delete(name);
        renderEngines();
      });
      list.append(more);
    }
    box.append(list);
    root.append(box);
  }
  checkModels();
}

function addModelRow(name) {
  // 列表获取失败或者没列出来的模型，可以手动加（加了就是要用，默认打开）
  const row = el('div', 'model add');
  const input = el('input', 'add-model');
  input.placeholder = I18N.t('手动添加模型名，回车确认');
  input.spellcheck = false;
  input.addEventListener('keydown', (e) => {
    if (e.key !== 'Enter') return;
    const id = input.value.trim();
    const models = state.data.engines[name].models;
    if (!id || models.some((m) => m.id === id)) return;
    models.push({ id, enabled: true, max_effort: 'max' });
    save();
    renderEngines();
  });
  row.append(input);
  return row;
}

function openMenu(anchor, m) {
  closeMenu();
  const menu = $('#effort-menu');
  menu.innerHTML = '';
  for (const level of EFFORTS) {
    const item = el('button', level === m.max_effort ? 'on' : '');
    item.innerHTML = `<span>${level}</span>${level === m.max_effort ? ICON.check : ''}`;
    item.addEventListener('click', () => {
      m.max_effort = level;
      anchor.firstChild.textContent = level;
      closeMenu();
      save();
    });
    menu.append(item);
  }
  menu.hidden = false;
  state.menuAnchor = anchor;
  anchor.classList.add('open');
  // 放在按钮下方，靠近卡片底部放不下时放到上方
  const r = anchor.getBoundingClientRect();
  const card = $('.settings').getBoundingClientRect();
  const below = r.bottom + 4 + menu.offsetHeight <= card.bottom - 8;
  menu.style.top = `${below ? r.bottom + 4 : r.top - 4 - menu.offsetHeight}px`;
  menu.style.left = `${r.right - menu.offsetWidth}px`;
}

function closeMenu() {
  $('#effort-menu').hidden = true;
  if (state.menuAnchor) state.menuAnchor.classList.remove('open');
  state.menuAnchor = null;
}

function modelsRefreshed(result) {
  const button = $('#refresh');
  button.disabled = false;
  button.textContent = result.added ? I18N.t('新增 {n} 个', { n: result.added })
    : (result.errors.length ? I18N.t('获取失败') : I18N.t('没有新模型'));
  clearTimeout(state.refreshTimer);
  state.refreshTimer = setTimeout(() => { button.textContent = I18N.t('刷新列表'); }, 2500);
  if (result.errors.length) banner(result.errors.join('\n'));
  if (!result.added) return;
  // 只把新发现的模型并进来（默认关闭），不动其它正在显示的状态
  call('load').then((json) => {
    const fresh = JSON.parse(json);
    for (const name of Object.keys(ENGINES)) {
      const mine = state.data.engines[name];
      if (!mine || !fresh.engines[name]) continue;
      const known = new Set(mine.models.map((m) => m.id));
      for (const m of fresh.engines[name].models) if (!known.has(m.id)) mine.models.push(m);
    }
    renderEngines();
  });
}

// ---------- 隐私 ----------

function renderBlocked() {
  const box = $('#blocked');
  const input = $('#blocked-input');
  box.querySelectorAll('.chip').forEach((chip) => chip.remove());
  for (const app of state.data.privacy.blocked_apps) {
    const chip = el('span', 'chip');
    chip.innerHTML = `<span>${escapeHtml(app)}</span><button title="${escapeHtml(I18N.t('移除'))}">${ICON.cross}</button>`;
    $('button', chip).addEventListener('click', () => {
      state.data.privacy.blocked_apps = state.data.privacy.blocked_apps.filter((a) => a !== app);
      renderBlocked();
      save();
    });
    box.insertBefore(chip, input);
  }
}

function addBlocked(raw) {
  let name = raw.trim();
  if (!name) return;
  if (!/\.exe$/i.test(name)) name += '.exe';
  const list = state.data.privacy.blocked_apps;
  if (list.some((a) => a.toLowerCase() === name.toLowerCase())) return;
  list.push(name);
  renderBlocked();
  save();
}

// ---------- 事件 ----------

document.addEventListener('keydown', (e) => {
  if (state.recording) {
    recordKey(e);
    return;
  }
  if (e.key !== 'Escape') return;
  const field = document.activeElement;
  if (state.menuAnchor) {
    closeMenu();
  } else if (field && field.tagName === 'INPUT' && field.value) {
    field.value = '';
    if (field.id === 'model-filter') renderEngines();
  } else {
    call('close');
  }
}, true);

document.addEventListener('keyup', (e) => {
  // 只按了修饰键又松开：恢复提示
  if (state.recording && !(e.ctrlKey || e.altKey || e.shiftKey || e.metaKey)) showPrompt();
}, true);

document.addEventListener('mousedown', (e) => {
  if (state.menuAnchor && !e.target.closest('#effort-menu, .effort')) closeMenu();
  if (state.recording && !e.target.closest('.keycap')) stopRecording();
});

window.addEventListener('blur', stopRecording);

$('#titlebar').addEventListener('mousedown', (e) => {
  if (e.button === 0 && !e.target.closest('button')) call('startDrag');
});
$('#close').addEventListener('click', () => call('close'));
$('#open-config').addEventListener('click', (e) => {
  e.preventDefault();
  call('openConfig');
});
$('#open-setup').addEventListener('click', () => call('openSetup'));
$('#update-btn').addEventListener('click', () => {
  const u = state.update;
  if (u && typeof u === 'object' && u.newer && u.managed && !u.error) applyUpdate();
  else checkUpdate();
});
$('#scroll').addEventListener('scroll', closeMenu);

for (const node of document.querySelectorAll('.keycap')) {
  node.addEventListener('click', () => startRecording(node.dataset.hotkey));
}

$('#theme').addEventListener('click', (e) => {
  const value = e.target.closest('button')?.dataset.value;
  if (!value || value === state.data.appearance.theme) return;
  state.data.appearance.theme = value;
  setSegment('#theme', value);
  save();
});

$('#language').addEventListener('click', (e) => {
  const value = e.target.closest('button')?.dataset.value;
  if (!value || value === state.data.appearance.language) return;
  state.data.appearance.language = value;
  setSegment('#language', value);
  save(); // 宿主回来的数据带着新的 lang，save() 里整页换语言
});

$('#clipboard').addEventListener('click', (e) => {
  const value = e.target.closest('button')?.dataset.value;
  if (value === undefined) return;
  state.data.privacy.clipboard_max_age_s = Number(value);
  setSegment('#clipboard', value);
  save();
});

$('#model-filter').addEventListener('input', renderEngines);

$('#refresh').addEventListener('click', () => {
  const button = $('#refresh');
  button.disabled = true;
  button.textContent = I18N.t('正在获取…');
  call('refreshModels');
});

$('#blocked-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter') {
    addBlocked(e.target.value);
    e.target.value = '';
  }
});
$('#blocked-input').addEventListener('blur', (e) => {
  addBlocked(e.target.value);
  e.target.value = '';
});

$('#shadow-eval').addEventListener('click', () => {
  const on = state.data.router.shadow_eval === false;
  state.data.router.shadow_eval = on;
  $('#shadow-eval').classList.toggle('on', on);
  save();
});

$('#autostart').addEventListener('click', async () => {
  const on = !state.data.autostart;
  const problem = await call('setAutostart', on);
  if (problem) {
    banner(problem);
    return;
  }
  state.data.autostart = on;
  $('#autostart').classList.toggle('on', on);
  flashSaved();
});

// ---------- 宿主调用的接口 ----------

window.settings = { reload, modelsRefreshed, stopRecording, updateChecked };

// ---------- 浏览器预览：模拟数据 ----------

const PREVIEW_LANG = new URLSearchParams(location.search).get('lang') === 'en' ? 'en' : 'zh'; // ?lang=en 预览英文

const PREVIEW_DATA = {
  hotkeys: { ask: 'Alt+Q', act: 'Alt+W' },
  appearance: { theme: 'system', language: 'system' },
  privacy: { blocked_apps: ['KeePass.exe', '1Password.exe', 'Bitwarden.exe'], clipboard_max_age_s: 300 },
  safety: { blocklist: false },
  router: { llmrouter_path: '', pin_engine: '', shadow_eval: true, shadow_daily: 20 },
  engines: {
    claude: {
      enabled: true,
      models: [
        { id: 'claude-opus-5-5', enabled: true, max_effort: 'max' },
        { id: 'claude-sonnet-5-5', enabled: false, max_effort: 'max' },
        { id: 'claude-fable-5-1', enabled: false, max_effort: 'max' },
        { id: 'claude-haiku-4-5-20251001', enabled: false, max_effort: 'high' },
      ],
    },
    codex: {
      enabled: true,
      models: [
        { id: 'gpt-6-astra', enabled: true, max_effort: 'max' },
        { id: 'gpt-6-astra-mini', enabled: false, max_effort: 'xhigh' },
      ],
    },
    dsh: { enabled: false, models: [{ id: 'deepseek-flash', enabled: true, max_effort: 'max' }] },
  },
  tools: {
    claude: { installed: true, configured: true, detail: '自定义服务地址 api.example.com' },
    codex: { installed: true, configured: true, detail: 'ChatGPT 账号登录' },
    dsh: { installed: false, configured: false, detail: '' },
  },
  version: '0.1.0',
  autostart: false,
  browser: { ready: false, problem: '浏览器操作还没接通：在 Codex 应用的插件页里安装「Chrome」插件（用 ChatGPT 控制浏览器，Edge 也支持）。' },
};

function previewTheme(theme) {
  if (theme !== 'system') return theme;
  return matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

// 跟随系统：预览里就用网址指定的语言（默认中文）
function previewLang(language) {
  return language === 'zh' || language === 'en' ? language : PREVIEW_LANG;
}

const preview = {
  load: () => JSON.stringify({ ...PREVIEW_DATA, resolved_theme: previewTheme(PREVIEW_DATA.appearance.theme),
                               lang: previewLang(PREVIEW_DATA.appearance.language) }),
  save: (payload) => {
    const data = JSON.parse(payload);
    return JSON.stringify({ errors: [], data: { ...data, resolved_theme: previewTheme(data.appearance.theme),
                                                lang: previewLang(data.appearance.language) } });
  },
  checkHotkey: () => '',
  setAutostart: () => '',
  refreshModels: () => setTimeout(() => modelsRefreshed({ added: 0, errors: [] }), 600),
  checkUpdate: () => setTimeout(() => updateChecked({ current: '0.1.0', latest: '0.2.0', newer: true, managed: true,
                                                      source: 'GitHub', error: '' }), 700),
  applyUpdate: () => '',
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
