"""截图检查：新手指引的欢迎页、每一步的气泡（尾巴朝向按实际摆法）、都会了；深浅色、中英文。

网页在屏幕外渲染，状态用真的 tour.Tour 生成（文字和宿主给的一样），存到 spikes/out/p13-tour/。
气泡和目标摆在一起是什么样子要看真机（我们的界面不进截图，真机检查见 docs/design.md 3.10 节）。

    uv run python spikes/p13_tour_shots.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QTimer, QUrl
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import QApplication

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from super_aide import i18n, tour  # noqa: E402

WEB = ROOT / "src" / "super_aide" / "ui" / "web"
OUT = ROOT / "spikes" / "out" / "p13-tour"
#: 每一步的气泡在真机上尾巴朝哪（输入框在下方时气泡在它上面；胶囊、托盘在右下角）
TAILS = {"center": "none", "input": "down", "card": "up", "pill": "down", "tray": "down"}


def state(lang: str, theme: str, index: int | None, hidden: bool = False) -> dict:
    i18n.set_language(lang)
    t = tour.Tour()
    if index is None:
        t.finish()
    elif index >= 0:
        t.start()
        t.index = index
    data = t.state("Alt+Q", "Alt+W", hidden=hidden)
    target = "center" if index is None else (t.step.target if t.step else "")
    data.update(layout="welcome" if index == -1 else "bubble", theme=theme, lang=lang, target=target)
    i18n.set_language("zh")
    return data


def js(data: dict) -> str:
    tail = TAILS.get(data.get("target", ""), "none")
    place = (f"const r = document.querySelector('#bubble').getBoundingClientRect();"
             f"tour.place({{ tail: '{tail}', at: r.left + Math.min(56, r.width / 2), pop: false }});")
    return (f"document.querySelector('#demo').hidden = true; tour.update({json.dumps(data, ensure_ascii=False)});"
            f"{place if data['layout'] == 'bubble' else ''} 0")


def shots() -> list[tuple[str, str]]:
    out = []
    for theme in ("dark", "light"):
        for lang in ("zh", "en"):
            tag = f"{theme}-{lang}"
            out.append((f"welcome-{tag}", js(state(lang, theme, -1))))
            for i, step in enumerate(tour.steps()):
                if step.target:
                    out.append((f"{i}-{step.key}-{tag}", js(state(lang, theme, i))))
            out.append((f"7-tray-hidden-{tag}", js(state(lang, theme, 7, hidden=True))))
            out.append((f"9-done-{tag}", js(state(lang, theme, None))))
    return out


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    app = QApplication(sys.argv)
    todo = shots()
    view = QWebEngineView()
    view.move(QPoint(-4000, -4000))
    view.resize(640, 420)
    view.show()

    def run_next() -> None:
        if not todo:
            app.quit()
            return
        name, setup = todo.pop(0)

        def loaded(_ok: bool) -> None:
            view.loadFinished.disconnect(loaded)
            QTimer.singleShot(300, lambda: view.page().runJavaScript(setup, 0, lambda _r: QTimer.singleShot(
                900, lambda: (view.grab().save(str(OUT / f"{name}.png")), print("saved", name), run_next()))))

        view.loadFinished.connect(loaded)
        view.load(QUrl.fromLocalFile(str(WEB / "tour.html")))

    QTimer.singleShot(100, run_next)
    app.exec()
    return 0


if __name__ == "__main__":
    sys.exit(main())
