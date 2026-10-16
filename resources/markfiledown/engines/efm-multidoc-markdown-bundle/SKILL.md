---
name: efm-multidoc-markdown-bundle
description: "All-in-one portable skill bundle for mixed PDF, Word, PowerPoint, and Excel conversion. PDF and PowerPoint use visual-first processing, while Word and Excel run text-first with embedded-media OCR. Copy this folder as-is into an empty project, then invoke /efm-multidoc.pipeline or run run.ps1 directly. Use this engine when the markfiledown runner selects OOXML extraction, or when processing presentations and workbooks. Triggers include: 混合文档转换, PowerPoint转换, Excel转换, OOXML提取, efm engine, visual-first PDF, multi-format conversion. Do NOT use directly for simple PDF/DOCX — prefer the markfiledown-0509 entry point."
---

# EFM Multi-Document Markdown Pipeline

## Positioning

这是一个可拷贝的单文件夹 skill bundle，不要求调用方再去拼接 adapter、step pack、模板目录或额外流程说明。

复制这个文件夹到别处后，调用方只需要关心两件事：

1. 入口文件是 `SKILL.md`
2. 调用命令是 `/efm-multidoc.pipeline`

本文件已经内嵌：

1. 入口协议
2. 流程步骤
3. 多种文档格式分支
4. evidence / freeze / trace / integrity 契约
5. 失败回跳规则
6. 输出目录标准

## Current Runnable Scope

当前 `efm-multidoc-markdown-bundle/` 是一个可直接试跑的多格式便携包。

当前已落地并验证的执行范围：

1. 输入：`pdf`、`doc`、`docx`、`ppt`、`pptx`、`xls`、`xlsx`
2. 支持：单文件输入或目录批处理输入
3. 输出：批量索引 + 每文档独立输出目录
4. 运行方式：`run.ps1` 或显式调用 `/efm-multidoc.pipeline`

## Portable Copy Contract

如果要把这个 bundle 拷到其他仓库或目录，默认只需要复制整个 `efm-multidoc-markdown-bundle/` 文件夹。

调用约束如下：

1. 不要求调用方再去找外部 adapter 文档
2. 不要求调用方再去组合多份 step 文件
3. 不要求调用方再去找模板文件才能明白产物格式
4. 所有运行协议以本文件为准

## Entry Command

统一显式调用入口：

```markdown
/efm-multidoc.pipeline
输入路径：@docs
输出目录：output/efm-multidoc-batch
格式：auto
风格：technical
PDF Agent回读校验：true
包含视觉资产链接：true
OCR：true
递归扫描：true
```

如果直接用终端运行，统一入口是：

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-batch"
```

## Input Contract

空项目试用版直接接受原始文件或目录：

1. `inputPath`
2. `outputRoot`

可选参数：

1. `markdownStyle`
2. `enablePdfAgentValidation`
3. `includeAssetLinks`
4. `enableOcr`
5. `recurse`
6. `pythonExe`

支持输入格式：

1. `pdf`
2. `doc` / `docx`
3. `ppt` / `pptx`
4. `xls` / `xlsx`

## Runtime Parameters

| Parameter | Required | Allowed Values | Meaning |
| --- | --- | --- | --- |
| `inputPath` | Yes | path | 单文件路径或目录路径 |
| `outputRoot` | Yes | path | 输出根目录 |
| `sourceFormat` | No | `auto`, `pdf`, `doc`, `docx`, `ppt`, `pptx`, `xls`, `xlsx` | 输入过滤提示 |
| `enablePdfAgentValidation` | No | `true`, `false` | `pdf/ppt/pptx` 这类视觉优先文档在生成 Markdown 后是否执行 agent 回读校验 |
| `markdownStyle` | No | `technical`, `narrative`, `audit-friendly` | Markdown 风格 |
| `includeAssetLinks` | No | `true`, `false` | 是否输出资产链接页 |
| `enableOcr` | No | `true`, `false` | 是否对视觉优先页面的低文本密度页，以及 Office 内置插图启用 OCR。开启时自动对 OCR 结果进行区域分类，并生成交互式复核报告供人工修正分类决策 |
| `recurse` | No | `true`, `false` | 目录输入是否递归扫描 |
| `pythonExe` | No | path | 指定 Python 可执行文件 |

## Standard Output Tree

运行结果统一输出到：

```text
<outputRoot>/
  index.md
  batch-manifest.json
  <doc-id>/
    intake-validation-report.md
    source.md
    final.md
    artifacts/
      pages/
      embedded-media/
    csv/
    evidence/
      ocr-review.html              ← 交互式 OCR 区域复核报告（开启 OCR 时生成）
      ocr-classification-decisions.json  ← 人工修正后的分类决策（用户导出后手动放入）
    markdown/
    .pipeline-state.json
