---
name: python-env
description: 排查 Windows 上的 Python 环境问题：装了包还提示找不到模块、pip 装到了别的 Python、敲 python 打开了微软商店、多个 Python / conda / venv / uv 混用、PATH 顺序不对、版本不对、装包编译失败。
---

# Python 环境

"装了却找不到"几乎都是同一个原因：运行代码的 Python 和装包的 Python 不是同一个。先找出运行代码的是哪一个，再往它里面装。

## 1. 找出运行代码的 Python

- 报错来自终端或脚本：在同一个终端里运行 `python -c "import sys; print(sys.executable, sys.version)"`；PowerShell 里 `Get-Command python, python3, py -All | Format-Table Source` 能看到所有同名命令。
- 来自 VS Code：看状态栏右下角选中的解释器，或者工作区 `.vscode/settings.json` 里的 `python.defaultInterpreterPath`。
- 来自 Jupyter：见 jupyter-debug 技能（内核的 Python 经常和终端的不一样）。
- 项目里有 `.venv`、`venv`、`uv.lock`、`environment.yml`、`poetry.lock` 的，通常应该用项目自己的环境。

## 2. 往同一个 Python 里装

- 用 `<那个 python 的完整路径> -m pip install <包>`，不要单独敲 `pip`。
- conda 环境：`conda install -n <环境> <包>`；或者先 `conda activate <环境>`，再 `python -m pip install <包>`。
- uv 项目：`uv add <包>`（写进 pyproject.toml）；或者 `uv pip install --python <路径> <包>`。
- 装完用同一个 Python 验证：`<python> -c "import <模块>; print(<模块>.__file__)"`。
- 包名和模块名可能不一样：opencv-python → cv2，Pillow → PIL，scikit-learn → sklearn，python-docx → docx，PyYAML → yaml，beautifulsoup4 → bs4。

## 3. 常见情况

- 敲 `python` 打开了微软商店，或者什么都不输出：这是 Windows 的"应用执行别名"。到 设置 → 应用 → 高级应用设置 → 应用执行别名，关掉 python.exe 和 python3.exe；或者改用 `py` 启动器。
- 装了好几个 Python：`py -0p` 列出所有版本和路径；PATH 里靠前的那个生效，用 `$env:Path -split ';'` 看顺序。
- pip 很慢或超时：多半是网络问题，见 network-proxy 技能。国内可以临时加镜像：`-i https://pypi.tuna.tsinghua.edu.cn/simple`。
- 权限错误（Python 装在 Program Files 下）：加 `--user`，或者改用虚拟环境。不要用管理员身份往系统 Python 里装。
- 编译失败、提示需要 Microsoft C++ Build Tools：先找现成的 wheel（换个包版本，或者加 `--only-binary :all:`），实在不行再装 Build Tools。

## 4. 汇报

说清楚用的是哪个 Python（路径）、包装到了哪里，用户下次就知道该用哪个。

问答模式：只运行第 1 步的只读命令，然后给出装包的命令。
