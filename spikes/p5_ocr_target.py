"""OCR 靶子：一个只有画布的窗口，按钮都是画出来的像素，UI Automation 里什么都没有（像远程桌面、游戏、自绘界面）。
点到哪个"按钮"就把它的名字追加写进第一个参数给的文件；点"保存"后画布上再画出"已保存"。

    python spikes/p5_ocr_target.py <输出文件>
"""

import ctypes
import sys
import tkinter as tk

ctypes.windll.shcore.SetProcessDpiAwareness(2)  # 和大多数现代应用一样按物理像素画
out = sys.argv[1]
root = tk.Tk()
root.title("OCR 靶子")
root.geometry("+240+240")
canvas = tk.Canvas(root, width=760, height=300, bg="#1f1f24", highlightthickness=0)
BUTTONS = [("保存", 40, 40), ("取消", 230, 40), ("Settings", 420, 40), ("导出为 PDF", 40, 150)]
W, H = 160, 56
for label, x, y in BUTTONS:
    canvas.create_rectangle(x, y, x + W, y + H, fill="#2d6cdf", outline="")
    canvas.create_text(x + W // 2, y + H // 2, text=label, fill="white", font=("Microsoft YaHei UI", 15))


def click(ev: tk.Event) -> None:
    for label, x, y in BUTTONS:
        if x <= ev.x <= x + W and y <= ev.y <= y + H:
            with open(out, "a", encoding="utf-8") as f:
                f.write(label + "\n")
            if label == "保存":
                canvas.create_text(520, 180, text="已保存", fill="#7ee787", font=("Microsoft YaHei UI", 16))


canvas.bind("<Button-1>", click)
canvas.pack()
root.mainloop()
