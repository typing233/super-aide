"""中英文界面：每一处 tr() / I18N.t() / data-i18n 都有英文；变量名两边一致；切换语言；英文汇报也认得出没办成。"""

from __future__ import annotations

import ast
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from super_aide import i18n
from super_aide.engines import browser_use, computer, experience
from super_aide.engines.base import reported_failure
from super_aide.setup import install
from super_aide.snapshot import content

SRC = Path(__file__).resolve().parents[1] / "src" / "super_aide"
WEB = SRC / "ui" / "web"
PLACEHOLDER = re.compile(r"\{(\w*)\}")


@pytest.fixture(autouse=True)
def chinese_afterwards():
    yield
    i18n.set_language("zh")


def tr_keys() -> dict[str, str]:
    """所有 Python 文件里 tr("…") 的字面量参数 → 出现在哪个文件。"""
    found: dict[str, str] = {}
    for path in SRC.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and node.args and (
                    getattr(node.func, "id", None) == "tr" or getattr(node.func, "attr", None) == "tr"):
                arg = node.args[0]
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    found.setdefault(arg.value, str(path.relative_to(SRC)))
    return found


def test_every_python_string_has_english():
    catalog = i18n.english()
    missing = {key: where for key, where in tr_keys().items() if key not in catalog}
    assert not missing, f"缺英文：{missing}"


def test_dynamic_keys_have_english():
    """不是字面量、运行时才拼出来的键：下载源的名字、npm 报错、推荐问题。"""
    catalog = i18n.english()
    keys = [label for label, _ in install.REGISTRIES + install.NODE_DISTS] + list(install.NPM_CODES.values())
    keys += [text for pair in content.PLACEHOLDERS.values() for text in pair]
    keys += list(computer.ACT_VERBS.values()) + ["正在操作界面", experience.STATUS]
    keys += [browser_use.FIX, browser_use.NOT_CONNECTED, browser_use.NO_EXTENSION]
    assert [k for k in keys if k not in catalog] == []


def test_catalogs_do_not_disagree():
    """同一句中文在两个对照表里都有时，英文必须一样（不然谁覆盖谁取决于读的先后）。"""
    import importlib
    import pkgutil

    from super_aide import locales

    seen: dict[str, tuple[str, str]] = {}
    clashes = []
    for info in pkgutil.iter_modules(locales.__path__):
        if info.name.startswith("en_"):
            for zh, en in importlib.import_module(f"{locales.__name__}.{info.name}").EN.items():
                if zh in seen and seen[zh][1] != en:
                    clashes.append((zh, seen[zh], (info.name, en)))
                seen.setdefault(zh, (info.name, en))
    assert clashes == []


def test_placeholders_match_on_both_sides():
    bad = {zh: en for zh, en in i18n.english().items()
           if set(PLACEHOLDER.findall(zh)) != set(PLACEHOLDER.findall(en))}
    assert not bad, bad


def test_switching_language():
    assert i18n.tr("设置") == "设置" and i18n.app_name() == "超级助手"
    i18n.set_language("en")
    assert i18n.tr("设置") == "Settings" and i18n.app_name() == "Super Aide"
    assert i18n.tr("自定义服务地址 {host}", host="relay.example.com") == "Custom endpoint relay.example.com"
    assert i18n.tr("没有翻译的文字") == "没有翻译的文字"  # 查不到就显示中文


def test_resolve_follows_setting_and_env(monkeypatch):
    assert i18n.resolve("zh") == "zh" and i18n.resolve("en") == "en"
    monkeypatch.setenv("SUPER_AIDE_LANG", "en")
    assert i18n.resolve("system") == "en"
    monkeypatch.setenv("SUPER_AIDE_LANG", "zh")
    assert i18n.resolve("system") == "zh"


def test_english_reports_are_understood():
    assert reported_failure("Not done: the installer needs admin rights.\nNothing was changed.")
    assert reported_failure("没完成：需要管理员权限")
    assert reported_failure("Done: installed pandas.") == ""


def test_foreign_text_depends_on_ui_language():
    english = "This is a long English paragraph about installing the package and running the script."
    chinese = "这是一段比较长的中文说明，讲的是怎么安装这个软件包，然后运行脚本，最后检查结果。"
    assert content.classify(english) == "foreign" and content.classify(chinese) == "text"
    i18n.set_language("en")
    assert content.classify(english) == "text" and content.classify(chinese) == "foreign"
    assert content.placeholders("foreign") == {"ask": "Translate and explain", "act": "Translate and replace with English"}


# ---------- 网页 ----------

WEB_KEYS = r"""
const fs = require('fs'), path = require('path');
const dir = process.argv[2];
global.window = {};
eval(fs.readFileSync(path.join(dir, 'i18n-en.js'), 'utf8'));
const catalog = window.I18N_EN, used = {};
const add = (key, file) => { key = key.trim(); if (key && !(key in used)) used[key] = file; };
for (const file of fs.readdirSync(dir)) {
  if (fs.statSync(path.join(dir, file)).isDirectory()) continue;
  const text = fs.readFileSync(path.join(dir, file), 'utf8');
  if (file.endsWith('.html')) {
    for (const m of text.matchAll(/<(\w+)([^>]*\sdata-i18n(?:=""|\s|>)[^>]*)>([^<]*)</g)) add(m[3], file);
    for (const m of text.matchAll(/data-i18n-(?:placeholder|title|aria-label)="([^"]*)"/g)) add(m[1], file);
  } else if (file.endsWith('.js') && !['i18n-en.js', 'i18n.js'].includes(file) && !file.includes('.min.')) {
    for (const m of text.matchAll(/I18N\.t\(\s*'((?:[^'\\]|\\.)*)'/g)) add(m[1].replace(/\\'/g, "'"), file);
    for (const m of text.matchAll(/I18N\.t\(\s*"((?:[^"\\]|\\.)*)"/g)) add(m[1].replace(/\\"/g, '"'), file);
  }
}
const missing = Object.fromEntries(Object.entries(used).filter(([k]) => !(k in catalog)));
console.log(JSON.stringify({ used: Object.keys(used).length, missing }));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="没有 Node.js")
def test_every_web_string_has_english(tmp_path):
    script = tmp_path / "keys.js"
    script.write_text(WEB_KEYS, encoding="utf-8")
    out = subprocess.run(["node", str(script), str(WEB)], capture_output=True, text=True, encoding="utf-8", check=True)
    result = json.loads(out.stdout)
    assert result["used"] > 0
    assert result["missing"] == {}, f"网页缺英文：{result['missing']}"
