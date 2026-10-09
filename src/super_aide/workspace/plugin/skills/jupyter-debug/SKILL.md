---
name: jupyter-debug
description: 修 Jupyter / JupyterLab / Notebook 里的报错，包括本机的、VS Code 里的 .ipynb，以及浏览器里的云端 Notebook（ModelScope、Colab、Kaggle、PAI、JupyterHub 等）：模块找不到、内核挂掉或连不上、单元格报错、显存或内存不足、内核选错。
---

# Jupyter 报错

## 1. 先分清是哪种 Notebook

- 本机的：地址是 localhost / 127.0.0.1，或者是 VS Code 里打开的 .ipynb。可以在电脑上运行命令。
- 云端的：ModelScope、Colab、Kaggle、阿里云 PAI、公司的 JupyterHub 等。内核跑在远端，本机的 pip 和 python 管不到它。只能在 Notebook 里改单元格、运行代码，或者用它网页里的终端。操作模式下用 Browser Use / Computer Use 在页面上操作。

## 2. 找出内核用的 Python

在 Notebook 里新建一个单元格运行：

```python
import sys; print(sys.executable); print(sys.version)
```

装包一律在 Notebook 里用 `%pip install <包>`，它会装进当前内核；不要用 `!pip`。装完重启内核（Kernel → Restart），再重新运行。

## 3. 常见报错

先读页面上的文字（环境里的框选区域原文、前台窗口的完整内容，或者用 read 工具），不要只看截图；
看图会把拼错的名字自动"纠正"过来。几个单元格都报错时，先修最早报错的那一格。

- `ModuleNotFoundError`：先逐字母核对报错里的模块名和代码里的拼写——拼错了就改代码，不用装包（`modescope` 应为 `modelscope`；
  `sklearn` 要装 `scikit-learn`、`cv2` 要装 `opencv-python`、`PIL` 要装 `pillow`）。名字没错才是真缺包，按第 2 步装。本机的还可能是内核选错了：看右上角的内核名，换成对应的环境；或者在那个环境里运行 `python -m ipykernel install --user --name <名字>` 注册一个内核。
- 内核挂掉、Kernel died、一直显示忙：多半是内存或显存不够。减小 batch size 或数据量；`del` 掉大变量后 `import gc; gc.collect()`；PyTorch 用 `torch.cuda.empty_cache()`。
- `CUDA out of memory`：同上；再确认没有别的进程占着显卡（本机运行 `nvidia-smi`）。
- 连不上内核、404：本机的重启 Jupyter 服务；云端的刷新页面，或者重启实例。
- 变量报 `NameError`：先看定义它的那一格有没有报错——那一格失败了（比如 import 报错），变量就没定义，修好那一格再往下运行。
  没报错的话是那一格还没运行，或者内核重启过：从头按顺序运行（Run All）。
- 文件找不到：云端的工作目录和本机不一样，用 `import os; print(os.getcwd(), os.listdir())` 确认。

## 4. 操作模式下修云端 Notebook

1. 用 read 读整个页面的文字（包括没滚动到的单元格和输出），逐字看清出错的单元格和完整的报错。
2. 在出错的单元格上方插入修复用的单元格（比如 `%pip install ...`），或者只改出错的那一行。不要删掉用户的代码。
3. 需要时重启内核，从头运行到出错的单元格，确认不再报错。
4. 汇报改了哪个单元格、怎么撤销。
