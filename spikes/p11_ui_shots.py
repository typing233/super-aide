"""截图检查：自我改进相关的界面（设置 → 高级、Esc 停下后问原因、👎 后的原因），深浅色、中英文。

用网页的预览模式（没有宿主时用模拟数据），在屏幕外渲染后截图，存到 spikes/out/evolve-ui/。

    uv run python spikes/p11_ui_shots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "super_aide" / "ui" / "web"
OUT = ROOT / "spikes" / "out" / "evolve-ui"

SETTINGS_JS = """
document.documentElement.dataset.theme = '{theme}';
state.opened.add('r');
state.diffs['r'] = preview.evolveDiff();
renderEvolve();
settings.focusSection('evolve');
"""
STOP_JS = """
document.querySelector('#demo').hidden = true;
document.documentElement.dataset.theme = '{theme}';
setMode('act'); live.question = '帮我把桌面整理一下';
showToast(I18N.t('已停止 · 是助手哪里没做好吗？'), true, true);
clearTimeout(state.toastTimer);
"""
BOTTOM_JS = """
document.documentElement.dataset.theme = '{theme}';
const box = document.querySelector('#scroll'); box.scrollTop = box.scrollHeight;
"""
BAD_JS = """
document.querySelector('#demo').hidden = true;
document.documentElement.dataset.theme = '{theme}';
setMode('ask'); startCard(I18N.t('这个报错是什么原因？'));
live.draft = MOCK_ANSWER; finish({ok: true});
document.querySelector('#rate-bad').click();
document.activeElement.blur();
"""


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    jobs = []
    for lang in ("zh", "en"):
        for theme in ("dark", "light"):
            jobs.append((f"settings-{lang}-{theme}", "settings.html", lang, SETTINGS_JS.replace('{theme}', theme), (760, 1180)))
            jobs.append((f"stop-{lang}-{theme}", "index.html", lang, STOP_JS.replace('{theme}', theme), (520, 260)))
            jobs.append((f"settings-bottom-{lang}-{theme}", "settings.html", lang, BOTTOM_JS.replace('{theme}', theme),
                         (760, 1180)))
            jobs.append((f"bad-{lang}-{theme}", "index.html", lang, BAD_JS.replace('{theme}', theme), (720, 520)))
    view = QWebEngineView()
    view.move(QPoint(-30000, -30000))
    view.show()

    def run(i: int) -> None:
        if i >= len(jobs):
            app.quit()
            return
        name, page, lang, script, size = jobs[i]
        view.resize(*size)

        def loaded(ok: bool) -> None:
            view.loadFinished.disconnect(loaded)
            QTimer.singleShot(700, lambda: view.page().runJavaScript(script, 0, lambda _r: QTimer.singleShot(
                900, lambda: (view.grab().save(str(OUT / f"{name}.png")), print(name), run(i + 1)))))

        view.loadFinished.connect(loaded)
        view.load(QUrl(QUrl.fromLocalFile(str(WEB / page)).toString() + f"?lang={lang}"))

    QTimer.singleShot(0, lambda: run(0))
    app.exec()
    print(f"截图在 {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
