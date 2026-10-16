# efm-multidoc-markdown-bundle

这是一个可直接复制到空项目里的 all-in-one 多格式文档解析 skill bundle。PDF/PPT 走视觉优先，Word/Excel 走文本优先，仅对内置插图做 OCR。

## 稳定命名约定

为了避免和仓库里其他试验性目录或历史输出撞名，这个分发版固定使用下面这套名称：

1. 分发文件夹：`efm-multidoc-markdown-bundle/`
2. Agent 显式调用命令：`/efm-multidoc.pipeline`
3. 单文件默认输出目录：`output/efm-multidoc-single`
4. 批量默认输出目录：`output/efm-multidoc-batch`
5. Excel-only 默认输出目录：`output/efm-multidoc-xlsx-batch`

## 支持输入

1. `pdf`
2. `doc` / `docx`
3. `ppt` / `pptx`
4. `xls` / `xlsx`

其中：

1. `pdf / ppt / pptx` 输出 `source.md`、`final.md`、视觉资产、evidence、trace、PDF agent review
2. `doc / docx` 直接输出文本与表格导出的 `source.md`、`final.md`、`evidence/word-manifest.json`，如有插图则附带 `artifacts/embedded-media/*`
3. `xls / xlsx` 输出每个 sheet 的 `csv/*`、`source.md`、`final.md` 和工作簿清单；如有内置图片则附带 `artifacts/embedded-media/*`

## 需要复制什么

最简单的方式是直接复制整个 `efm-multidoc-markdown-bundle/` 文件夹。

如果你只想按最小集合核对，分发目录里应该只有这 8 个文件：

1. `README.md`
2. `SKILL.md`
3. `skill.yaml`
4. `bundle-manifest.json`
5. `run.ps1`
6. `bundle_runner.py`
7. `pipeline_runner.py`
8. `requirements.txt`

## 运行方式

复制到目标项目根目录后，可以二选一：

1. 让 Agent 读取 `SKILL.md`，显式调用 `/efm-multidoc.pipeline`
2. 直接运行 `run.ps1`

### 单文件

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs\source.docx" -OutputRoot ".\output\efm-multidoc-single"
```

### 混合目录批处理

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-batch"
```

### 指定虚拟环境 Python

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-batch" -PythonExe ".\.venv\Scripts\python.exe"
```

## 运行前提

1. 目标机器可用 `python` 或 `py -3`，或者显式传入 `-PythonExe`
2. 首次运行会按 `requirements.txt` 自动安装依赖
3. Windows 上如果要处理 `doc/ppt/xls`，或对 `pptx` 保留高保真视觉还原度，需要安装 Microsoft Office，因为 bundle 使用 Office COM 做格式归一和 PDF 渲染
4. 不依赖 `LibreOffice`、`pandoc`、`tesseract`

## 主要产物

运行后会在 `<outputRoot>/` 下得到：

1. `index.md`：批量入口索引
2. `batch-manifest.json`：所有输入文件的处理清单
3. 每个文档一个独立子目录 `<doc-slug>-<hash>/`

视觉文档子目录中通常包含：

1. `source.md`
2. `final.md`
3. `artifacts/pages/*`
4. `artifacts/embedded-media/*`（PPTX 以及含插图的 Office 文档）
5. `evidence/*`
6. `markdown/*`

表格文档子目录中通常包含：

1. `csv/*.csv`
2. `source.md`
3. `final.md`
4. `evidence/workbook-manifest.json`

Word 文档子目录中通常包含：

1. `source.md`
2. `final.md`
3. `evidence/word-manifest.json`
4. `artifacts/embedded-media/*`（仅当包内存在插图时）

## 空项目验证方式

建议至少做一次目录批处理 smoke test：

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-batch" -PythonExe ".\.venv\Scripts\python.exe"
```

验证通过的最低标准：

1. `output/efm-multidoc-batch/index.md` 已生成
2. `output/efm-multidoc-batch/batch-manifest.json` 已生成
3. 至少存在一个 `<doc-slug>-<hash>/final.md`
4. 如果输入包含 `doc/docx`，存在 `evidence/word-manifest.json`
5. 如果输入包含 `docx/pptx/xlsx` 且带插图，存在 `artifacts/embedded-media/embedded-media-report.md`
6. 如果输入包含 `xls/xlsx`，存在 `csv/*.csv`
7. 如果启用了 PDF 回读校验，视觉文档存在 `markdown/pdf-agent-review-report.json`

## 建议目录结构

```text
target-project/
  efm-multidoc-markdown-bundle/
  docs/
    a.pdf
    b.docx
    c.pptx
    d.xlsx
  output/
```

## 当前状态

这个干净分发版来自已经实跑通过的多格式 bundle，当前仓库内已完成混合格式样例目录验证。
