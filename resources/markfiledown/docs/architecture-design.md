# MarkFileDown 0509 — 详细设计架构文档

> **版本**: v1.0.0  
> **最后更新**: 2026-06-02  
> **适用范围**: `mark-file-down/` 整个技能包及其两个 vendored engine

---

## 目录

1. [概述](#1-概述)
2. [系统总览](#2-系统总览)
3. [核心设计理念](#3-核心设计理念)
4. [架构分层](#4-架构分层)
5. [集成 Runner（编排层）](#5-集成-runner编排层)
6. [Engine 1: doc-pre-allinone（文本优先引擎）](#6-engine-1-doc-pre-allinone文本优先引擎)
7. [Engine 2: efm-multidoc（OOXML 提取引擎）](#7-engine-2-efm-multidocooxml-提取引擎)
8. [数据模型](#8-数据模型)
9. [路由与决策机制](#9-路由与决策机制)
10. [输出目录结构](#10-输出目录结构)
11. [接口与调用协议](#11-接口与调用协议)
12. [关键流程时序](#12-关键流程时序)
13. [多模态修复契约](#13-多模态修复契约)
14. [依赖关系](#14-依赖关系)
15. [设计决策记录](#15-设计决策记录)
16. [已知问题与修复历史](#16-已知问题与修复历史)
17. [扩展指南](#17-扩展指南)

---

## 1. 概述

### 1.1 定位

MarkFileDown 0509 是一个**便携式文档转 Markdown 技能包**，用于将 PDF、DOCX、PPTX、XLSX 以及混合格式文件夹批量转换为高保真 Markdown。它是一个 Claude Code skill bundle，可以在空项目中直接运行。

### 1.2 核心价值

- **双引擎对比选主**: 每个文档同时经过 `doc-pre`（文本优先）和 `efm`（OOXML 提取）两个引擎处理，然后自动选择更强的输出
- **文本优先契约**: OCR 文字是正文主渠道，截图/区域仅用于修正结构而非替代文字
- **证据链追溯**: 每个 block 都有 raw_block_key，可在 evidence 文件中追溯来源
- **静默执行**: 不弹出浏览器、文件管理器或 Office UI
- **可移植**: 整个 `mark-file-down/` 文件夹复制到空项目即可运行

### 1.3 支持的输入格式

| 格式类别 | 扩展名 | 主要引擎 |
|---------|--------|---------|
| PDF | `.pdf` | doc-pre (文本优先) + efm (视觉优先) |
| Word | `.doc`, `.docx` | efm (OOXML 文本提取) |
| PowerPoint | `.ppt`, `.pptx` | efm (COM 归一化 → PDF 视觉管线) |
| Excel | `.xls`, `.xlsx` | efm (CSV 导出) |
| 图片 | `.png`, `.jpg`, `.jpeg`, `.bmp`, `.gif`, `.tif`, `.tiff`, `.webp`, `.svg`, `.ico` | efm |
| HTML | `.html`, `.htm` | efm |
| 纯文本/Markdown | `.md`, `.mdx`, `.markdown`, `.txt`, `.rst`, `.log` | efm |
| 结构化数据 | `.csv`, `.tsv`, `.json`, `.yaml`, `.yml`, `.xml`, `.toml`, `.ini` | efm |
| 代码 | `.py`, `.java`, `.go`, `.rs`, `.c`, `.cpp`, `.js`, `.ts` 等 | efm |

---

## 2. 系统总览

```
┌─────────────────────────────────────────────────────────────────┐
│                        MarkFileDown 0509                        │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │                    编排层 (Orchestration)                  │  │
│  │  ┌─────────────┐  ┌──────────────┐  ┌─────────────────┐  │  │
│  │  │ run.ps1     │  │ markfiledown │  │ install-workspace│  │  │
│  │  │ (终端入口)   │  │ _runner.py   │  │ -skill.ps1      │  │  │
│  │  └──────┬──────┘  └──────┬───────┘  └─────────────────┘  │  │
│  │         │                 │                               │  │
│  │  ┌──────▼─────────────────▼───────┐                       │  │
│  │  │      发现 → 分发 → 比较 → 提升   │                       │  │
│  │  │    Discover → Dispatch →       │                       │  │
│  │  │    Compare → Promote           │                       │  │
│  │  └──────────────┬─────────────────┘                       │  │
│  └─────────────────┼─────────────────────────────────────────┘  │
│                    │                                            │
│  ┌─────────────────┼─────────────────────────────────────────┐  │
│  │      Engines (引擎层)           │                          │  │
│  │                                 │                          │  │
│  │  ┌──────────────────────────────┴───┐  ┌────────────────┐ │  │
│  │  │  doc-pre-allinone-skill-0508     │  │ efm-multidoc   │ │  │
│  │  │  (文本优先引擎)                   │  │ markdown-bundle│ │  │
│  │  │                                  │  │ (OOXML/视觉)    │ │  │
│  │  │  pipeline_runner.py              │  │ bundle_runner.py│ │  │
│  │  │  runtime/doc_pre/                │  │ pipeline_runner │ │  │
│  │  │    ├── adapters/                 │  │                │ │  │
│  │  │    ├── workers/                  │  │                │ │  │
│  │  │    ├── repair/                   │  │                │ │  │
│  │  │    ├── pipeline.py               │  │                │ │  │
│  │  │    ├── routing.py                │  │                │ │  │
│  │  │    └── models.py                 │  │                │ │  │
│  │  └──────────────────────────────────┘  └────────────────┘ │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 3. 核心设计理念

### 3.1 Text-First 契约

这是整个系统的核心设计原则：

1. **OCR 文字 = 正文主渠道**: 优先使用 `pdfplumber` 提取内嵌文本；当返回空文本（< 20 字符）或乱码（< 60% 可读字符）时，自动使用 `RapidOCR` 回退
2. **截图 = 语义证据**: 页截图、tile、region 仅用于理解页面分区、图示、箭头、callout 和阅读顺序，不作为正文的主替代源
3. **文字优先修复**: `final.md` 先保留原文用词和句意，再用视觉证据修正层级、流程、分区、callout 和关系
4. **冲突处理**: 若视觉和文字冲突，默认保留已抽取文字，把冲突留给 evidence/readback 链路确认

### 3.2 双引擎选主策略

| 文档类型 | 选主规则 |
|---------|---------|
| `.doc/.docx/.ppt/.pptx/.xls/.xlsx` | EFM 完成则优先 EFM（保留 OOXML/table/media 保真度） |
| `.pdf` | 比较 review_status 等级，强的优先；平局时偏好 doc-pre（保留原文措辞） |
| 扩展格式 (图片/HTML/代码/数据) | 直接走 EFM（doc-pre 不处理） |
| 双方都失败 | 不提升任何输出 |

### 3.3 证据链追溯

每个文档处理过程中，所有 block（正文段落、页截图、tile、region、表格）都有唯一的 `raw_block_key`，记录在 `block-catalog.json` 中。`block-md-trace.md` 记录每个 block 是否在最终 Markdown 中出现、以何种状态出现。

### 3.4 静默执行

Runner 不弹出任何 GUI 窗口（File Explorer、浏览器、Office UI）。所有输出写入磁盘，路径打印到 stdout。

---

## 4. 架构分层

### 4.1 层视图

```
┌─────────────────────────────────────────────┐
│  Layer 4: 终端 / Agent 入口                   │
│  run.ps1 / SKILL.md / skill.yaml             │
├─────────────────────────────────────────────┤
│  Layer 3: 编排层 (Orchestration)              │
│  markfiledown_runner.py                      │
│    ├── discover()      → 发现输入文件           │
│    ├── process()       → 分发双引擎              │
│    ├── choose()        → 引擎选主               │
│    ├── promote()       → 提升输出               │
│    └── root_outputs()  → 批量索引和报告          │
├─────────────────────────────────────────────┤
│  Layer 2: 引擎层 (Engines)                    │
│  ┌───────────────────────┐ ┌───────────────┐ │
│  │ doc-pre-allinone      │ │ efm-multidoc  │ │
│  │ (文本优先 + 证据链)     │ │ (OOXML/视觉)  │ │
│  └───────────────────────┘ └───────────────┘ │
├─────────────────────────────────────────────┤
│  Layer 1: 运行时核心 (Runtime Core)            │
│  pdfplumber / pypdfium2 / RapidOCR / PIL      │
│  openpyxl / pywin32 / markitdown             │
└─────────────────────────────────────────────┘
```

### 4.2 关键文件映射

| 文件 | 层级 | 职责 |
|------|------|------|
| `SKILL.md` | L4 | Agent 主入口，定义契约、参数、完成标准 |
| `skill.yaml` | L4 | 技能元数据（触发器、参数 schema、输出定义） |
| `run.ps1` | L4 | PowerShell 终端入口，解析参数并调用 Python runner |
| `markfiledown_runner.py` | L3 | 集成编排器：发现、分发、比较、提升、报告 |
| `bundle-manifest.json` | L4 | 打包清单，列出所有必要文件和核心输出 |
| `requirements.txt` | L1 | Python 依赖声明 |
| `engines/doc-pre-allinone-skill-0508/` | L2 | 文本优先引擎 |
| `engines/efm-multidoc-markdown-bundle/` | L2 | OOXML 提取引擎 |
| `install-workspace-skill.ps1` | L4 | 工作区技能安装器 |

---

## 5. 集成 Runner（编排层）

### 5.1 文件: `markfiledown_runner.py`

**职责**: 批量文档处理的全流程编排

### 5.2 核心流程

```
discover() → [文件列表]
    │
    ▼
for each source file:
    process()
        ├── 运行 doc-pre 引擎
        ├── 运行 efm 引擎（如果适用）
        ├── choose() — 选择更强引擎
        ├── promote() — 提升输出 + 重写链接 + 链接校验
        └── 写 comparison.md + decision.json
    │
    ▼
root_outputs()
    ├── index.md
    ├── batch-manifest.json
    ├── comparison-matrix.md
    └── report.html
```

### 5.3 关键函数

| 函数 | 行号 | 职责 |
|------|------|------|
| `discover()` | 199-225 | 扫描输入路径/文件列表，过滤支持格式 |
| `run()` | 228-241 | 执行子进程，捕获日志 |
| `find_doc_root()` | 244-251 | 在引擎输出目录中找到文档根 |
| `summarize_engine()` | 254-267 | 汇总引擎执行结果 |
| `should_efm()` | 270-275 | 判断 EFM 是否应该运行（格式 + 大小限制） |
| `choose()` | 278-293 | **核心**: 双引擎选主逻辑 |
| `promote()` | 296-322 | 提升选定引擎的 output，重写链接，执行链接校验 |
| `html_report()` | 337-343 | 生成 HTML 报告 |
| `root_outputs()` | 346-356 | 写批量索引和比较矩阵 |
| `process()` | 359-391 | 单文档完整处理流程 |
| `main()` | 394-401 | 入口点 |

### 5.4 选主逻辑 (`choose()`)

```python
def choose(path, doc_pre, efm):
    doc_ok = doc_pre.final_exists
    efm_ok = efm.final_exists

    # 1. Office 文件: EFM 优先（保留 OOXML 保真度）
    if office_format and efm_ok:
        return "efm"

    # 2. 扩展格式: EFM 优先
    if efm_extra_format and efm_ok:
        return "efm"

    # 3. 单方成功
    if doc_ok and not efm_ok: return "doc-pre"
    if efm_ok and not doc_ok: return "efm"

    # 4. 双方成功: 比较 review_status 等级
    if RANK[efm.review_status] > RANK[doc_pre.review_status]:
        return "efm"
    return "doc-pre"  # 平局偏好 doc-pre
```

等级: `pass(4) > skipped(3) > needs-human-review(2) > needs-repair(1) > failed(0)`

### 5.5 链接重写 (`rewrite_markdown_links()`)

提升 `final.md` 和 `source.md` 时，所有相对图片/资产链接会被重写，指向它们在 `engine-results/` 中的真实位置。随后执行 `check_markdown_links()` 验证链接完整性，结果写入 `link-check-report.json`。

---

## 6. Engine 1: doc-pre-allinone（文本优先引擎）

### 6.1 文件: `engines/doc-pre-allinone-skill-0508/`

**版本**: 1.2.1  
**定位**: 文本优先文档重建，block 级证据追踪，可插拔 Agent 回读

### 6.2 架构

```
pipeline_runner.py (CLI 入口)
    │
    ▼
DocumentPipeline (编排)
    │
    ├── LocalFileInputAdapter        → 加载文件，生成 WorkingBundle
    ├── MarkItDownBaselineAdapter    → baseline 文本提取 (Stage 1)
    ├── PDFMultimodalPreparationWorker → 页截图 + tile + region (Stage 2)
    ├── MultimodalReconstructionWorker → LLM 多模态重建 (可选)
    ├── PDFVisualRepairAdapter       → 文本优先 multimodal 修复 (Stage 3)
    ├── BundleEvidenceWriter         → 证据包写入 (Stage 1.5)
    ├── AgentReviewExecutor          → Agent 回读 (Stage 3.5)
    └── LegacyOutputAdapter          → 兼容输出
```

### 6.3 执行阶段

| 阶段 | 名称 | 输入 | 输出 |
|------|------|------|------|
| Stage 1 | Baseline Extraction | 原始文档 | `source.md` (draft_markdown) |
| Stage 1.5 | Block Evidence Merge | draft_markdown + 页资产 | `block-catalog.json`, `block-md-trace.md` |
| Stage 2 | Multimodal Preparation | PDF 文件 | 页截图、tile、region 图片 |
| Stage 3 | Text-First Reconstruction | draft + 页资产 | `final.md` |
| Stage 3.5 | Agent Exec Readback | evidence pack + final.md | `agent-review-response.json` |
| Stage 5 | Integrity Aggregation | 所有阶段产物 | `integrity-metrics.json` |

### 6.4 路由矩阵 (`routing.py`)

```
输入文件扩展名 → 路由决策
├── .xlsx/.xls/.csv → spreadsheet_pipeline (confidence 0.98)
├── .docx          → office_document_pipeline (confidence 0.95)
├── .pptx          → presentation_pipeline (confidence 0.95)
├── .pdf
│   ├── size >= 15MB → complex_visual_pdf_path (confidence 0.60)
│   ├── size >= 5MB  → mixed_pdf_path (confidence 0.70)
│   └── else         → simple_text_pdf_path (confidence 0.65)
└── else            → generic_file_pipeline (confidence 0.50)
```

### 6.5 适配器详解

#### MarkItDownBaselineAdapter

- 优先使用 `MarkItDown` 库提取文本
- 对 DOCX 额外做表格换行修复（从 OOXML 直接解析）
- PDF 的 OCR fallback: `pdfplumber` → `RapidOCR`
- 文本文件格式直接读取（`.md`, `.txt`, `.csv`, `.json` 等）

#### PDF OCR Fallback 触发条件

```python
# 仅当以下情况之一时触发 OCR:
# 1. pdfplumber 返回空文本 (< 20 字符)
# 2. pdfplumber 返回乱码 (< 60% 可读字符)
# 可读字符范围: ASCII printable, CJK, 全角符号, 常用标点
```

### 6.6 Worker 详解

#### PDFMultimodalPreparationWorker

- 使用 `pdfplumber` + `pypdfium2` 渲染页面截图
- 生成 2x2 tile 切片（四分格）
- 生成 region 区域裁剪（主区域 + diagram-focus + 特殊 region）
- OCR fallback: 当 pdfplumber 返回空文本时执行
- 表格提取: explicit (pdfplumber) → implicit (word clustering) → OCR-based

#### BundleEvidenceWriter

写入以下证据文件:
- `evidence/block-catalog.json` — 所有 block 的目录
- `evidence/relation-candidates.md` — 关系候选
- `evidence/reading-order-map.json` — 阅读顺序映射
- `evidence/visual-review-queue.json` — 视觉复核队列
- `evidence/visual-review-summary.md` — 视觉复核摘要
- `evidence/md-input-freeze.json` — 输入冻结快照
- `evidence/freeze-sources.md` — 冻结源列表
- `markdown/block-md-trace.md` — block 追溯
- `markdown/asset-links.md` — 资产链接
- `markdown/agent-review-request.json` — Agent 回读请求

#### AgentReviewExecutor

- **builtin 模式**: 内置规则引擎，检查 visual-review-page 是否在正文中有 anchor
- **external-command 模式**: 执行外部命令，传入 request/response 路径
- **disabled 模式**: 跳过回读
- 生成: `agent-review-report.json`, `agent-review-summary.md`, `back-edge-decision.json`, `integrity-metrics.json`

#### PDFVisualRepairAdapter

- **J90K HVAC 文档**: 专用模板，按预定义章节结构生成 `final.md`
- **通用文档**: 通用文本优先修复，按页面结构输出
- 对演示页/流程页: 提取页面态、动作线索、原文说明
- Mermaid 图生成: 针对信息架构、页面布局、流程图的硬编码模板
- ASCII 图回退: 当 Mermaid 不适用时

#### MultimodalReconstructionWorker

- 使用 Claude API (Sonnet 4.6) 进行多模态重建
- 将页面截图 + OCR 文字发送给 LLM，获取结构化 Markdown
- 替换 draft_markdown 为 AI 重建结果
- **可选功能**: 需要 `ANTHROPIC_API_KEY` 环境变量

### 6.7 数据模型 (`models.py`)

```python
@dataclass
class SourceDocument:          # 源文档元数据
    document_id: str
    filename: str
    media_type: str
    extension: str
    source_path: str | None
    metadata: dict

@dataclass
class RouteDecision:           # 路由决策
    route: str                 # 路由名称
    confidence: float          # 置信度
    rationale: str             # 决策理由

@dataclass
class WorkingBundle:           # 核心传输对象
    bundle_dir: Path
    source_document: SourceDocument
    route_decision: RouteDecision
    draft_markdown: str
    final_markdown: str
    artifacts: list[ArtifactRecord]
    page_records: list[PageRecord]
    table_records: list[TableRecord]
    agent_tasks: list[AgentTask]
    metadata: dict
```

---

## 7. Engine 2: efm-multidoc（OOXML 提取引擎）

### 7.1 文件: `engines/efm-multidoc-markdown-bundle/`

**版本**: 2.2.0  
**定位**: 多格式文档批处理，OOXML 直接提取，视觉优先 PDF/PPT 处理

### 7.2 架构

```
bundle_runner.py (主入口)
    │
    ├── discover_input_files()   → 文件发现
    │
    ├── format routing:
    │   ├── PDF/PPT/PPTX → process_visual_document()
    │   │   └── → run_pdf_pipeline() [在 pipeline_runner.py 中]
    │   ├── DOC/DOCX     → process_word_document()
    │   │   └── → convert_word_to_docx() + export_word_document()
    │   ├── XLS/XLSX     → process_workbook_document()
    │   │   └── → convert_excel_to_xlsx() + export_workbook_csvs()
    │   ├── HTML/Text    → process_text_document()
    │   ├── Data/Code    → process_data_document()
    │   └── Image        → process_image_document()
    │
    └── build_batch_index()      → 批量索引
```

### 7.3 处理阶段

| 阶段 | 名称 | 描述 |
|------|------|------|
| Phase 1 | Discover | 扫描输入，发现支持格式文件 |
| Phase 2 | Normalize | 格式归一化 (doc→docx, ppt→pptx+pdf, xls→xlsx) |
| Phase 3 | Extract | 文本提取 / 视觉处理 / CSV 导出 |
| Phase 4 | OCR & Media Review | OCR fallback + 嵌入图片 OCR |
| Phase 5 | Emit | 输出 source.md, final.md, 批量索引 |

### 7.4 关键处理流程

#### 视觉文档 (PDF/PPT)

1. 归一化为 PDF（PPT 通过 PowerPoint COM 导出）
2. 调用 `run_pdf_pipeline()`（在 `pipeline_runner.py` 中）
3. PDF 页面处理:
   - `pdfplumber` 提取文本
   - `pypdfium2` 渲染截图
   - 低文本密度页触发 OCR fallback
   - 构建 block catalog, relation candidates, visual review queue
4. 生成 `source.md` + `final.md`

#### Word 文档

1. `.doc` 通过 Word COM 归一为 `.docx`
2. 直接从 OOXML (`word/document.xml`) 提取文本块和表格
3. 提取嵌入图片 (`word/media/*`)
4. 对嵌入图片执行 OCR
5. 生成 `source.md` + `final.md` + `word-manifest.json`

#### Excel 文档

1. `.xls` 通过 Excel COM 归一为 `.xlsx`
2. 每个 sheet 导出为 CSV
3. 提取嵌入图片 (`xl/media/*`)
4. 生成 `csv/*.csv` + `source.md` + `final.md` + `workbook-manifest.json`

### 7.5 OCR 区域分类（Phase 4）

EFM 引擎对 OCR 结果自动执行区域分类:

| 分类 | 规则 | 示例 |
|------|------|------|
| 正文 | 行长 ≥ 15 字符，含规则说明用语 | "用户通过...", "开启后..." |
| UI 噪音 | 状态栏时间、开关状态、占位标记 | "21:05", "ON", "icon" |
| 不确定 | 短文本块 (4-8 字符) | 需要人工判定 |

生成 `evidence/ocr-review.html` 交互式复核报告，用户可切换分类并导出决策 JSON。

### 7.6 pipeline_runner.py 核心函数

| 函数 | 职责 |
|------|------|
| `build_page_data()` | 处理 PDF，生成页面数据（文本 + 截图 + OCR） |
| `build_block_catalog()` | 构建 block 目录 |
| `build_relation_candidates()` | 构建关系候选 |
| `build_visual_review_queue()` | 构建视觉复核队列 |
| `render_page_body()` | 渲染页面正文 Markdown |
| `generate_source_markdown()` | 生成 source.md |
| `generate_final_markdown()` | 生成 final.md（含领域模板） |
| `run_pdf_pipeline()` | PDF 完整处理流程 |
| `_classify_page_approach()` | 自适应 OCR 路由决策 |
| `_rebuild_ocr_to_markdown()` | 基于区域的 OCR → Markdown 重建 |
| `_detect_page_zone()` | UE 文档三区域检测（顶部/截图/内容） |

---

## 8. 数据模型

### 8.1 WorkingBundle (doc-pre)

核心传输对象，贯穿 doc-pre 引擎所有阶段:

```
WorkingBundle
├── source_document: SourceDocument
│   ├── document_id    # "stem-sha1hash"
│   ├── filename       # 原始文件名
│   ├── media_type     # MIME 类型
│   ├── extension      # 扩展名
│   └── metadata       # {size_bytes, ...}
├── route_decision: RouteDecision
│   ├── route          # 路由名称
│   ├── confidence     # 置信度
│   └── rationale      # 理由
├── draft_markdown: str      # source.md 内容
├── final_markdown: str      # final.md 内容
├── page_records: list[PageRecord]
│   ├── page_number
│   ├── screenshot_path
│   ├── tile_paths
│   ├── region_paths
│   ├── needs_visual_review
│   ├── diagram_candidate
│   ├── text_length / image_count / char_count
│   └── metadata: {raw_text, page_tables, ...}
├── table_records: list[TableRecord]
├── agent_tasks: list[AgentTask]
└── metadata: dict
```

### 8.2 批量决策 (集成 Runner)

每个文档的决策记录写入 `markfiledown-decision.json`:

```json
{
  "source_name": "example.pdf",
  "source_path": "/path/to/example.pdf",
  "source_format": "pdf",
  "output_root": "/output/doc-id/",
  "primary_engine": "doc-pre",
  "decision_reason": "doc-pre review status pass ranked at least as strong as EFM",
  "promoted": {
    "source_path": "...",
    "final_path": "...",
    "link_check_report_path": "...",
    "broken_link_count": "0"
  },
  "engines": {
    "doc-pre": { "status": "completed", "review_status": "pass", ... },
    "efm": { "status": "completed", "review_status": "pass", ... }
  }
}
```

---

## 9. 路由与决策机制

### 9.1 doc-pre 路由 (`routing.py`)

基于文件扩展名和大小的静态路由:

```
                   ┌─── .xlsx/.xls/.csv ──→ spreadsheet_pipeline
                   ├─── .docx ────────────→ office_document_pipeline
输入文件扩展名 ─────┼─── .pptx ────────────→ presentation_pipeline
                   ├─── .pdf (≥15MB) ────→ complex_visual_pdf_path
                   ├─── .pdf (≥5MB) ─────→ mixed_pdf_path
                   ├─── .pdf (<5MB) ─────→ simple_text_pdf_path
                   └─── else ─────────────→ generic_file_pipeline
```

### 9.2 EFM 路由 (`bundle_runner.py`)

基于文件扩展名的直接分发:

```
                   ┌─── .pdf/.ppt/.pptx ─→ process_visual_document()
                   ├─── .doc/.docx ──────→ process_word_document()
输入文件扩展名 ─────┼─── .xls/.xlsx ──────→ process_workbook_document()
                   ├─── .html/.md/.txt ──→ process_text_document()
                   ├─── .csv/.json/.py ──→ process_data_document()
                   └─── .png/.jpg/... ───→ process_image_document()
```

### 9.3 集成 Runner 选主 (`choose()`)

```
                  ┌─── Office 格式 + EFM 成功 ───→ efm
                  ├─── 扩展格式 + EFM 成功 ───────→ efm
                  ├─── 仅 doc-pre 成功 ───────────→ doc-pre
                  ├─── 仅 EFM 成功 ───────────────→ efm
双引擎结果 ───────┼─── 都成功: RANK[efm] > RANK[doc-pre] → efm
                  ├─── 都成功: 平局 ───────────────→ doc-pre (偏好原文)
                  └─── 都失败 ────────────────────→ none
```

### 9.4 自适应 OCR 路由 (`_classify_page_approach()`)

```
页面文本
├── len ≥ 20 且可读率 ≥ 60% ───→ text-first (跳过 OCR)
├── len ≥ 20 但可读率 < 60% ───→ ocr-rebuild (乱码回退)
├── len < 20 且 enable_ocr ────→ ocr-rebuild (空文本回退)
└── len < 20 且 !enable_ocr ───→ text-first (无能为力)
```

---

## 10. 输出目录结构

### 10.1 集成 Runner 输出

```
<outputRoot>/
├── index.md                      # 批量入口索引
├── batch-manifest.json           # 处理清单
├── comparison-matrix.md          # 工程比较矩阵
├── report.html                   # HTML 报告
│
└── <doc-id>/                     # 每文档独立输出
    ├── source.md                 # 提升的基线文本
    ├── final.md                  # 提升的修复版 Markdown（含决策头）
    ├── comparison.md             # 引擎比较
    ├── markfiledown-decision.json # 决策记录
    ├── link-check-report.json    # 链接校验报告
    │
    ├── logs/
    │   ├── doc-pre.log           # doc-pre 引擎日志
    │   └── efm.log               # EFM 引擎日志
    │
    └── engine-results/
        ├── doc-pre/              # doc-pre 原始输出
        │   ├── source.md
        │   ├── final.md
        │   ├── artifacts/
        │   │   ├── pages/        # 页截图
        │   │   ├── regions/      # 区域裁剪
        │   │   └── tables/       # 表格 CSV
        │   ├── evidence/         # 证据包
        │   │   ├── block-catalog.json
        │   │   ├── relation-candidates.md
        │   │   ├── reading-order-map.json
        │   │   └── ...
        │   ├── markdown/         # Markdown 侧车
        │   │   ├── block-md-trace.md
        │   │   ├── agent-review-*.json
        │   │   └── ...
        │   ├── manifest.json
        │   └── integrity-metrics.json
        │
        └── efm/                  # EFM 原始输出
            ├── source.md
            ├── final.md
            ├── artifacts/
            │   ├── pages/
            │   └── embedded-media/
            ├── csv/              # Excel CSV 导出
            ├── evidence/
            │   ├── ocr-review.html
            │   └── word-manifest.json / workbook-manifest.json
            ├── markdown/
            └── .pipeline-state.json
```

### 10.2 关键输出文件说明

| 文件 | 含义 |
|------|------|
| `index.md` | 批量入口，列出所有文档的处理状态 |
| `batch-manifest.json` | 结构化处理清单，含时间戳 |
| `comparison-matrix.md` | 工程视角的引擎对比矩阵 |
| `report.html` |  stakeholder 友好的 HTML 报告 |
| `final.md` | 最终提升的 Markdown（包含引擎决策表头 + 正文） |
| `source.md` | 最终提升的基线文本（链接已重写） |
| `comparison.md` | 单文档引擎比较，含实用优势观察 |
| `markfiledown-decision.json` | 结构化决策记录 |
| `link-check-report.json` | 链接校验报告（broken_link_count 应为 0） |

---

## 11. 接口与调用协议

### 11.1 主入口: `/markfiledown.pipeline`

```markdown
/markfiledown.pipeline
Input path: @docs
Output root: output/markfiledown-0509
Format: auto
Style: technical
Agent review: true
OCR: true
Recurse: true
```

### 11.2 终端入口: `run.ps1`

```powershell
.\mark-file-down\run.ps1 `
  -InputPath ".\docs" `
  -OutputRoot ".\output\markfiledown-0509" `
  -SourceFormat auto `
  -MarkdownStyle technical `
  -EnableAgentReviewValidation $true `
  -IncludeAssetLinks $true `
  -EnableOcr $true `
  -Recurse $true `
  -MaxEfmPdfSizeMb 80 `
  -PythonExe ".\.venv\Scripts\python.exe"
```

### 11.3 参数表

| 参数 | 默认值 | 可选值 | 说明 |
|------|--------|--------|------|
| `InputPath` | 无 | 路径 | 单文件或目录输入 |
| `InputFile` | 空数组 | 路径数组 | 显式文件列表（可重复） |
| `OutputRoot` | **必填** | 路径 | 输出根目录 |
| `SourceFormat` | `auto` | auto/pdf/doc/docx/ppt/pptx/xls/xlsx/csv | 格式过滤器 |
| `MarkdownStyle` | `technical` | technical/narrative/audit-friendly | Markdown 风格 |
| `EnableAgentReviewValidation` | `true` | bool | Agent 回读校验 |
| `IncludeAssetLinks` | `true` | bool | 资产链接 |
| `EnableOcr` | `true` | bool | OCR 回退 |
| `Recurse` | `true` | bool | 递归扫描 |
| `MaxEfmPdfSizeMb` | 80 | int | EFM 处理 PDF 大小上限 |
| `PythonExe` | auto | 路径 | Python 可执行文件 |

### 11.4 Python Runner 参数

`markfiledown_runner.py` 接受的参数（通过 `run.ps1` 转发）:

```
--input-path PATH
--input-file PATH (可多次)
--output-root PATH (必填)
--source-format {auto,pdf,doc,...}
--markdown-style {technical,narrative,audit-friendly}
--agent-review-validation {on,off}
--asset-links {on,off}
--ocr {on,off}
--recurse {on,off}
--max-efm-pdf-size-mb N
--python-exe PATH
```

### 11.5 子引擎参数转发

集成 Runner 调用子引擎时，转发以下参数:

**doc-pre**:
```
--input-file <source>
--output-root <doc-pre-dir>
--source-format <format>
--markdown-style <style>
--agent-review-validation <on/off>
--asset-links <on/off>
--agent-exec-mode builtin
--agent-command ""
--use-plugins off
```

**efm**:
```
--input-path <source>
--output-root <efm-dir>
--source-format <format>
--markdown-style <style>
--pdf-agent-validation <on/off>
--asset-links <on/off>
--ocr <on/off>
--recurse off
```

---

## 12. 关键流程时序

### 12.1 单文档处理时序

```
User / Agent
    │
    ▼
┌─────────────────┐
│    run.ps1      │  解析参数，发现 Python，安装依赖
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────┐
│   markfiledown_runner.py        │
│   main()                        │
└────────┬────────────────────────┘
         │
    discover(args)                 扫描输入，过滤支持格式
         │
         ▼
    for each source file:
         │
         ▼
    process(source, output_root, args, skill_root)
         │
         ├── run(doc-pre pipeline_runner.py) ──────────────────┐
         │                                                      │
         │   ┌──────────────────────────────────────────────┐  │
         │   │  doc-pre Engine                               │  │
         │   │  1. LocalFileInputAdapter.load()              │  │
         │   │  2. MarkItDownBaselineAdapter.extract()       │  │
         │   │  3. PDFMultimodalPreparationWorker.prepare()  │  │
         │   │  4. MultimodalReconstructionWorker.reconstruct()│
         │   │  5. PDFVisualRepairAdapter.repair()           │  │
         │   │  6. BundleEvidenceWriter.write()              │  │
         │   │  7. AgentReviewExecutor.execute()             │  │
         │   │  8. LegacyOutputAdapter.write()               │  │
         │   └──────────────────────────────────────────────┘  │
         │                                                      │
         ├── should_efm(source, limit_mb)                       │
         │   └── if True:                                       │
         │       run(efm bundle_runner.py) ─────────────────────┤
         │                                                      │
         │   ┌──────────────────────────────────────────────┐  │
         │   │  EFM Engine                                 │  │
         │   │  1. format routing                          │  │
         │   │  2. normalize (COM if needed)                │  │
         │   │  3. extract (text/visual/csv)                │  │
         │   │  4. OCR + media review                      │  │
         │   │  5. emit source.md + final.md               │  │
         │   └──────────────────────────────────────────────┘  │
         │                                                      │
         ├── choose(source, doc_pre, efm)                       │
         │   └── 选择更强引擎                                    │
         │                                                      │
         ├── promote(doc_dir, source, primary, ...)              │
         │   ├── 重写 Markdown 链接                              │
         │   ├── 写 source.md + final.md                         │
         │   └── 执行链接校验                                    │
         │                                                      │
         ├── write_doc_comparison(...)                          │
         │                                                      │
         └── write decision.json                                │
                                                                │
         ▼                                                      │
    root_outputs(output_root, items)                            │
    ├── index.md                                                │
    ├── batch-manifest.json                                     │
    ├── comparison-matrix.md                                    │
    └── report.html                                             │
```

### 12.2 doc-pre Pipeline 内部时序

```
DocumentPipeline.run_local()
    │
    ├─→ input_adapter.load()
    │     └── SourceDocument + RouteDecision → WorkingBundle
    │
    ├─→ _seed_agent_tasks()
    │     └── 根据路由添加 agent 任务
    │
    ├─→ baseline_adapter.extract()
    │     ├── MarkItDown (优先)
    │     ├── DOCX table line-break restoration
    │     └── PDF OCR fallback (pdfplumber → RapidOCR)
    │     └── → draft_markdown
    │
    ├─→ _run_multimodal_preparation()
    │     └── PDFMultimodalPreparationWorker.prepare()
    │         ├── 页截图渲染 (pypdfium2)
    │         ├── 2x2 tile 切片
    │         ├── region 区域裁剪
    │         ├── 文本提取 (pdfplumber)
    │         ├── OCR fallback
    │         └── 表格提取 (explicit → implicit → OCR)
    │
    ├─→ _run_multimodal_reconstruction() [可选]
    │     └── MultimodalReconstructionWorker.reconstruct()
    │         └── Claude API 多模态重建
    │
    ├─→ _build_final_markdown()
    │     └── PDFVisualRepairAdapter.repair()
    │         ├── J90K HVAC 专用模板
    │         └── 通用文本优先模板
    │
    ├─→ _write_bundle_outputs()
    │     ├── source.md + final.md
    │     ├── evidence writer → block-catalog, relation-candidates, ...
    │     └── agent review executor → review report, integrity metrics
    │
    └─→ output_adapter.write()
          └── 兼容输出 (legacy markdown, CSV exports)
```

---

## 13. 多模态修复契约

### 13.1 纯图片 PDF 自动修复

当 EFM 管线检测到 PDF 为纯图片格式（pdfplumber 每页平均提取字符数 < 50）:

1. 自动写入 `multimodal-repair-brief.json` 和 `multimodal-repair-summary.md`
2. brief 包含: 页面截图路径、OCR source.md 路径、修复规则
3. **Agent 在管线结束后必须自动检测并执行修复**:
   - 读取 brief + 截图 + source.md
   - 以 OCR 文本为内容主干，截图为结构参考
   - 修复 final.md 的 Markdown 格式（标题、表格、列表、图片引用）
   - **不得改写、意译或编造内容**

### 13.2 控制标志

`--multimodal-repair`:
- `auto` (默认): 纯图片 PDF 时写入 brief
- `on`: 始终写入 brief
- `off`: 不写入

### 13.3 Agent 修复规则

```
OCR text = 内容主干
screenshots = 结构参考

Do NOT:
- rewrite / paraphrase / invent content
- replace readable OCR text with screenshot-only paraphrases

DO:
- use screenshots for heading hierarchy, table structure,
  paragraph grouping, list relationships, annotation layout
- repair final.md with proper Markdown formatting
- preserve all OCR text verbatim
```

---

## 14. 依赖关系

### 14.1 Python 依赖 (`requirements.txt`)

```
markitdown[pdf,docx,pptx,xlsx,xls]   # 通用文档转 Markdown
pdfplumber                           # PDF 文本和表格提取
pypdfium2                            # PDF 页面渲染
pypdf                                # PDF 元数据读取
Pillow                               # 图片处理
rapidocr-onnxruntime                 # OCR 引擎
openpyxl                             # Excel 读写
pywin32                              # Windows Office COM 自动化
```

### 14.2 外部依赖

| 依赖 | 用途 | 必需性 |
|------|------|--------|
| Python 3.x | 运行环境 | **必需** |
| Microsoft Office (Windows) | doc/ppt/xls COM 归一化 | 可选（仅影响旧格式） |
| ANTHROPIC_API_KEY | LLM 多模态重建 | 可选（仅 MultimodalReconstructionWorker） |

### 14.3 明确不依赖

- LibreOffice
- Pandoc
- Tesseract

---

## 15. 设计决策记录

### 15.1 为什么采用双引擎架构？

**决策**: 每个文档同时经过 doc-pre 和 efm 两个引擎，然后自动选主。

**理由**:
- doc-pre 擅长 PDF 文本优先提取和证据链追溯
- efm 擅长 OOXML 直接提取（保留表格换行、嵌入图片、工作簿结构）
- 单一引擎无法在所有格式上都达到最佳效果
- 双引擎 + 选主提供 per-document 级别的 fallback 保障

**代价**: 处理时间是单引擎的 ~2x，但质量提升显著。

### 15.2 为什么 Text-First 而非 Visual-First？

**决策**: 默认契约是 OCR 文字为正文主渠道，截图仅用于修正结构。

**理由**:
- 截图理解有主观性，不同 Agent 对同一截图的理解可能不同
- OCR 文字是客观提取，适合做 content backbone
- 视觉证据应用于修正 heading hierarchy、flow direction、zone归属等 OCR 无法稳定表达的结构语义
- 冲突时保留文字，把冲突留给 evidence/readback 链路

### 15.3 为什么证据链追溯是必需的？

**决策**: 每个 block 都有 raw_block_key，记录在 block-catalog.json 中。

**理由**:
- 便于审计: 知道 final.md 中每段文字来自哪个 block
- 便于调试: 当内容有误时，可以追溯到原始 block
- 便于增量更新: 知道哪些 block 需要重新处理

### 15.4 为什么使用 COM 而非 LibreOffice？

**决策**: doc/ppt/xls 归一化使用 Microsoft Office COM，而非 LibreOffice。

**理由**:
- 目标环境是 Windows (win32 平台)
- Office COM 提供更高的渲染保真度
- 不引入额外的 LibreOffice 安装依赖

### 15.5 为什么 Runner 是静默执行？

**决策**: 不弹出任何 GUI 窗口。

**理由**:
- 适合 CI/CD 和批量处理
- 适合 headless 环境
- 用户需要预览时可以手动打开 report.html

---

## 16. 已知问题与修复历史

### 16.1 OCR 渲染挂起问题

| 项目 | 详情 |
|------|------|
| **现象** | 在 `设置UE.pdf`（超大页、图片型 PDF）上长时间停留在 `in-progress` |
| **根因** | 内置 OCR 路径对超大页使用固定高分辨率整页渲染，导致内存溢出或挂起 |
| **影响范围** | `MarkItDownBaselineAdapter.extract()` 的 PDF OCR fallback; `PDFMultimodalPreparationWorker` 的 OCR 路径 |
| **修复方案** | 为 OCR 渲染增加限宽/限像素约束: baseline OCR 按页宽动态降低渲染 DPI，并对生成图片再限像素 |
| **回归验证** | baseline OCR 从挂起恢复为 53 秒完成并返回 4290 字文本 |
| **涉及文件** | `utils.py`, `markitdown_adapter.py`, `pdf_multimodal.py` |

---

## 17. 扩展指南

### 17.1 添加新格式支持

1. 在 `markfiledown_runner.py` 的 `SUPPORTED` 和 `EFM_SUPPORTED` 集合中添加扩展名
2. 在 `efm-multidoc/bundle_runner.py` 中添加对应的处理函数
3. 在 `bundle_runner.py` 的 `main()` 中添加 format routing

### 17.2 添加新的 Agent 回读后端

1. 实现外部命令脚本，接受 `{request}` 和 `{response}` 路径参数
2. 设置环境变量 `DOC_PRE_AGENT_COMMAND` 或使用 `--agent-exec-mode external-command --agent-command "..."`
3. 脚本必须读取 request JSON，执行审查，写入 response JSON

### 17.3 自定义 Mermaid 模板

在 `PDFVisualRepairAdapter` 中添加新的 Mermaid 生成方法:

```python
def _my_custom_mermaid(self) -> list[str]:
    return [
        "```mermaid",
        "flowchart LR",
        "  A --> B",
        "```",
    ]
```

然后在 `_page_macro_mermaid()` 中添加检测条件调用。

### 17.4 自定义文档模板（类似 J90K HVAC）

1. 在 `utils.py` 中添加文档检测函数 `is_my_document_type()`
2. 在 `PDFVisualRepairAdapter._is_j90k_document()` 旁添加新的检测逻辑
3. 在 `_build_text_first_repair()` 中添加新的 profile 分支
4. 实现对应的 `_build_my_profile_repair()` 方法

### 17.5 Workspace 技能安装

```powershell
.\mark-file-down\install-workspace-skill.ps1 `
  -ProjectRoot "C:\path\to\project" `
  -Force
```

这会在目标项目的 `.github/skills/markfiledown-0509/` 下安装 SKILL.md wrapper。

---

## 附录 A: 文件清单

### 根层 (mark-file-down/)

| 文件 | 类型 | 说明 |
|------|------|------|
| `SKILL.md` | Skill | Agent 主入口定义 |
| `skill.yaml` | Config | 技能元数据（触发器、参数 schema） |
| `bundle-manifest.json` | Config | 打包清单 |
| `run.ps1` | Script | PowerShell 终端入口 |
| `markfiledown_runner.py` | Code | 集成编排器 |
| `requirements.txt` | Config | Python 依赖 |
| `install-workspace-skill.ps1` | Script | 工作区技能安装器 |
| `README.md` | Doc | 使用说明 |
| `doc-preprocess-pipeline.md` | Doc | Step 0 预处理流程说明 |
| `issue-history.md` | Doc | 问题修复历史 |
| `multimodal_repair.ps1` | Script | 多模态修复辅助脚本 |

### Engine 1: doc-pre-allinone-skill-0508

| 文件 | 类型 | 说明 |
|------|------|------|
| `SKILL.md` | Skill | 引擎技能定义 |
| `skill.yaml` | Config | 引擎元数据 |
| `pipeline_runner.py` | Code | CLI 入口 |
| `run.ps1` | Script | 终端验证适配器 |
| `requirements.txt` | Config | 依赖 |
| `runtime/doc_pre/__init__.py` | Code | 包初始化 |
| `runtime/doc_pre/__main__.py` | Code | 模块入口 |
| `runtime/doc_pre/__about__.py` | Code | 版本信息 |
| `runtime/doc_pre/pipeline.py` | Code | 管线编排 |
| `runtime/doc_pre/routing.py` | Code | 路由决策 |
| `runtime/doc_pre/models.py` | Code | 数据模型 |
| `runtime/doc_pre/utils.py` | Code | 工具函数 |
| `runtime/doc_pre/adapters/markitdown_adapter.py` | Code | Baseline 文本提取 |
| `runtime/doc_pre/adapters/local_file.py` | Code | 文件输入适配器 |
| `runtime/doc_pre/adapters/legacy_output.py` | Code | 兼容输出适配器 |
| `runtime/doc_pre/workers/pdf_multimodal.py` | Code | PDF 多模态准备 |
| `runtime/doc_pre/workers/evidence_writer.py` | Code | 证据包写入 |
| `runtime/doc_pre/workers/pdf_agent_readback.py` | Code | Agent 回读执行 |
| `runtime/doc_pre/workers/multimodal_reconstruction.py` | Code | LLM 多模态重建 |
| `runtime/doc_pre/repair/pdf_visual_repair.py` | Code | PDF 视觉修复 |

### Engine 2: efm-multidoc-markdown-bundle

| 文件 | 类型 | 说明 |
|------|------|------|
| `SKILL.md` | Skill | 引擎技能定义 |
| `skill.yaml` | Config | 引擎元数据 |
| `bundle-manifest.json` | Config | 打包清单 |
| `bundle_runner.py` | Code | 主入口，格式路由 |
| `pipeline_runner.py` | Code | PDF 管线实现 |
| `run.ps1` | Script | 终端入口 |
| `requirements.txt` | Config | 依赖 |
| `README.md` | Doc | 使用说明 |
| `TASKS.md` | Doc | 任务清单 |

---

## 附录 B: 关键配置常量

### OCR 路由阈值

| 常量 | 值 | 用途 |
|------|-----|------|
| `_OCR_TRIGGER_CHARS` | 20 | 低于此值考虑 OCR |
| `_GARBLED_RATIO_THRESHOLD` | 0.60 | 可读率低于此值视为乱码 |
| `OCR_RENDER_DPI` | 96 | OCR 渲染默认 DPI |
| `OCR_MAX_WIDTH` | 2200 | OCR 最大宽度（像素） |
| `OCR_MAX_PIXELS` | 20,000,000 | OCR 最大像素数 |

### EFM PDF 大小限制

| 常量 | 值 | 用途 |
|------|-----|------|
| `maxEfmPdfSizeMb` | 80 | 超过此大小的 PDF 跳过 EFM |

### doc-pre 路由大小阈值

| 条件 | 路由 | 置信度 |
|------|------|--------|
| ≥ 15MB | complex_visual_pdf_path | 0.60 |
| ≥ 5MB | mixed_pdf_path | 0.70 |
| < 5MB | simple_text_pdf_path | 0.65 |

---

## 附录 C: Claude Code 集成说明

### C.1 Skill 注册

MarkFileDown 0509 通过以下文件注册为 Claude Code skill:

1. `SKILL.md` — 位于项目根目录或 `.github/skills/` 下
2. `skill.yaml` — 提供结构化元数据

### C.2 触发方式

Agent 通过 `/markfiledown.pipeline` 触发 skill，或者通过自然语言识别 trigger keywords（如 "PDF转markdown", "文档转MD" 等）。

### C.3 工作区集成

使用 `install-workspace-skill.ps1` 可以将 skill 安装到目标项目的 `.github/skills/markfiledown-0509/` 目录，使其作为 workspace-native skill 被自动发现。
