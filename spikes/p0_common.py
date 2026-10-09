"""P0 验证脚本共用的小工具。"""

from __future__ import annotations

import base64
import io
import json
import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

TRACEBACK = (
    "Traceback (most recent call last):\n"
    '  File "C:\\work\\analysis.py", line 3, in <module>\n'
    "    import pandas as pd\n"
    "ModuleNotFoundError: No module named 'pandas'"
)


def synthetic_error_png() -> bytes:
    """合成一张"报错截图"，验证时只发它，不发真实屏幕。"""
    img = Image.new("RGB", (900, 200), (30, 30, 30))
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(r"C:\Windows\Fonts\consola.ttf", 22)
    draw.multiline_text((20, 20), TRACEBACK, fill=(240, 90, 90), font=font, spacing=10)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def synthetic_error_b64() -> str:
    return base64.b64encode(synthetic_error_png()).decode()


def claude_env_from_settings() -> dict[str, str]:
    """从 ~/.claude/settings.json 取出 Claude Code 的服务地址和令牌（只传给子进程，不打印）。"""
    settings = json.loads((Path.home() / ".claude" / "settings.json").read_text(encoding="utf-8"))
    env = settings.get("env", {})
    return {k: v for k, v in env.items() if k.startswith("ANTHROPIC_")}


def strip_nested_session_env() -> None:
    """验证脚本是从 Claude Code 会话里启动的；清掉会让子进程误以为自己是嵌套会话的变量。"""
    for name in list(os.environ):
        if name == "CLAUDECODE" or name.startswith(("CLAUDE_CODE_", "CLAUDE_AGENT_SDK")):
            del os.environ[name]
