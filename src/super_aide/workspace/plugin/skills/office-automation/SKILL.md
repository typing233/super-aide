---
name: office-automation
description: 处理 Word、Excel、PowerPoint（以及 WPS）文档：批量修改内容、生成或填写表格、转 PDF 等格式转换、合并拆分、提取数据，以及操作用户正打开着的 Office 文档。
---

# Office 文档

## 选方法

- 有专门的文档、表格、演示文稿技能时（比如 Codex 的 documents、spreadsheets、presentations），优先用它们。
- 只处理文件、不需要用户正开着的窗口：用 Python 库最稳。
  - Word：`python-docx`；
  - Excel：`openpyxl`（保留格式），数据处理用 `pandas`；
  - PowerPoint：`python-pptx`。
  - 先查库有没有装，没有就装进当前的 Python（见 python-env 技能）。
- 用户正开着、想实时看到变化，或者只有 Office 能做的（宏、刷新透视表、精确版式、转 PDF）：通过 COM 操作本机的 Office。

```powershell
# 连上已经打开的 Excel（需要 Windows PowerShell 5.1，即 powershell.exe）
$excel = [Runtime.InteropServices.Marshal]::GetActiveObject('Excel.Application')
$wb = $excel.ActiveWorkbook
$ws = $wb.ActiveSheet
$ws.Range('A1').Value2
```

- PowerShell 7（pwsh）里没有 `GetActiveObject`，改用 Python：`import win32com.client; excel = win32com.client.GetActiveObject('Excel.Application')`。
- Word 是 `Word.Application`，PowerPoint 是 `PowerPoint.Application`。
- 没打开时用 `New-Object -ComObject Excel.Application` 新开一个，最后记得 `$excel.Quit()`。
- WPS 的 COM 名称：表格 `KET.Application`（老版本 `et.Application`），文字 `KWPS.Application`（`wps.Application`），演示 `KWPP.Application`（`wpp.Application`）。

转 PDF：

- Word：`$doc.ExportAsFixedFormat($pdfPath, 17)`
- Excel：`$wb.ExportAsFixedFormat(0, $pdfPath)`
- PowerPoint：`$pres.SaveAs($pdfPath, 32)`

## 规矩

- 改之前先备份，或者输出到新文件。除非用户明确要求，不要直接覆盖原文件。
- 用户正开着的文件：要么用 COM 改，要么提醒用户先关掉再用库改。否则文件被占用，或者改完又被 Office 覆盖。
- 大表格先看结构（表头、行数、合并单元格），再动手；改完抽查几处，确认结果对。
- openpyxl 写进去的公式不会被计算。需要计算结果时，用 Excel 打开重新计算，或者用 COM。

## 汇报

改了哪个文件（路径）、改了什么、备份在哪。

问答模式：只读取和分析文件内容，给出做法。
