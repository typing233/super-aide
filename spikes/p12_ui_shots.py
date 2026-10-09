"""截图检查：操作胶囊收起 / 展开、长回答滚到顶 / 底时的渐隐、设置里的数据位置，深浅色、中英文。

用网页的预览模式（没有宿主时用模拟数据），在屏幕外渲染后截图，存到 spikes/out/p12-ui/。

    uv run python spikes/p12_ui_shots.py
"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "src" / "super_aide" / "ui" / "web"
OUT = ROOT / "spikes" / "out" / "p12-ui"

PILL_JS = """
document.querySelector('#demo').hidden = true;
document.documentElement.dataset.theme = '{theme}';
setMode('act');
startPill(I18N.t('帮我把这个表格导出成 PDF，存到桌面'));
for (const s of ['正在打开 Excel', '正在点击"文件"', '正在点击"导出"', '正在选择"PDF"']) onEvent({{ type: 'status', text: I18N.t(s) }});
onEvent({{ type: 'status', text: I18N.t('正在思考…'), transient: true }});
clearInterval(state.ticker); document.querySelector('#pill-time').textContent = '0:42';
"""
OPEN_JS = "document.querySelector('#pill-note').hidden = true; setPillOpen(true);"
HALF_JS = "document.querySelector('#pill-note').hidden = true; setPillOpen(true); setTimeout(() => state.pillAnim && state.pillAnim.pause(), 110);"
LONG = "\\n\\n".join(f"第 {i} 段：这是一段很长的回答，用来看滚动到顶和到底时第一行、最后一行是不是清楚。" for i in range(1, 16))
CARD_JS = """
document.querySelector('#demo').hidden = true;
document.documentElement.dataset.theme = '{theme}';
setMode('ask'); startCard('这个报错是什么原因？');
live.draft = '""" + LONG + """'; finish({{ ok: true }});
"""
BOTTOM_JS = "const a = document.querySelector('#answer'); a.scrollTop = a.scrollHeight; updateFades(a);"
SETTINGS_JS = """
document.documentElement.dataset.theme = '{theme}';
{action}
document.querySelector('#data-note').scrollIntoView({{ block: 'center' }});
"""
DATA_ACTIONS = {
    "idle": "",
    "confirm": "state.moving = {{ target: 'D:' + String.fromCharCode(92) + 'SuperAide', size: '338 MB', problem: '' }}; renderData();",
    "moving": "state.moving = {{ target: 'D:' + String.fromCharCode(92) + 'SuperAide', percent: 45 }}; renderData();",
    "problem": "state.moving = {{ problem: I18N.t('数据已经在这里了') }}; renderData();",
}


def shots() -> list[tuple[str, str, str, str, tuple[int, int]]]:
    out = []
    for theme in ("dark", "light"):
        for lang in ("zh", "en"):
            q = "?lang=en" if lang == "en" else ""
            pill = PILL_JS.format(theme=theme)
            out.append((f"pill-{theme}-{lang}", f"index.html{q}", pill, "", (620, 520)))
            out.append((f"pill-open-{theme}-{lang}", f"index.html{q}", pill, OPEN_JS, (620, 520)))
            card = CARD_JS.format(theme=theme)
            out.append((f"card-top-{theme}-{lang}", f"index.html{q}", card, "", (760, 760)))
            out.append((f"card-bottom-{theme}-{lang}", f"index.html{q}", card, BOTTOM_JS, (760, 760)))
            for name, action in DATA_ACTIONS.items():
                js = SETTINGS_JS.format(theme=theme, action=action.format())
                out.append((f"data-{name}-{theme}-{lang}", f"settings.html{q}", js, "", (720, 520)))
    out.append(("pill-half-dark-zh", "index.html", PILL_JS.format(theme="dark"), HALF_JS, (620, 520)))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    todo = shots()
    view = QWebEngineView()
    view.move(QPoint(-4000, -4000))
    view.show()

    def run_next() -> None:
        if not todo:
            app.quit()
            return
        name, page, setup, after, size = todo.pop(0)
        view.resize(*size)
        url = QUrl.fromLocalFile(str(WEB / page.split("?")[0]))
        if "?" in page:
            url.setQuery(page.split("?", 1)[1])

        def loaded(_ok: bool) -> None:
            view.loadFinished.disconnect(loaded)
            QTimer.singleShot(400, lambda: view.page().runJavaScript(setup, 0, lambda _r: QTimer.singleShot(
                350, lambda: view.page().runJavaScript(after or "0", 0, lambda _r: QTimer.singleShot(
                    500, lambda: (view.grab().save(str(OUT / f"{name}.png")), print("saved", name), run_next()))))))

        view.loadFinished.connect(loaded)
        view.load(url)

    QTimer.singleShot(100, run_next)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
