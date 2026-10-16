---
name: doc-pre-allinone-skill-0508
description: "Portable text-first document Markdown pipeline with block-level evidence tracing, pluggable agent-exec readback, and empty-project verification support. Converts PDF/DOCX into structured Markdown with source attribution and integrity checks. Use this engine when the markfiledown runner selects text-first processing, or when you need evidence-traced document conversion with readback validation. Triggers include: text-first文档转换, block-level evidence, 文档验证, document pipeline, 证据链转换, doc-pre engine, portable markdown pipeline. Do NOT use directly — prefer the markfiledown-0509 entry point for end-to-end document conversion."
---

# Portable Document Markdown Pipeline

## Positioning

这是一个可以整文件夹复制到空项目里直接验证的便携 bundle。

对外交付件就是整个 `doc-pre-allinone-skill-0508/` 目录，不是单个脚本，不是 runtime 子目录，也不是某个输出样例目录。

它和早期便携包相比，重点新增了两层：

1. `block-level evidence / trace / relation candidates`
2. `agent-exec` 回读执行层，既可用内置 backend，也可切换到外部命令 backend

这个 bundle 的主入口是 skill trigger `doc-markdown.pipeline`，本地 `run.ps1` 只是验证/回归适配器，不是产品主入口。

## Text-First Contract

这个 skill 对 PDF 的默认契约不是”截图优先重写正文”，而是：

1. OCR 文字识别是正文主渠道：优先使用 pdfplumber 提取内嵌文本；当 pdfplumber 返回空时（扫描版/图片 PDF），自动使用 RapidOCR 进行 OCR 回退
2. 抽取的文本根据行长度、标点、位置启发式地分类为标题、段落、列表项等结构
3. 页截图、tile、region 是多模态语义佐证渠道
4. `final.md` 必须先保留原文用词和句意，再用视觉证据修正层级、流程、分区、callout 和关系
5. 对于结构稳定、关系明确的宏观图页（如信息架构、页面布局、显式流程图），可以在正文旁并列输出 Mermaid 复刻
6. 当 Mermaid 不适用时（非特定文档模板的通用 PDF），尝试生成 ASCII 图作为回退：流程/状态转换页生成 ASCII 流程图，大纲/编号页生成 ASCII 层级图
7. 视觉证据不能替代已可读的正文文本；当视觉和文字冲突时，默认保留文字，并把冲突留给 evidence/readback 链路确认
8. 对演示页 / 页面流转页，页面态和动作线索可以概述，但说明块、callout、规则说明优先引用原始抽取 wording
9. 当演示页整页 OCR 被歌曲名、按钮名、计数或占位 UI 淹没时，优先做局部分栏 / region 抽取，不默认使用重型 agent 直接重写正文

## Empty Project Contract

复制整个 `doc-pre-allinone-skill-0508/` 文件夹到目标项目根目录后，不需要依赖当前仓库。

最小建议目录：

```text
target-project/
  doc-pre-allinone-skill-0508/
  docs/
    source.pdf
    source.docx
    source.pptx
    source.xlsx
  output/
```

## Entry Command

显式 skill 入口，也是推荐的对外调用入口：

```markdown
/doc-markdown.pipeline
输入文件：@docs/source.pdf
输出目录：output/doc-markdown
格式：auto
风格：technical
Agent Review回读校验：true
包含视觉资产链接：true
Agent Exec模式：builtin
```

对 Office 文件也一样：

```markdown
/doc-markdown.pipeline
输入文件：@docs/source.docx
输出目录：output/doc-markdown
格式：auto
Agent Review回读校验：true
```

终端入口只作为 fallback：

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 -InputFile ".\docs\source.pdf" -OutputRoot ".\output\doc-markdown"
```

## External Readback Backend

```powershell
.\doc-pre-allinone-skill-0508\run.ps1 \
  -InputFile ".\docs\source.pdf" \
  -OutputRoot ".\output\doc-markdown" \
  -AgentExecMode external-command \
  -AgentCommand "python .\my_agent.py {request} {response}"
