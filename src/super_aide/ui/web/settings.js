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
  focus: '',             // 打开后要滚到的那一节（托盘里点了"正在自我改进"）
  opened: new Set(),     // 自我改进：展开了详情的那几条
  diffs: {},             // 自我改进：展开了改动的那几条 → 补丁原文
  confirming: '',        // 两步确认（撤销、不要了、合并）：第一次点过的那个按钮
  confirmTimer: null,
  armed: null,           // 那个按钮和它原来的字：超时或点了别的确认时变回去
  ticker: null,         // 正在改进的那一行的计时
  moving: null,          // 换数据位置：选好的去处、搬的进度、出错的原因
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
      // 换了语言：整页按新语言重画（浏览器操作没接通时那一行的修法、自我改进记录的标题和说明，也由宿主按新语言重新给）
      Object.assign(state.data, { lang: resp.data.lang, browser: resp.data.browser, evolve_state: resp.data.evolve_state });
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
  // 浏览器操作没接通时才出现这一行，写着怎么接通（只有用 Codex 官方账号时才要接通）；
  // 平时不显示：用的是哪一套、接通了没有，都没什么要你做的
  const browser = d.browser || { ready: true, problem: '' };
  $('#browser-row').hidden = browser.ready;
  $('#browser-note').textContent = browser.problem.replace(/^(浏览器操作还没接通：|Browser control isn't connected yet: )/, '');
  $('#setup-note').textContent = setupNote(d.tools || {});
  renderData();
  renderUpdate();
  renderEvolve();
  if (state.focus) focusSection(state.focus);
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
  const evolved = state.data.evolve_state && state.data.evolve_state.evolved;
  if (evolved && typeof u !== 'string') note.textContent += ` · ${I18N.t('已自我改进 {n} 次', { n: evolved })}`;
}

// ---------- 数据位置 ----------

// 平时写着数据在哪 → 选好文件夹后问你要不要搬（搬去哪、多少数据）→ 搬的进度 → 搬完重启。出错停在原地，写着原因
function renderData() {
  const note = $('#data-note');
  const actions = $('#data-actions');
  actions.innerHTML = '';
  const m = state.moving;
  if (m && m.percent !== undefined) {
    const text = m.finished ? I18N.t('搬好了，正在重启…')
      : I18N.t('正在搬到 {path}… {percent}%', { path: m.target, percent: m.percent });
    note.innerHTML = `<span class="shimmer">${escapeHtml(text)}</span>`;
    return;
  }
  if (m && m.target && !m.problem) {
    note.textContent = I18N.t('搬到 {path}？现在有 {size} 数据，搬完会重启超级助手', { path: m.target, size: m.size });
    actions.append(textBtn(I18N.t('取消'), () => { state.moving = null; renderData(); }));
    actions.append(textBtn(I18N.t('移动'), startMove, 'accent'));
    return;
  }
  note.textContent = m ? (m.problem || m.error) : state.data.data_dir;
  actions.append(textBtn(I18N.t('更改…'), chooseDataDir));
}

async function chooseDataDir() {
  const result = JSON.parse((await call('chooseDataDir')) || '{}');
  if (!result.target) return; // 没选
  state.moving = result;
  renderData();
}

async function startMove() {
  const { target } = state.moving;
  state.moving = { target, percent: 0 };
  renderData();
  const problem = await call('moveData', target);
  if (problem) {
    state.moving = { error: problem };
    renderData();
  }
}

function dataMoved(result) {
  if (result.error) state.moving = { error: result.error };
  else state.moving = { ...state.moving, percent: result.finished ? 100 : result.percent, finished: result.finished };
  renderData();
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

// ---------- 自我改进 ----------

// 状态 → (标记, 说明)。说明是中文原文，显示时经 I18N.t()
const EVOLVE_STATUS = {
  queued: ['wait', '排队中'],
  triage: ['busy', '正在看是不是助手的问题'],
  running: ['busy', '正在改进'],
  waiting: ['busy', '等网络恢复'],
  login: ['bad', '需要登录或配置'],
  ready: ['ready', '改好了，等你确认生效'],
  applying: ['busy', '正在生效'],
  done: ['ok', '已生效'],
  none: ['none', '无需改进'],
  covered: ['none', '前面的改进已经解决了'],
  held: ['bad', '待你处理'],
  failed: ['bad', '没改成'],
  discarded: ['none', '你没要'],
  rolled_back: ['bad', '新版本没能启动，已装回原来的版本'],
  undone: ['none', '已撤销'],
};
const EVOLVE_PHASE = {
  prepare: '正在准备', agent: '正在分析和修改', carry: '正在把本地改进移到新版本', check: '正在跑测试',
  review: '正在复核', build: '正在打包',
};
const TRIGGER = { failure: '没办成', stopped: '你停下了', thumbs_down: '你点了 👎', suggestion: '你的建议', carry: '版本更新' };
const VERDICT = { merge: ['ok', '建议合并'], problems: ['bad', '有问题'], duplicate: ['none', '重复'] };
const CHECKS = { passed: 'CI 通过', failed: 'CI 没过', pending: 'CI 进行中', none: '没有 CI' };

function fmtTime(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000);
  const pad = (n) => String(n).padStart(2, '0');
  return `${pad(d.getMonth() + 1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtElapsed(ts) {
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return h ? `${h}:${String(m).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}` : `${m}:${String(s % 60).padStart(2, '0')}`;
}

// 两步确认：第一次点变成"确认撤销？"，3 秒内再点一次才算
function confirmTwice(btn, key, label, action) {
  if (state.confirming === key) {
    clearTimeout(state.confirmTimer);
    state.confirming = '';
    state.armed = null;
    action();
    return;
  }
  disarm();
  state.confirming = key;
  state.armed = { btn, original: btn.textContent };
  btn.textContent = label;
  btn.classList.add('danger');
  state.confirmTimer = setTimeout(() => { disarm(); renderEvolve(); }, 3000);
}

// 上一个"确认…？"变回原样：没被重画的按钮（正在改进那一行的"不要了"）也要变回去
function disarm() {
  clearTimeout(state.confirmTimer);
  if (state.armed) {
    state.armed.btn.textContent = state.armed.original;
    state.armed.btn.classList.remove('danger');
  }
  state.armed = null;
  state.confirming = '';
}

// 正在做、排着的改进"不要了"（点两下确认）：正在跑的会话马上停下，改到一半的还原
function cancelButton(job) {
  const key = `cancel-${job.id}`;
  return textBtn(state.confirming === key ? I18N.t('确认不要？') : I18N.t('不要了'),
    (b) => confirmTwice(b, key, I18N.t('确认不要？'), () => call('evolveCancel', job.id)));
}

function textBtn(label, onClick, cls = '') {
  const b = el('button', `text-btn${cls ? ` ${cls}` : ''}`);
  b.textContent = label;
  b.addEventListener('click', (e) => { e.stopPropagation(); onClick(b); });
  return b;
}

function renderDiff(text) {
  const pre = el('pre', 'diff');
  for (const line of text.split('\n')) {
    const span = el('span', line.startsWith('+') && !line.startsWith('+++') ? 'add'
      : line.startsWith('-') && !line.startsWith('---') ? 'del' : line.startsWith('@@') ? 'hunk' : '');
    span.textContent = `${line}\n`;
    pre.append(span);
  }
  return pre;
}

function evolveItem(job) {
  const [mark, label] = EVOLVE_STATUS[job.status] || ['none', job.status];
  const item = el('div', `evo-item${state.opened.has(job.id) ? ' open' : ''}`);
  const line = el('div', 'evo-line');
  const dot = el('span', `evo-mark ${mark}`);
  const title = el('span', 'evo-title');
  title.textContent = job.title || job.trigger;
  title.title = job.title || job.trigger;
  const meta = el('span', 'evo-meta');
  meta.textContent = fmtTime(job.finished || job.created);
  const actions = el('span', 'evo-actions');
  const pr = job.pr || {};
  if (job.status === 'ready') {
    actions.append(textBtn(I18N.t('生效'), async () => {
      const problem = await call('evolveApply', job.id);
      if (problem) banner(problem);
      else banner(I18N.t('正在换上新版本，超级助手会先退出，几秒后自动重新打开'));
    }, 'accent'));
    actions.append(textBtn(state.confirming === `discard-${job.id}` ? I18N.t('确认不要？') : I18N.t('不要了'),
      (b) => confirmTwice(b, `discard-${job.id}`, I18N.t('确认不要？'), () => call('evolveDiscard', job.id))));
  }
  if (job.can_cancel) actions.append(job.cancelling
    ? Object.assign(el('span', 'evo-meta shimmer'), { textContent: I18N.t('正在停下…') }) : cancelButton(job));
  if (job.status === 'done' && job.can_undo) {
    actions.append(textBtn(state.confirming === `undo-${job.id}` ? I18N.t('确认撤销？') : I18N.t('撤销'),
      (b) => confirmTwice(b, `undo-${job.id}`, I18N.t('确认撤销？'), async () => {
        const problem = await call('evolveUndo', job.id);
        banner(problem || I18N.t('正在装回原来的版本，超级助手会先退出，几秒后自动重新打开'));
      })));
  }
  if (pr.number) actions.append(textBtn(`PR #${pr.number}`, () => call('openUrl', pr.url)));
  else if (pr.dup_of) actions.append(textBtn(I18N.t('同 #{n}', { n: pr.dup_of }), () => call('openUrl', pr.url)));
  line.append(dot, title, meta, actions);
  line.addEventListener('click', () => {
    if (state.opened.has(job.id)) state.opened.delete(job.id);
    else state.opened.add(job.id);
    renderEvolve();
  });
  item.append(line);
  if (job.privacy_pending) {
    const row = el('div', 'evo-privacy');
    const text = el('span');
    text.textContent = I18N.t('改动里可能有个人信息，没有自动提交：{what}', { what: (pr.privacy || []).join(I18N.t('、')) });
    row.append(text, textBtn(I18N.t('仍然提交'), () => call('privacyDecision', job.id, true)),
      textBtn(I18N.t('不提交'), () => call('privacyDecision', job.id, false)));
    item.append(row);
  }
  if (state.opened.has(job.id)) {
    const detail = el('div', 'evo-detail');
    const lines = [
      [I18N.t('状态'), I18N.t(label)],
      [I18N.t('起因'), job.trigger && job.trigger !== job.title
        ? I18N.t('{what}：{detail}', { what: I18N.t(TRIGGER[job.kind] || job.kind), detail: job.trigger })
        : I18N.t(TRIGGER[job.kind] || job.kind)],
      [I18N.t('你说的'), job.reason],
      [I18N.t('怎么改的'), job.summary],
      [I18N.t('原因'), job.error],
      [I18N.t('版本'), job.version],
      [I18N.t('用的'), job.engine ? `${job.engine} · ${job.model} · ${job.effort}` : ''],
    ];
    const kvs = el('div', 'evo-kvs');  // 两列：标签、内容，内容对齐
    for (const [k, v] of lines) {
      if (!v || (job.kind === 'carry' && k === I18N.t('你说的'))) continue;
      const key = el('span', 'k');
      key.textContent = k;
      const val = el('span', 'v');
      val.textContent = v;
      kvs.append(key, val);
    }
    detail.append(kvs);
    if (['ready', 'done', 'held', 'undone', 'rolled_back', 'discarded', 'running'].includes(job.status)) {
      const toggle = textBtn(state.diffs[job.id] !== undefined ? I18N.t('收起改动') : I18N.t('看看改了什么'), async () => {
        if (state.diffs[job.id] !== undefined) delete state.diffs[job.id];
        else state.diffs[job.id] = await call('evolveDiff', job.id) || '';
        renderEvolve();
      });
      detail.append(toggle);
      if (state.diffs[job.id] !== undefined) {
        detail.append(state.diffs[job.id] ? renderDiff(state.diffs[job.id]) : Object.assign(el('div', 'evo-empty'),
          { textContent: I18N.t('没有改动') }));
      }
    }
    item.append(detail);
  }
  return item;
}

function renderEvolve() {
  const ev = state.data.evolve_state;
  if (!ev) return;
  $('#evolve-switch').classList.toggle('on', Boolean((state.data.evolve || {}).enabled));
  $('#evolve-note').textContent = !ev.available ? I18N.t('需要 Claude Code 或 Codex（装好并配好模型）')
    : ev.editable ? I18N.t('从源码运行：改好的改动留在补丁里，不会换包生效')
      : I18N.t('任务失败、你停下并说明原因、点 👎 或提建议时，分析原因、改进自己；测试和复核都通过后，等你确认生效');
  // 正在改进的那一行
  const now = $('#evolve-now');
  const active = ev.active;
  clearInterval(state.ticker);
  if (active && active.status !== 'ready') {
    now.hidden = false;
    const [, label] = EVOLVE_STATUS[active.status] || ['', ''];
    $('#evolve-now-title').textContent = I18N.t('{what}：{detail}', {
      what: I18N.t(active.status === 'running' ? (EVOLVE_PHASE[active.phase] || '正在改进') : label),
      detail: active.title || active.trigger,
    });
    const notes = [active.step, active.error && active.status !== 'running' ? active.error : '',
      I18N.t('期间请不要关机，尽量保持联网'), ev.queued ? I18N.t('排队 {n} 个', { n: ev.queued }) : '']
      .filter(Boolean);
    $('#evolve-now-note').textContent = notes.join(' · ');
    const tick = () => { $('#evolve-now-time').textContent = active.started ? fmtElapsed(active.started) : ''; };
    tick();
    state.ticker = setInterval(tick, 1000);
    // 进度每走一步都会重画这一行：按钮没变就不换，免得正按下去的那一下落空
    const nowActions = $('#evolve-now-actions');
    const sig = `${active.id}|${active.cancelling ? 'stopping' : active.can_cancel ? 'cancel' : ''}`;
    if (nowActions.dataset.sig !== sig) {
      nowActions.dataset.sig = sig;
      nowActions.innerHTML = '';
      if (active.cancelling) nowActions.append(Object.assign(el('span', 'evo-meta shimmer'), { textContent: I18N.t('正在停下…') }));
      else if (active.can_cancel) nowActions.append(cancelButton(active));
    }
  } else {
    now.hidden = true;
    $('#evolve-now-actions').dataset.sig = '';
  }
  // 最近的几条
  const list = $('#evolve-list');
  list.innerHTML = '';
  for (const job of ev.items || []) {
    if (active && job.id === active.id && active.status !== 'ready') continue;
    list.append(evolveItem(job));
  }
  list.hidden = !list.children.length;
  // 社区共建
  const c = ev.contribute || {};
  $('#contribute-title').textContent = c.maintainer ? I18N.t('稳定后提交到主版本') : I18N.t('参与社区共建');
  $('#contribute-switch').classList.toggle('on', Boolean(c.enabled));
  $('#contribute-note').textContent = c.login
    ? I18N.t('已登录 @{login}：生效后稳定运行一天的改进，自动以你的账号提交 PR（只有代码改动，不带屏幕内容和日志）', { login: c.login })
    : I18N.t('用 GitHub 账号登录后，生效后稳定运行一天的改进会自动提交给主版本，让大家都用上（只有代码改动，不带屏幕内容和日志）');
  const loginRow = $('#login-row');
  loginRow.hidden = !(c.pending || c.error);
  if (c.error) {
    $('#login-text').textContent = I18N.t('没能登录 GitHub');
    $('#login-note').textContent = c.error;
  } else if (c.code) {
    $('#login-text').innerHTML = `${escapeHtml(I18N.t('在浏览器里输入'))} <code class="device-code">${escapeHtml(c.code)}</code>`;
    $('#login-note').innerHTML = `<span class="shimmer">${escapeHtml(I18N.t('等你在浏览器里确认…'))}</span>`;
  } else if (c.pending) {
    $('#login-text').innerHTML = `<span class="shimmer">${escapeHtml(I18N.t('正在连接 GitHub…'))}</span>`;
    $('#login-note').textContent = '';
  }
  $('#login-copy').hidden = $('#login-open').hidden = !c.code;
  $('#login-cancel').textContent = c.error ? I18N.t('关闭') : I18N.t('取消');
  // 社区改进（只在维护者的电脑上）
  const items = ev.community || [];
  const show = Boolean(c.maintainer);
  $('#community-head').hidden = !show;
  $('#community-tile').hidden = !show;
  if (show) {
    $('#community-title').textContent = items.length
      ? I18N.t('社区改进 · {n} 个待审', { n: items.length }) : I18N.t('社区改进');
    $('#community-check').textContent = ev.community_checking ? I18N.t('正在审…') : I18N.t('检查');
    $('#community-check').disabled = Boolean(ev.community_checking);
    const box = $('#community-list');
    box.innerHTML = '';
    if (!items.length) {
      const empty = el('div', 'evo-empty pad');
      empty.textContent = ev.community_checked && !ev.community_checking
        ? I18N.t('没有待审的社区 PR · {time} 检查过', { time: fmtTime(ev.community_checked) }) : I18N.t('没有待审的社区 PR');
      box.append(empty);
    }
    if (ev.community_error && !ev.community_checking) { // 原来检查失败（比如连不上 GitHub）只写日志，看起来像什么都没发生
      const err = el('div', 'evo-empty pad error');
      err.textContent = I18N.t('没能检查：{error}', { error: ev.community_error });
      box.append(err);
    }
    for (const pr of items) box.append(communityItem(pr));
  }
}

function communityItem(pr) {
  const [mark, label] = VERDICT[pr.verdict] || ['wait', '还没审'];
  const item = el('div', `evo-item${state.opened.has(`pr-${pr.number}`) ? ' open' : ''}`);
  const line = el('div', 'evo-line');
  const title = el('span', 'evo-title');
  title.textContent = `#${pr.number} ${pr.title}`;
  const meta = el('span', 'evo-meta');
  meta.textContent = [pr.verdict === 'duplicate' && pr.duplicate_of ? I18N.t('同 #{n}', { n: pr.duplicate_of })
    : I18N.t(label), I18N.t(CHECKS[pr.checks] || '')].filter(Boolean).join(' · ');
  const actions = el('span', 'evo-actions');
  if (pr.verdict === 'merge') {
    const key = `merge-${pr.number}`;
    actions.append(textBtn(state.confirming === key ? I18N.t('确认合并？') : I18N.t('合并'),
      (b) => confirmTwice(b, key, I18N.t('确认合并？'), async () => {
        const problem = await call('communityMerge', pr.number);
        if (problem) banner(problem);
      }), 'accent'));
  }
  actions.append(textBtn(I18N.t('查看'), () => call('openUrl', pr.url)));
  line.append(el('span', `evo-mark ${mark}`), title, meta, actions);
  line.addEventListener('click', () => {
    const key = `pr-${pr.number}`;
    if (state.opened.has(key)) state.opened.delete(key);
    else state.opened.add(key);
    renderEvolve();
  });
  item.append(line);
  if (state.opened.has(`pr-${pr.number}`)) {
    const detail = el('div', 'evo-detail');
    const kvs = el('div', 'evo-kvs');
    for (const [k, v] of [[I18N.t('提交者'), pr.author], [I18N.t('审的结论'), pr.why],
      [I18N.t('风险'), (pr.risks || []).join(I18N.t('；'))]]) {
      if (!v) continue;
      kvs.insertAdjacentHTML('beforeend', `<span class="k">${escapeHtml(k)}</span><span class="v">${escapeHtml(v)}</span>`);
    }
    detail.append(kvs);
    item.append(detail);
  }
  return item;
}

function evolveChanged(snapshot) {
  if (!state.data) return;
  state.data.evolve_state = snapshot;
  renderEvolve();
  renderUpdate();
}

function focusSection(name) {
  state.focus = name;
  if (!state.data) return;
  const target = name === 'evolve' ? $('#evolve-section') : null;
  if (target) {
    requestAnimationFrame(() => {
      const scroll = $('#scroll');
      const top = target.getBoundingClientRect().top - scroll.getBoundingClientRect().top + scroll.scrollTop - 8;
      scroll.scrollTo({ top, behavior: 'smooth' });
      state.focus = '';
    });
  }
}

async function sendSuggestion() {
  const input = $('#suggest-input');
  const text = input.value.trim();
  if (!text) return;
  const btn = $('#suggest-send');
  btn.disabled = true;
  const resp = JSON.parse(await call('suggest', text) || '{}');
  btn.disabled = false;
  if (resp.error) {
    $('#suggest-note').textContent = resp.error;
    return;
  }
  input.value = '';
  $('#suggest-note').textContent = resp.position > 1
    ? I18N.t('收到了，排在第 {n} 个', { n: resp.position }) : I18N.t('收到了，马上开始');
  setTimeout(() => { $('#suggest-note').textContent = ''; }, 6000);
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
  } else if (field && field.tagName === 'TEXTAREA' && field.value) {
    field.blur(); // 写了一半的建议：Esc 不清空也不关窗口
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

// 开关写在配置的 [evolve] 里（state.data.evolve），和别的设置一样改了就存；进度和记录在 state.data.evolve_state
$('#evolve-switch').addEventListener('click', () => {
  const cfg = state.data.evolve;
  cfg.enabled = !cfg.enabled;
  $('#evolve-switch').classList.toggle('on', cfg.enabled);
  save();
});

$('#contribute-switch').addEventListener('click', () => {
  const c = state.data.evolve_state.contribute || {};
  const on = !c.enabled;
  if (on && !c.login) call('githubLogin'); // 先登录 GitHub：页内显示设备码
  c.enabled = on;
  state.data.evolve.contribute = on ? 'on' : 'off';
  $('#contribute-switch').classList.toggle('on', on);
  save();
});

$('#suggest-send').addEventListener('click', sendSuggestion);
$('#suggest-input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && e.ctrlKey) {
    e.preventDefault();
    sendSuggestion();
  }
});
$('#login-copy').addEventListener('click', () => call('copy', (state.data.evolve_state.contribute || {}).code || ''));
$('#login-open').addEventListener('click', () => call('openUrl', (state.data.evolve_state.contribute || {}).uri
  || 'https://github.com/login/device'));
