"""设置窗口自检：用假的宿主打开设置窗口，经 JS 模拟操作，核对配置变化并截图。

不碰真实配置和注册表（开机自启被替换掉）。快捷键冲突检查用真的 RegisterHotKey 试注册：
如果 Super Aide 正在运行，Alt+Q 应当被报告为"已被其它程序占用"。

    uv run --no-sync python -X utf8 spikes/p1_settings_check.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import QApplication

from super_aide import autostart, config, hotkeys
from super_aide.shell import settings as settings_ui

OUT = Path(__file__).parent / "out" / "settings"
OUT.mkdir(parents=True, exist_ok=True)

CLAUDE_IDS = ["claude-opus-5-5", "claude-sonnet-5-5", "claude-fable-5-1", "claude-haiku-4-5-20251001",
              "claude-opus-4-1", "claude-sonnet-4-5", "claude-3-7-sonnet", "claude-3-5-haiku"]
CODEX_IDS = ["gpt-6-astra", "gpt-6-astra-mini", "gpt-5.5-codex", "o4-mini"]

autostart_state = {"on": False}
autostart.is_enabled = lambda: autostart_state["on"]
autostart.set_enabled = lambda on: autostart_state.update(on=on)


class FakeHost:
    def __init__(self) -> None:
        self.cfg = config.Config()
        self.cfg.claude.merge_discovered(CLAUDE_IDS)
        self.cfg.codex.merge_discovered(CODEX_IDS)
        self.hotkeys = hotkeys.HotkeyManager(lambda *_: None)
        self.calls: list[str] = []
        self.window: settings_ui.SettingsWindow | None = None

    def apply_settings(self, new: config.Config) -> list[str]:
        self.calls.append("apply")
        self.cfg.update_from(new)
        return []

    def check_hotkey(self, spec: str) -> str:
        try:
            return "" if self.hotkeys.available(spec) else "已被其它程序占用"
        except ValueError as e:
            return str(e)

    def pause_hotkeys(self) -> None:
        self.calls.append("pause")

    def resume_hotkeys(self) -> None:
        self.calls.append("resume")

    def refresh_models(self) -> None:
        self.cfg.claude.merge_discovered(["claude-new-model"])
        QTimer.singleShot(300, lambda: self.window.models_refreshed({"added": 1, "errors": []}))

    def resolved_theme(self) -> str:
        return self.cfg.theme if self.cfg.theme in ("light", "dark") else "dark"

    def settings_closed(self) -> None:
        self.calls.append("closed")


def key_js(code: str, key: str, **mods: bool) -> str:
    opts = {"code": code, "key": key, "bubbles": True, "cancelable": True, **mods}
    return f"document.dispatchEvent(new KeyboardEvent('keydown', {json.dumps(opts)}))"


def main() -> int:
    app = QApplication(sys.argv)
    host = FakeHost()
    win = settings_ui.SettingsWindow(host)
    host.window = win
    results: list[tuple[str, bool, str]] = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))

    def js(code: str) -> None:
        win.view.page().runJavaScript(code)

    def probe(code: str, name: str, expect) -> None:
        win.view.page().runJavaScript(code, 0, lambda value: check(name, expect(value), repr(value)))

    def shot(name: str) -> None:
        size = win.size()
        dpr = win.devicePixelRatioF()
        canvas = QPixmap(round(size.width() * dpr), round(size.height() * dpr))
        canvas.setDevicePixelRatio(dpr)
        g = QLinearGradient(0, 0, size.width(), size.height())
        g.setColorAt(0, QColor("#3b4a6b"))
        g.setColorAt(1, QColor("#6b4a5a"))
        p = QPainter(canvas)
        p.fillRect(canvas.rect(), g)
        p.drawPixmap(QPoint(0, 0), win.grab())
        p.end()
        canvas.save(str(OUT / f"{name}.png"))

    steps = [
        (900, lambda: (check("首次打开后显示", win.isVisible()), shot("1-dark"))),
        (0, lambda: js("document.querySelector('#theme [data-value=light]').click()")),
        (500, lambda: (check("主题改成浅色", host.cfg.theme == "light", host.cfg.theme), shot("2-light"))),
        # 录快捷键：Ctrl+Alt+A
        (0, lambda: js("document.querySelector('.keycap[data-hotkey=ask]').click()")),
        (200, lambda: js(key_js("ControlLeft", "Control", ctrlKey=True))),
        (200, lambda: shot("3-recording")),
        (0, lambda: js(key_js("KeyA", "a", ctrlKey=True, altKey=True))),
        (500, lambda: check("问答快捷键录成 Ctrl+Alt+A", host.cfg.hotkey_ask == "Ctrl+Alt+A", host.cfg.hotkey_ask)),
        (0, lambda: check("录制时暂停、结束后恢复快捷键", "pause" in host.calls and "resume" in host.calls,
                          ",".join(host.calls))),
        # 和另一个重复
        (0, lambda: js("document.querySelector('.keycap[data-hotkey=act]').click()")),
        (200, lambda: js(key_js("KeyA", "a", ctrlKey=True, altKey=True))),
        (500, lambda: check("重复的快捷键被拒绝", host.cfg.hotkey_act == "Alt+W", host.cfg.hotkey_act)),
        (0, lambda: probe("document.querySelector('#hotkey-note').textContent", "重复时提示",
                          lambda v: "重复" in (v or ""))),
        (0, lambda: shot("4-hotkey-error")),
        # 被占用（Super Aide 在运行时 Alt+Q 被它占着）
        (0, lambda: js("document.querySelector('.keycap[data-hotkey=act]').click()")),
        (200, lambda: js(key_js("KeyQ", "q", altKey=True))),
        (600, lambda: probe("document.querySelector('#hotkey-note').textContent", "被占用时提示（需 Super Aide 在运行）",
                            lambda v: "占用" in (v or ""))),
        # 模型：展开、打开第二个、改思考强度上限
        (0, lambda: js("document.querySelector('.engine .more').click()")),
        (300, lambda: shot("5-models-expanded")),
        (0, lambda: js("document.querySelectorAll('.engine')[0].querySelectorAll('.model')[1].click()")),
        (400, lambda: check("打开了第二个 Claude 模型", host.cfg.claude.models[1].enabled,
                            str([(m.id, m.enabled) for m in host.cfg.claude.models[:3]]))),
        (0, lambda: js("const a = document.querySelector('.engine .add-model'); a.value = 'claude-custom-x';"
                       "a.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")),
        (400, lambda: check("手动添加模型（默认打开）",
                            any(m.id == "claude-custom-x" and m.enabled for m in host.cfg.claude.models))),
        (0, lambda: js("document.querySelector('#scroll').scrollTop = 0")),
        (0, lambda: js("document.querySelector('.model.on .effort').click()")),
        (300, lambda: shot("6-effort-menu")),
        (0, lambda: js("[...document.querySelectorAll('#effort-menu button')].find(b => b.textContent.trim() === 'high').click()")),
        (400, lambda: check("思考强度上限改成 high", host.cfg.claude.models[0].max_effort == "high",
                            host.cfg.claude.models[0].max_effort)),
        # 关掉 Codex 引擎
        (0, lambda: js("document.querySelectorAll('.engine')[1].querySelector('.engine-head .switch').click()")),
        (400, lambda: check("关掉 Codex", not host.cfg.codex.enabled)),
        (0, lambda: js("document.querySelectorAll('.engine')[1].querySelector('.engine-head .switch').click()")),
        (400, lambda: check("再打开 Codex", host.cfg.codex.enabled)),
        # 隐私
        (0, lambda: js("const i = document.querySelector('#blocked-input'); i.value = 'WeChat';"
                       "i.dispatchEvent(new KeyboardEvent('keydown', {key: 'Enter', bubbles: true}))")),
        (400, lambda: check("加入隐私名单 WeChat.exe", "WeChat.exe" in host.cfg.blocked_apps, str(host.cfg.blocked_apps))),
        (0, lambda: js("document.querySelector('#clipboard [data-value=\"60\"]').click()")),
        (400, lambda: check("剪贴板改成 1 分钟", host.cfg.clipboard_max_age_s == 60, str(host.cfg.clipboard_max_age_s))),
        (0, lambda: js("document.querySelector('#scroll').scrollTop = 10000")),
        (300, lambda: shot("7-privacy")),
        # 开机自启（已替换成内存里的开关）
        (0, lambda: js("document.querySelector('#autostart').click()")),
        (400, lambda: check("开机自启打开", autostart_state["on"])),
        # 刷新列表：新模型并进来、默认关闭，且不丢掉刚才的改动
        (0, lambda: js("document.querySelector('#refresh').click()")),
        (900, lambda: probe("[...document.querySelectorAll('.model-id')].map(n => n.textContent).join(',')",
                            "刷新后显示新模型", lambda v: "claude-new-model" in (v or ""))),
        (0, lambda: js("document.querySelector('#theme [data-value=dark]').click()")),
        (400, lambda: check("刷新后保存仍保留新模型和之前的改动",
                            any(m.id == "claude-new-model" and not m.enabled for m in host.cfg.claude.models)
                            and host.cfg.claude.models[0].max_effort == "high")),
        # 筛选
        (0, lambda: js("const f = document.querySelector('#model-filter'); f.value = 'opus';"
                       "f.dispatchEvent(new Event('input'))")),
        (300, lambda: (js("document.querySelector('#scroll').scrollTop = 0"), None)),
        (200, lambda: shot("8-filter-dark")),
        (0, lambda: probe("document.querySelectorAll('.model').length", "筛选 opus 只剩匹配的", lambda v: v == 2)),
        # Esc：先清空筛选，再关窗口
        (0, lambda: js("document.querySelector('#model-filter').focus()")),
        (100, lambda: js(key_js("Escape", "Escape"))),
        (300, lambda: probe("document.querySelector('#model-filter').value", "Esc 先清空筛选", lambda v: v == "")),
        (0, lambda: js("document.activeElement.blur()")),
        (100, lambda: js(key_js("Escape", "Escape"))),
        (400, lambda: check("再按 Esc 关窗口", not win.isVisible() and "closed" in host.calls)),
        (0, lambda: win.open()),
        (500, lambda: check("再次打开", win.isVisible())),
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
        failed = [r for r in results if not r[1]]
        for name, ok, detail in results:
            print(("PASS " if ok else "FAIL ") + name + (f"  [{detail}]" if detail and not ok else ""))
        print(f"\n{len(results) - len(failed)}/{len(results)} 通过，截图在 {OUT}")
        app.exit(1 if failed else 0)

    def wait_visible(tries: int = 0) -> None:
        if win.isVisible() or tries > 100:
            run()
        else:
            QTimer.singleShot(100, lambda: wait_visible(tries + 1))

    win.open()  # 第一次：等网页画好后自己显示
    wait_visible()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