```

## Runtime Parameters

| Parameter | Required | Allowed Values | Meaning |
| --- | --- | --- | --- |
| `inputFile` | Yes | path | 原始文档路径 |
| `outputRoot` | Yes | path | 输出根目录 |
| `sourceFormat` | No | string, default `auto` | 文档格式提示 |
| `enableAgentReviewValidation` | No | `true`, `false` | 是否执行 readback agent |
| `markdownStyle` | No | `technical`, `narrative`, `audit-friendly` | Markdown 风格声明 |
| `includeAssetLinks` | No | `true`, `false` | 是否生成资产链接页 |
| `agentExecMode` | No | `builtin`, `external-command`, `disabled` | readback backend |
| `agentCommand` | No | string | 外部命令 backend 的命令行 |
| `pythonExe` | No | path | 指定 Python 可执行文件 |

## Standard Output Tree

```text
<outputRoot>/
  .pipeline-state.json
  intake-validation-report.md
  <document_id>/
    source.md
    final.md
    artifacts/
      pages/
      regions/
      tables/
    evidence/
      block-catalog.json
      relation-candidates.md
      reading-order-map.json
      visual-review-queue.json
      visual-review-summary.md
      md-input-freeze.json
      freeze-sources.md
    markdown/
      output.md
      block-md-trace.md
      asset-links.md
      agent-review-request.json
      agent-review-response.json
      agent-review-report.json
      agent-review-summary.md
      markdown-qv-report.md
      back-edge-decision.json
    markdown-integrity-report.md
    integrity-metrics.json
    manifest.json
    multimodal-correction-request.json  ← Stage 4 agent correction input (deleted after agent processes)
    quality-gate-request.json           ← Stage 5 quality gate input (written by pipeline)
    quality-gate-report.json            ← Stage 5 quality gate output (agent verification report)