$('#login-cancel').addEventListener('click', () => call('githubCancel'));
$('#community-check').addEventListener('click', () => call('communityCheck'));

// ---------- 宿主调用的接口 ----------

window.settings = { reload, modelsRefreshed, stopRecording, updateChecked, dataMoved, evolveChanged, focusSection };

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
  version: '0.2.0+aide.2',
  data_dir: 'C:\\Users\\you\\.super_aide',
  autostart: false,
  evolve: { enabled: true, contribute: 'auto' },
  evolve_state: {
    enabled: true, available: true, editable: false, tool: 'claude · claude-opus-5-5 · max', queued: 1, evolved: 2,
    active: { id: 'a', kind: 'failure', status: 'running', phase: 'check', step: '正在跑测试', title: '',
              trigger: '帮我把这个 Notebook 跑通', started: Date.now() / 1000 - 754 },
    items: [
      { id: 'r', kind: 'stopped', status: 'ready', title: 'Esc 停下后把焦点还给原来的窗口', trigger: '帮我整理桌面',
        summary: '停下后焦点留在了看不见的胶囊上，你接着打的字丢了。现在停下时把焦点还给原来的窗口。',
        finished: Date.now() / 1000 - 300, version: '0.2.0+aide.3', engine: 'claude', model: 'claude-opus-5-5', effort: 'max', pr: {} },
      { id: 'd', kind: 'suggestion', status: 'done', title: '读网址时先找地址栏', trigger: '读网址时先找地址栏',
        reason: '侧边栏开着的时候经常读错网址', summary: '读网址时按地址栏的类名直接找，侧边栏里的网页不再混进来。',
        finished: Date.now() / 1000 - 86400 * 2, version: '0.2.0+aide.2', can_undo: true,
        pr: { number: 12, url: 'https://github.com/typing233/super-aide/pull/12' } },
      { id: 'n', kind: 'thumbs_down', status: 'none', title: '服务暂时不可用，不是助手的问题', trigger: '这段话什么意思',
        finished: Date.now() / 1000 - 86400 * 3, pr: {} },
    ],
    contribute: { setting: 'auto', enabled: true, login: 'typing233', maintainer: true, pending: false, code: '', uri: '', error: '' },
    community: [
      { number: 14, title: '读网址时先找地址栏', url: 'https://github.com/typing233/super-aide/pull/14', author: 'someone',
        checks: 'passed', verdict: 'merge', why: '改动小，和问题对得上，测试覆盖了侧边栏的情况。', duplicate_of: 0, risks: [] },
      { number: 15, title: '地址栏读取改用类名', url: 'https://github.com/typing233/super-aide/pull/15', author: 'other',
        checks: 'pending', verdict: 'duplicate', why: '和 #14 解决的是同一件事，#14 更完整。', duplicate_of: 14, risks: [] },
    ],
    community_checking: false,
  },
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
  chooseDataDir: () => JSON.stringify({ target: 'D:\\SuperAide', size: '338 MB', problem: '' }),
  moveData: () => {
    [25, 60, 100].forEach((percent, i) => setTimeout(() => dataMoved(percent < 100 ? { percent } : { finished: true }),
      500 * (i + 1)));
    return '';
  },
  suggest: () => JSON.stringify({ id: 'x', position: 2 }),
  evolveDiff: () => '--- a/src/super_aide/shell/controller.py\n+++ b/src/super_aide/shell/controller.py\n@@ -340,6 +340,7 @@\n     def _on_esc(self) -> None:\n         self.signals.stop()\n+        self._return_focus()\n         if self.hub.is_busy(self.conv_key):\n',
  evolveApply: () => '',
  evolveUndo: () => '',
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
