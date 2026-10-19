"""安卓端的英文对照表：android/core/src/main/resources/i18n/en.json。

和桌面版一样，中文原文就是键。这里收集安卓代码里所有 tr("…") 的中文，
英文先查 android/i18n/en_android.json（安卓专用），再查桌面版的对照表（i18n-en.js 和 locales/）。
用法：python scripts/android/gen_strings.py        生成
      python scripts/android/gen_strings.py --check 只检查（有没翻译的键、或生成结果过期就失败，CI 用）
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android"
OUT = ANDROID / "core" / "src" / "main" / "resources" / "i18n" / "en.json"
OWN = ANDROID / "i18n" / "en_android.json"
DESKTOP_JS = ROOT / "src" / "super_aide" / "ui" / "web" / "i18n-en.js"

# tr("…")：前面不能是字母（排除 str("…")）；只认字面量
TR = re.compile(r'(?<![A-Za-z_.])tr\("((?:[^"\\]|\\.)*)"')
# 动态的进度动词（Tools.verbs 的值）：to "正在…"
VERBS = re.compile(r'to "(正在[^"]*)"')
# 路由的任务类型名（Router.LABELS 的值，显示时再 tr）
LABELS = re.compile(r'\) to "([^"]*[一-鿿][^"]*)"')


def android_keys() -> set[str]:
    keys: set[str] = set()
    for path in ANDROID.rglob("*.kt"):
        if "build" in path.parts or "test" in path.parts:
            continue
        text = path.read_text(encoding="utf-8")
        keys.update(m.replace('\\"', '"') for m in TR.findall(text))
        if path.name == "Tools.kt":
            keys.update(VERBS.findall(text))
        if path.name == "Router.kt":
            keys.update(LABELS.findall(text))
    return keys


def desktop_table() -> dict[str, str]:
    table: dict[str, str] = {}
    # 网页界面的表：'中文': 'English',（单引号 JS 字面量）
    if DESKTOP_JS.exists():
        for key, value in re.findall(r"'((?:[^'\\]|\\.)*)'\s*:\s*\n?\s*'((?:[^'\\]|\\.)*)'", DESKTOP_JS.read_text(encoding="utf-8")):
            table[key.replace("\\'", "'")] = value.replace("\\'", "'")
    # Python 一侧的表
    sys.path.insert(0, str(ROOT / "src"))
    try:
        from super_aide.locales import en_core, en_engines, en_evolve  # type: ignore

        for mod in (en_core, en_engines, en_evolve):
            table.update(mod.EN)
    except Exception:  # noqa: BLE001  桌面环境没装也能生成，只是少一些可复用的翻译
        pass
    return table


def build() -> tuple[dict[str, str], list[str]]:
    own = json.loads(OWN.read_text(encoding="utf-8"))
    desktop = desktop_table()
    out: dict[str, str] = {}
    missing = []
    for key in sorted(android_keys()):
        value = own.get(key) or desktop.get(key)
        if value:
            out[key] = value
        else:
            missing.append(key)
    return out, missing


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    table, missing = build()
    text = json.dumps(table, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
    if missing:
        print("这些键还没有英文（加到 android/i18n/en_android.json）：", file=sys.stderr)
        for k in missing:
            print("  " + k, file=sys.stderr)
    if args.check:
        stale = not OUT.exists() or OUT.read_text(encoding="utf-8") != text
        if stale:
            print("en.json 过期了：运行 python scripts/android/gen_strings.py", file=sys.stderr)
        return 1 if missing or stale else 0
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(text, encoding="utf-8")
    print(f"写好了 {len(table)} 条：{OUT.relative_to(ROOT)}")
    return 1 if missing else 0


if __name__ == "__main__":
    sys.exit(main())