```

## Route Matrix

1. PDF: text baseline + multimodal semantic evidence + text-first reconstruction + selective Mermaid reconstruction + agent readback
2. DOCX: baseline + evidence + compatibility output
3. PPTX: baseline + evidence + compatibility output
4. XLSX/XLS/CSV: baseline + evidence + CSV compatibility output
5. 其他文本类文件: baseline + evidence + compatibility output

## Spreadsheet Output Contract

Excel / CSV 路由的主兼容产物不是 Markdown，而是 CSV：

1. `artifacts/tables/*.csv` 保存 canonical CSV
2. `compatibility/*.csv` 提供直接读取的导出文件
3. 多 sheet 工作簿会额外写出 `compatibility/*-csv-exports.json` 索引
4. `single_csv` 或 `csv_exports_index` 会写进 manifest 的 `compatibility_outputs`

## Execution Stages

### Stage 1 Baseline Extraction

目标：先得到 `source.md`，它是 PDF / Office 文档正文内容的 canonical text substrate；后续重建默认不能脱离这个文字主源。

### Stage 1.5 Block Evidence Merge

目标：把正文、页级截图、tile、region、文本摘录统一进 `raw_block_key` 体系。

关键产物：

1. `evidence/block-catalog.json`
2. `markdown/block-md-trace.md`

### Stage 2 Multimodal Preparation

目标：为复杂 PDF 页面生成 screenshot、tile、region，给正文重建和 readback 提供语义证据。

约束：这些视觉资产用于理解页面分区、图示、箭头、callout、流程和阅读顺序，不作为正文文字的主替代源；只有当宏观关系足够稳定时，才允许产出 Mermaid 复刻。

### Stage 3 Text-First Multimodal Reconstruction

目标：写出 `final.md`，先按文本抽取结果重建正文，再用视觉证据补回 PDF 上纯文本无法稳定表达的结构和语义。

输出要求：

1. 正文文字以 `source.md` / 页级文本抽取为主
2. 截图只用于修正结构、关系和视觉语义
3. 不允许把截图理解结果直接当成正文的唯一来源去重写整页内容
4. `final.md` 需要同时保留文本主干和视觉锚点
5. 对显式的宏观流程 / 信息架构 / 页面布局，优先输出“文字主干 + Mermaid 复刻 + 视觉锚点”的并列结构
6. 如果关系图并不稳定或条件节点依赖截图状态，优先保留视觉锚点和规则说明，而不是强行生成细碎 Mermaid
7. 对演示页，允许输出“页面态 / 动作线索 + 原文说明摘录 + 视觉锚点”的结构；其中说明摘录优先使用原文，不把界面占位词抬升为正文

### Stage 3.5 Agent Exec Readback

目标：在 `final.md` 生成后执行独立 readback。

当前只有 PDF 路由会真正执行 PDF-specific multimodal readback；非 PDF 输入会保留兼容 sidecar 文件，但状态标记为 `skipped`。

也就是说，PDF 的识别链路不是”只跑脚本”，而是 skill 触发后进入同一条 pipeline，再在 PDF 路由中执行：

1. `PDFMultimodalPreparationWorker.prepare(...)`
2. `PDFVisualRepairAdapter.repair(...)`
3. `AgentReviewExecutor.execute(...)`

readback 输入：

1. `markdown/agent-review-request.json`
2. `evidence/block-catalog.json`
3. `evidence/relation-candidates.md`
4. `markdown/block-md-trace.md`
5. `final.md`

readback 输出：

1. `markdown/agent-review-response.json`
2. `markdown/agent-review-report.json`
3. `markdown/agent-review-summary.md`
4. `markdown/back-edge-decision.json`

### Stage 4 Agent Multi-modal Correction

目标：**让 Codex agent 逐页对比截图和 final.md，找出遗漏内容并直接修正 final.md。**

这是 pipeline 自动写入的。脚本在 `final.md` 生成后创建 `multimodal-correction-request.json`，其中包含：

1. `final_md` — 当前 final.md 全文
2. `source_md` — 当前 source.md 全文（OCR 基线）
3. `pages[]` — 每页的截图路径、tile 路径、region 路径、OCR 文本、视觉复核标记

**Agent 执行步骤**（当检测到该请求文件时）：

1. 阅读 `final.md` 全文，了解当前文档结构
2. 逐页查看 `screenshot`，对比 final.md 中对应章节
3. 对 `needs_visual_review=true` 的页面重点检查
4. 如页面有 tiles/regions，用它们查看细节
5. 对照 `source.md` 确认所有 OCR 文字都已保留
6. 发现遗漏时，在 final.md 对应位置补充
7. 发现错误时，以截图为准修正
8. 修正后用 `<!-- agent-corrected: 原因 -->` 标记
9. 完成后删除 `multimodal-correction-request.json`

**通用性**：该步骤不对文档做任何假设。以截图和 OCR 文字为唯一依据，适用于所有 PDF 文档。

### Stage 5 Multimodal Quality Gate

目标：**让 Agent 用多模态能力做最终校验——读图验证 final.md 的层级、标号、流程、分区是否正确。**

这是 Stage 4 Correction 之后的独立校验环节。修正者不能同时是判定者。

**执行流程**：

1. 管线写入 `quality-gate-request.json`（含 final.md、source.md、每页截图路径、页面类型推断、检查清单）
2. Agent 读取请求 + 截图 + final.md
3. Agent 按检查清单逐页校验：
   - 通用：完整性、阅读顺序、无编造
   - settings_tree：父子层级嵌套正确
   - annotated_ui：标号映射完整、页面分区正确
   - flow：流程方向正确、状态迁移链完整
   - variant_matrix：维度识别正确、显隐关系准确
   - layout：空间分区正确
4. Agent 写入 `quality-gate-report.json`，包含 `overall_verdict`（pass/fail/pass-with-notes）
5. 若 `fail` 且修复轮次 < 2：将失败项转为定点修复请求 → Agent 修复 final.md → 回到步骤 1

**校验报告结构**：

```json
{
  "overall_verdict": "pass | fail | pass-with-notes",
  "pages": [
    {
      "page_number": 3,
      "page_type": "annotated_ui",
      "verdict": "pass | fail",
      "checks": [
        { "category": "callout_mapping", "status": "pass | fail | skip", "detail": "..." }
      ],
      "issues": ["..."],
      "fix_suggestion": "..."
    }
  ],
  "summary": { "total_pages": 10, "passed": 8, "failed": 2 }
}
```

### Stage 6 Integrity Aggregation

目标：把 evidence、trace、agent review 汇总成完整性判断。

关键产物：

1. `markdown-integrity-report.md`
2. `integrity-metrics.json`

## Current Runnable Scope

当前便携包的可执行承诺范围包括：

1. PDF
2. DOCX
3. PPTX
4. XLSX / XLS / CSV
5. 通用文本类文件

## Validation Goal

如果你把这个目录复制到空项目后运行成功，至少应该能验证：

1. 能生成 `source.md` 和 `final.md`
2. 能生成 `block-catalog.json` 和 `block-md-trace.md`
3. 能生成 `agent-review-request.json` 和 `agent-review-response.json`
4. 能生成 `multimodal-correction-request.json`（Stage 4 agent 多模态修正输入）
5. agent 处理后 `multimodal-correction-request.json` 被删除，`final.md` 已被修正
6. 能生成 `markdown-integrity-report.md`
7. 对非 PDF 输入，`agent-review-report.json` 应显示 `status=skipped`
8. 对 spreadsheet 输入，`compatibility_outputs` 应包含 `single_csv` 或 `csv_exports_index`

## Agent 执行指令

**当 pipeline 脚本运行完毕后，如果检测到 `multimodal-correction-request.json` 文件，Agent 必须执行以下操作：**

1. 读取该 JSON 文件，获取 `final_md`、`source_md`、`pages[]`
2. 对每个 page：
   - 读取 `screenshot`（全页截图）
   - 如果有 `tiles`，按顺序读取高清分块图
   - 如果有 `regions`，读取区域截图（细节）
3. 逐页对比截图与 `final_md`，检查：
   - 截图上的信息是否都已体现在 final.md 中
   - final.md 中是否有与截图不一致的描述
   - source.md 中的 OCR 文字是否都已保留
4. 对发现的问题直接在 final.md 中修正
5. 用 `<!-- agent-corrected: 原因 -->` 标记每处修改
6. 确认 final.md 质量足够后，**删除 `multimodal-correction-request.json`**

同样的规则适用于 `multimodal-reconstruction-request.json`（Stage 2/3 的纯图 PDF 重建请求）。

这些请求文件是 pipeline 自动写入的信号，不是手动创建的。看到它们就应该执行对应操作。