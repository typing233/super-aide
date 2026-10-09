"""设置窗口联调：真实的 SuperAide（路由、引擎中枢、托盘、快捷键），经设置窗口改动后核对各部分。

不写真实配置文件、不写注册表、不预热引擎（都被替换掉）；"刷新列表"会真的去两边取模型清单（不花 token）。
需要先退出正在运行的 Super Aide（要用它的快捷键）。

    uv run --no-sync python -X utf8 spikes/p1_settings_live.py
"""

from __future__ import annotations

import json
import sys
import time

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication

from super_aide import app as app_mod
from super_aide import autostart, config

config.save = lambda cfg, path=None: None
autostart.is_enabled = lambda: False
autostart.set_enabled = lambda on: None


def key_js(code: str, key: str, **mods: bool) -> str:
    opts = {"code": code, "key": key, "bubbles": True, "cancelable": True, **mods}
    return f"document.dispatchEvent(new KeyboardEvent('keydown', {json.dumps(opts)}))"


def main() -> int:
    qt = QApplication(sys.argv)
    qt.setQuitOnLastWindowClosed(False)
    cfg = config.load()
    aide = app_mod.SuperAide(qt, cfg)
    warmed: list[float] = []
    aide.hub.warm_up = lambda: warmed.append(time.time())
    failed = aide._register_hotkeys(cfg)
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    def js(code: str) -> None:
        aide.settings.view.page().runJavaScript(code)

    def probe(code: str, name: str, expect) -> None:
        aide.settings.view.page().runJavaScript(code, 0, lambda v: check(name, expect(v), repr(v)))

    claude_ids = [m.id for m in cfg.claude.models]
    target = next((m.id for m in cfg.claude.models if not m.enabled), "")
    original_ask = cfg.hotkey_ask

    steps = [
        (0, lambda: check("启动时快捷键注册成功", not failed, str(failed))),
        (0, aide.open_settings),
        (1500, lambda: check("设置窗口显示", aide.settings.isVisible())),
        # 打开一个原来关着的 Claude 模型 → 路由在引擎线程里重建
        (0, lambda: js("document.querySelector('.engine .more').click()")),
        (300, lambda: js(f"[...document.querySelectorAll('.engine')[0].querySelectorAll('.model')]"
                         f".find(r => r.textContent.includes({json.dumps(target)})).click()")),
        (800, lambda: check(f"路由里多了 {target}", target in [m.id for m in aide.router.models["claude"]],
                            str([m.id for m in aide.router.models["claude"]]))),
        # 换问答快捷键 → 真的注册上，托盘菜单跟着变
        (0, lambda: js("document.querySelector('.keycap[data-hotkey=ask]').click()")),
        (300, lambda: check("录制时放开了快捷键", not aide.hotkeys.active)),
        (0, lambda: js(key_js("F22", "F22", ctrlKey=True, altKey=True, shiftKey=True))),
        (600, lambda: check("新快捷键已注册", cfg.hotkey_ask == "Ctrl+Alt+Shift+F22" and aide.hotkeys.active
                            and aide.hotkeys.available("Ctrl+Alt+Shift+F22"), cfg.hotkey_ask)),
        (0, lambda: check("托盘菜单更新", "Ctrl+Alt+Shift+F22" in aide.tray.ask_action.text(),
                          aide.tray.ask_action.text())),
        # 主题
        (0, lambda: js("document.querySelector('#theme [data-value=light]').click()")),
        (500, lambda: check("主题浅色", aide.ctrl.theme() == "light", aide.ctrl.theme())),
        # 隐私名单直接作用到采集
        (0, lambda: js("const i = document.querySelector('#blocked-input'); i.value = 'Notepad';"
                       "i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")),
        (500, lambda: check("采集跟着隐私名单", "notepad.exe" in aide.collector.blocked, str(aide.collector.blocked))),
        # 刷新列表：真的去取
        (0, lambda: js("document.querySelector('#refresh').click()")),
        (15000, lambda: probe("document.querySelector('#refresh').textContent", "刷新列表有结果",
                              lambda v: v in ("没有新模型", "刷新列表") or (v or "").startswith("新增"))),
        (0, lambda: probe("document.querySelector('#banner').hidden", "刷新没有报错", lambda v: v is True)),
        # 关窗口：恢复快捷键，并因为模型改过而预热一次
        (0, lambda: js(key_js("Escape", "Escape"))),
        (600, lambda: check("关闭后预热一次", len(warmed) == 1, str(warmed))),
        (0, lambda: check("关闭后快捷键仍在", aide.hotkeys.active)),
        (0, lambda: check("模型清单没丢", all(i in [m.id for m in cfg.claude.models] for i in claude_ids))),
    ]

    def run(i: int = 0) -> None:
        if i >= len(steps):
            finish()
            return
        delay, fn = steps[i]

        def go() -> None:
            try:
                fn()
            except Exception as e:  # noqa: BLE001
                check(f"第 {i} 步出错", False, repr(e))
            run(i + 1)

        QTimer.singleShot(delay, go)

    def finish() -> None:
        bad = [r for r in results if not r[1]]
        for name, ok, detail in results:
            print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        print(f"\n{len(results) - len(bad)}/{len(results)} 通过（问答快捷键原为 {original_ask}，未写回配置文件）")
        aide.shutdown()
        qt.exit(1 if bad else 0)

    run()
    return qt.exec()


if __name__ == "__main__":
    sys.exit(main())
