// 中英文界面。源语言是中文：
// - HTML 里的静态文字加 data-i18n（整个元素的文字就是中文原文）；属性用 data-i18n-placeholder="中文"、
//   data-i18n-title="中文"、data-i18n-aria-label="中文"；
// - 脚本里的文字用 I18N.t('中文') 或 I18N.t('共 {n} 条', { n: 3 })。
// 英文在 i18n-en.js（window.I18N_EN）里按中文原文查，查不到就显示中文。语言由宿主给（I18N.setLang('en')）。

'use strict';

const I18N = (() => {
  let lang = 'zh';
  const EN = window.I18N_EN || {};
  const ATTRS = ['placeholder', 'title', 'aria-label'];

  function t(zh, values) {
    let text = lang === 'en' && Object.prototype.hasOwnProperty.call(EN, zh) ? EN[zh] : zh;
    if (values) text = text.replace(/\{(\w+)\}/g, (m, key) => (key in values ? String(values[key]) : m));
    return text;
  }

  function apply(root = document) {
    for (const node of root.querySelectorAll('[data-i18n]')) {
      if (node.dataset.zh === undefined) node.dataset.zh = node.textContent.trim();
      node.textContent = t(node.dataset.zh);
    }
    for (const attr of ATTRS) {
      for (const node of root.querySelectorAll(`[data-i18n-${attr}]`)) {
        node.setAttribute(attr, t(node.getAttribute(`data-i18n-${attr}`)));
      }
    }
  }

  function setLang(code) {
    lang = code === 'en' ? 'en' : 'zh';
    document.documentElement.lang = lang === 'en' ? 'en' : 'zh-CN';
    apply();
  }

  return {
    t,
    apply,
    setLang,
    get lang() { return lang; },
    appName: () => (lang === 'en' ? 'Super Aide' : '超级助手'),
  };
})();
