"""读 Claude 会话记录：只打印用户问题（截掉环境部分）、工具调用和回答文字，不打印图片和工具结果全文。"""

import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
for line in path.read_text(encoding="utf-8").splitlines():
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        continue
    msg = rec.get("message") or {}
    role = msg.get("role") or rec.get("type")
    content = msg.get("content")
    if isinstance(content, str):
        content = [{"type": "text", "text": content}]
    for block in content or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind == "text" and block.get("text", "").strip():
            text = block["text"]
            if role == "user":
                text = text.split("【提问时的环境】")[0]  # 环境部分可能有隐私内容，不打印
            print(f"[{role}] {text.strip()[:700]}\n")
        elif kind == "tool_use":
            print(f"[{role} 工具] {block.get('name')} {json.dumps(block.get('input'), ensure_ascii=False)[:200]}\n")
        elif kind == "tool_result":
            body = block.get("content")
            snippet = body if isinstance(body, str) else json.dumps(body, ensure_ascii=False)
            print(f"[工具结果{'·出错' if block.get('is_error') else ''}] {snippet[:200]}\n")