```

## Format Routes

### PDF

1. 直接进入 PDF 视觉管线
2. 低文本密度页启用 OCR fallback
3. 输出 `source.md`、`final.md`、视觉资产、evidence、trace、review

### DOC / DOCX

1. `doc` 使用 Microsoft Word COM 归一为 `docx`，`docx` 直接使用原包
2. 直接读取 OOXML 文本和表格结构生成 `source.md` 与 `final.md`
3. OOXML 包中的 `word/media/*` 单独抽出
4. 仅对嵌入图片做 OCR，并尝试给出 `mermaid` 或解释性说明，不做页面级视觉修复

### PPT / PPTX

1. 使用 Microsoft PowerPoint COM 归一为 `pptx` + `pdf`
2. PDF 进入视觉管线
3. OOXML 包中的 `ppt/media/*` 单独抽出
4. 对嵌入图片做 OCR，并尝试给出 `mermaid` 或解释性说明

### XLS / XLSX

1. `xls` 先归一为 `xlsx`
2. 每个 sheet 导出为 `csv/*.csv`
3. 生成工作簿级 `source.md`、`final.md` 和 `evidence/workbook-manifest.json`
4. 如包内存在 `xl/media/*`，仅对内置图片做 OCR，不做页面级视觉修复

## OCR And Media Policy

1. 全图片页或低文本密度页的 OCR fallback 只对 `pdf/ppt/pptx` 这类视觉优先输入生效
2. `doc/docx/xls/xlsx` 这类文本优先输入直接走文本或结构化提取，不做页面级图像识别修复
3. `docx/pptx/xlsx` 的嵌入插图会单独抽出并做 OCR
4. 如果 OCR 结果显示明显流程 / 架构信号，bundle 会尝试生成简化 `mermaid`
5. 如果不适合画图，则输出解释性摘要
6. 开启 `enableOcr` 时，对 OCR 结果自动执行区域分类：
   - **正文**：行长 ≥ 15 字符、含规则说明用语（"用户"、"启用"、"开启后"、"请" 等）
   - **UI 噪音**：状态栏时间（"21:05"）、开关状态（"ON"/"OFF"/"READY"）、占位标记（"icon"/"Bar"/"插图"）、纯短数字
   - **不确定**：短文本块（4–8 字符），需要人工判定
7. 自动分类后生成 `evidence/ocr-review.html` 交互式报告：
   - 左侧显示页面截图，右侧列出每条 OCR 文本及其分类标签
   - 点击文本块可切换分类（正文 ↔ UI 噪音 ↔ 不确定）
   - 点击"导出决策 JSON"后，将文件保存为 `evidence/ocr-classification-decisions.json`
   - 重新运行管线时，自动读取该决策文件并只保留"正文"类文本写入 final.md

## Multimodal Agent Delegation

管线本身不调用任何 LLM API。所有多模态读图能力交给调用此 skill 的 agent：

1. 管线负责准备：`artifacts/pages/` 下的页面截图、tile 切片、region 区域裁剪
2. 调用方 agent 应使用自身多模态视觉能力读取这些图片，补充 `final.md` 中纯文本无法表达的结构、关系、箭头、callout 等语义
3. 管线产出的 `agent_brief.md`（doc-pre 引擎）和 `pdf-agent-review-report.json` 为 agent 提供读图指导和质量检查依据
4. 管线产出的 zone-based OCR 结构（`_rebuild_ocr_to_markdown`）已是纯本地计算的最佳文本骨架，agent 在此基础上做视觉增补

## Runtime Requirements

1. 需要 Python 环境
2. 首次运行会按 `requirements.txt` 自动安装依赖
3. Windows 上处理 `doc/ppt/xls` 时，需要 Microsoft Office COM 可用；`docx/xlsx` 默认走文本优先路径，不依赖页面级 PDF 渲染
4. 不依赖 LibreOffice、Pandoc、Tesseract

## Pipeline State Machine

状态文件固定写入 `<outputRoot>/.pipeline-state.json`。

最小状态协议：

1. step 开始前写入 `in-progress`
2. gate 通过后写入 `completed`
3. 回跳时将目标 step 重置为 `not-started`
4. 若输入哈希变化，则恢复时必须警告并要求重新确认

## Execution Phases

### Phase 1 Discover

1. 接收 `inputPath`
2. 如果是单文件，直接进入处理队列
3. 如果是目录，按 `sourceFormat` 和 `recurse` 规则扫描支持格式文件
4. 为每个输入文件生成稳定输出目录 `<doc-slug>-<hash>`

### Phase 2 Normalize

1. `pdf`：直接进入视觉文档处理
2. `doc/docx`：`doc` 归一为 `docx`，然后直接读取 OOXML 文本与表格结构
3. `ppt/pptx`：使用 PowerPoint COM 归一为 `pptx + pdf`
4. `xls/xlsx`：将 `xls` 归一为 `xlsx`

### Phase 3 Extract

1. 视觉文档走 PDF 视觉管线，生成页面图、evidence、trace、review
2. `docx` 直接提取文本块、表格块，并从 OOXML 包中提取嵌入图片到 `artifacts/embedded-media/`
3. `pptx/xlsx` 从 OOXML 包中提取嵌入图片到 `artifacts/embedded-media/`
4. `xlsx` 逐个 sheet 导出为 `csv/*.csv`

### Phase 4 OCR And Media Review

1. `pdf/ppt/pptx` 的低文本密度页面触发 OCR fallback（仅当 pdfplumber 返回空文本或乱码时）
2. OCR 结果自动进行区域分类：正文 / UI 噪音 / 不确定
3. 生成 `evidence/ocr-review.html` 交互式报告供人工复核
4. 人工确认后可导出决策 JSON，重新运行管线时自动读取并只保留正文文本
5. `doc/docx/xls/xlsx` 不做页面级视觉修复
6. `docx/pptx/xlsx` 的嵌入图片做 OCR
7. 如果 OCR 文本呈现明显流程 / 架构信号，尝试生成简化 `mermaid`
8. 如果不适合图形化，则生成解释性摘要

### Phase 5 Emit

1. 视觉文档输出 `source.md`、`final.md`、`artifacts/pages/*`、`evidence/*`、`markdown/*`
2. Word 文档输出 `source.md`、`final.md`、`evidence/word-manifest.json`，如有插图则附带 `artifacts/embedded-media/*`
3. 表格文档输出 `csv/*.csv`、`source.md`、`final.md`、`evidence/workbook-manifest.json`，如有插图则附带 `artifacts/embedded-media/*`
4. 批量根目录输出 `index.md` 和 `batch-manifest.json`
5. **纯图片 PDF Agent 多模态修复**：当检测到 PDF 为纯图片格式（pdfplumber 每页平均提取字符数 < 50），在 `final.md` 生成后自动写入 `multimodal-repair-brief.json` 和 `multimodal-repair-summary.md`。简报包含页面截图路径、OCR `source.md` 路径和修复规则。多模态 Agent 读取这些证据后，以 OCR 文本为内容主干、截图为结构参考，将 `final.md` 修复为格式良好的 Markdown。可通过 `--multimodal-repair` 控制：`auto`（默认，纯图片时写入简报）、`on`（始终写入）、`off`（不写入）。

## Completion Standard

1. 每个输入文件都有独立输出目录
2. `pdf/ppt/pptx` 视觉文档至少有 `source.md`、`final.md` 和页面资产
3. `doc/docx` 至少有直接文本导出的 `source.md`、`final.md` 和 `evidence/word-manifest.json`
4. `docx/pptx/xlsx` 的嵌入图片被抽出时，会形成 OCR 报告
5. `xls/xlsx` 的每个 sheet 都被导出为 CSV
6. 批量根目录生成 `index.md` 和 `batch-manifest.json`
7. 如启用回读校验，仅视觉优先文档生成 `markdown/pdf-agent-review-report.json`

## Recommended Invocation Patterns

### 单文件

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs\source.pptx" -OutputRoot ".\output\efm-multidoc-single"
```

### 混合目录

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-batch" -Recurse $true
```

### 只处理 Excel

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-xlsx-batch" -SourceFormat xlsx
```

## Empty Project Validation

建议至少准备一个 `pdf/docx/pptx/xlsx` 中的任意文件放到 `docs/` 目录，然后执行：

```powershell
.\efm-multidoc-markdown-bundle\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\efm-multidoc-batch" -PythonExe ".\.venv\Scripts\python.exe"
```

最低验证标准：

1. 批量根目录生成 `index.md`
2. 批量根目录生成 `batch-manifest.json`
3. 每个输入文件都有自己的 `<doc-slug>-<hash>/` 子目录
4. `pdf/ppt/pptx` 子目录中生成 `source.md`、`final.md` 和 `markdown/pdf-agent-review-report.json`
5. `doc/docx` 子目录中生成 `source.md`、`final.md` 和 `evidence/word-manifest.json`
6. `docx/pptx/xlsx` 含插图时，生成 `artifacts/embedded-media/embedded-media-report.md`
7. `xlsx` 输入时，生成 `csv/*.csv`

## Non-Negotiable Rules

1. 不允许从最终 Markdown 反推 evidence 或 coverage。
2. 不允许多模态复核直接改写基线计数。
3. 不允许静默丢失 `needs-clarification`。
4. 不允许把图片存在误当作图片语义已恢复。
5. 不允许把 OCR 文本直接当结构真相。
6. PDF 开启 agent 回读校验时，不允许跳过回读校验步骤。

## Completion Standard

只要满足以下条件，即认为本 pipeline 成功闭合：

1. 每个输入文件都被归档到独立输出目录
2. `pdf/ppt/pptx` 视觉文档的 `source.md`、`final.md`、页面资产、trace、review 都已生成
3. `doc/docx` 文档的直接文本导出结果和 `evidence/word-manifest.json` 已生成
4. `xls/xlsx` 文档的 CSV、工作簿清单，以及存在时的内置图片 OCR 报告已生成
5. 批量根目录的 `index.md` 和 `batch-manifest.json` 已生成
6. 阻断性回读问题没有被静默忽略
