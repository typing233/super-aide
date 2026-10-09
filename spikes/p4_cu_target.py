"""Computer Use 自检用的靶子窗口：几个常见控件，每次变化把状态写进 JSON，驱动方据此核对动作有没有生效。

    python spikes/p4_cu_target.py <状态文件>
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit,
                               QListWidget, QPushButton, QPlainTextEdit, QVBoxLayout, QWidget)


def main() -> int:
    state_file = Path(sys.argv[1])
    app = QApplication(sys.argv)
    win = QWidget()
    win.setWindowTitle("CU 靶子窗口")
    win.resize(560, 520)
    win.move(80, 80)

    name = QLineEdit()
    name.setAccessibleName("姓名")
    city = QComboBox()
    city.setAccessibleName("城市")
    city.addItems(["北京", "上海", "广州", "深圳"])
    agree = QCheckBox("我同意条款")
    fruits = QListWidget()
    fruits.setAccessibleName("水果")
    fruits.addItems(["苹果", "香蕉", "橙子", "葡萄"])
    notes = QPlainTextEdit()
    notes.setAccessibleName("备注")
    submit = QPushButton("提交")
    clear = QPushButton("清空")
    status = QLabel("还没有提交")

    state = {"submitted": 0, "cleared": 0}

    def save() -> None:
        state.update(name=name.text(), city=city.currentText(), agree=agree.isChecked(),
                     fruit=fruits.currentItem().text() if fruits.currentItem() else "",
                     notes=notes.toPlainText())
        state_file.write_text(json.dumps(state, ensure_ascii=False), encoding="utf-8")

    def on_submit() -> None:
        state["submitted"] += 1
        status.setText(f"已提交 {state['submitted']} 次：{name.text()}")
        save()

    def on_clear() -> None:
        state["cleared"] += 1
        name.clear()
        notes.clear()
        save()

    for signal in (name.textChanged, city.currentTextChanged, agree.toggled, fruits.currentRowChanged,
                   notes.textChanged):
        signal.connect(lambda *_: save())
    submit.clicked.connect(on_submit)
    clear.clicked.connect(on_clear)

    form = QFormLayout()
    form.addRow("姓名", name)
    form.addRow("城市", city)
    form.addRow("", agree)
    form.addRow("水果", fruits)
    form.addRow("备注", notes)
    buttons = QHBoxLayout()
    buttons.addWidget(submit)
    buttons.addWidget(clear)
    layout = QVBoxLayout(win)
    layout.addLayout(form)
    layout.addLayout(buttons)
    layout.addWidget(status, alignment=Qt.AlignLeft)
    save()
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
