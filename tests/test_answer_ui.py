"""回答界面（ui/web/app.js）里的小函数：结果提示的一句话。用 Node 跑原样的函数（没有 Node 就跳过）。"""

import json
import re
import shutil
import subprocess

import pytest

from super_aide import history, paths

APP_JS = paths.UI_INDEX.with_name("app.js")


def js_function(name: str) -> str:
    source = APP_JS.read_text(encoding="utf-8")
    match = re.search(rf"^function {name}\(.*?^\}}$", source, re.M | re.S)
    assert match, f"app.js 里没有 {name}"
    return match.group(0)


@pytest.mark.skipif(shutil.which("node") is None, reason="没有 Node.js")
def test_toast_line(tmp_path):
    cases = {
        "已完成：新建了 `D:\\out\\a.txt`，内容是 `1`。\n撤销：删掉它": "新建了 D:\\out\\a.txt，内容是 1。",  # 没有 Markdown 记号
        "已完成：3 个文件已删除。": "3 个文件已删除。",          # 开头的数字是正文，不是编号
        "1. 已完成：装好了 pandas": "装好了 pandas",             # 真的编号照样去掉
        "**已完成**：版本 3.5 已安装": "版本 3.5 已安装",        # 加粗记号去掉后也认得出前缀；3.5 不是编号
        "Done: created [the report](https://x.y/r) in Downloads": "created the report in Downloads",
        "## 2026-10-10 的备份已完成": "2026-10-10 的备份已完成",
    }
    script = tmp_path / "toast.js"
    script.write_text(js_function("summaryLine") + "\nconst cases = " + json.dumps(list(cases), ensure_ascii=False)
                      + ";\nconsole.log(JSON.stringify(cases.map(summaryLine)));\n", encoding="utf-8")
    out = subprocess.run(["node", str(script)], capture_output=True, text=True, encoding="utf-8", check=True)
    assert json.loads(out.stdout) == list(cases.values())


def test_history_preview_keeps_leading_numbers():
    assert history._preview("3 个文件已删除。") == "3 个文件已删除。"
    assert history._preview("1. 打开设置") == "打开设置"
    assert history._preview("- **注意**：`pip` 装到了别的 Python") == "注意：pip 装到了别的 Python"
