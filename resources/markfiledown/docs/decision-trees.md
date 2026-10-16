# MarkFileDown 0509 — 完整决策树

> **版本**: v1.1.0  
> **最后更新**: 2026-06-03  
> **覆盖范围**: 输入发现 → 格式路由 → 纯图片 PDF 检测 → 引擎选主 → OCR 路由 → 链接校验 → 多模态修复 → 分块处理

---

## 决策树 1: 输入发现与格式过滤

```
用户提供输入
    │
    ├── 是单个文件? ──Yes──→ 直接使用
    │
    └── No (目录)
         │
         ├── --recurse=on? ──Yes──→ 递归扫描 (**/*)
         │
         └── No ──→ 仅扫描顶层 (*)
                    │
                    ▼
            过滤规则:
              ├── 扩展名不在 SUPPORTED 集合中 → ✗ 排除
              ├── 文件名以 "~$" 开头 (Office 临时文件) → ✗ 排除
              ├── 路径包含 excluded 部分 (.git, outputs, __pycache__...) → ✗ 排除
              └── --source-format != auto → 只保留匹配该扩展名的文件
                    │
                    ▼
            有文件吗?
              ├── No → ✗ 抛出 FileNotFoundError
              └── Yes → 去重 (SHA1 前8位 + 路径) → 进入处理队列
```

---

## 决策树 2: 双引擎路由 (集成 Runner)

```
对队列中每个源文件 source:
    │
    ▼
    源文件扩展名是?
    │
    ├── 图片 / HTML / 文本 / 数据 / 代码 (.png/.md/.json/.py/...)
    │   └── doc-pre: ✗ 直接跳过 (记录 "extended format, handled by EFM")
    │       EFM: ✓ 进入 EFM 处理
    │
    ├── PDF (.pdf)
    │   └── doc-pre: ✓ 始终执行
    │       │
    │       ├── 纯图片检测 (avg chars/page < 50)?
    │       │   ├── Yes → pure_image_pdf_path
    │       │   │   └── 页面尺寸 > 阈值? → 自适应分块 (tile-based)
    │       │   └── No → 继续文件大小判断
    │       │
    │       ├── 文件大小 ≥ 15 MB → complex_visual_pdf_path
    │       ├── 文件大小 ≥ 5 MB  → mixed_pdf_path
    │       └── 文件大小 < 5 MB  → simple_text_pdf_path
    │       │
    │       EFM: 取决于 should_efm():
    │           ├── 文件大小 > --max-efm-pdf-size-mb (默认80MB)?
    │           │   ├── Yes → ✗ 跳过 (记录 "PDF too large, EFM skipped")
    │           │   └── No → ✓ 执行
    │           └── 扩展名在 EFM_SUPPORTED 中? (PDF 在集合中)
    │               └── Yes → 继续检查大小
    │
    ├── Office (.doc/.docx/.ppt/.pptx/.xls/.xlsx)
    │   └── doc-pre: ✓ 始终执行 (通用文本提取)
    │       EFM: ✓ 始终执行 (OOXML 直接提取)
    │
    └── 其他不支持的格式 → ✗ 报错
```

---

## 决策树 3: doc-pre 引擎路由 (routing.py)

```
输入文件扩展名?
    │
    ├── .xlsx / .xls / .csv
    │   └── route: spreadsheet_pipeline (confidence=0.98)
    │       └── 产物: CSV 导出 + manifest
    │
    ├── .docx
    │   └── route: office_document_pipeline (confidence=0.95)
    │       └── 产物: OOXML 文本提取 + evidence
    │
    ├── .pptx
    │   └── route: presentation_pipeline (confidence=0.95)
    │       └── 产物: 幻灯片提取 + 嵌入图片
    │
    ├── .pdf
    │   └── 纯图片检测 (pdfplumber + pypdfium2)
    │       │
    │       ├── pdfplumber 打开失败? → 回退到文件大小判断
    │       │
    │       ├── 平均每页 pdfplumber 字符数 ≥ 50?
    │       │   └── → 不是纯图片 → 回退到文件大小判断
    │       │
    │       └── 平均每页字符数 < 50 (疑似纯图片)
    │           │
    │           ├── 渲染前 3 页，检查尺寸
    │           │   ├── 任一页 > 2200px 宽 或 > 20MP?
    │           │   │   └── → pure_image_pdf_path (confidence=0.75)
    │           │   │       rationale="纯图片PDF + 超大页面 → 分块处理"
    │           │   └── 所有页面在阈值内?
    │           │       └── → pure_image_pdf_path (confidence=0.80)
    │           │           rationale="纯图片PDF → 多模态路径"
    │           │
    │       └── 回退: 文件大小判断
    │           ├── ≥ 15 MB → route: complex_visual_pdf_path (confidence=0.60)
    │           ├── ≥ 5 MB  → route: mixed_pdf_path (confidence=0.70)
    │           └── < 5 MB  → route: simple_text_pdf_path (confidence=0.65)
    │
    └── 未知扩展名
        └── route: generic_file_pipeline (confidence=0.50)
```

---

## 决策树 3.5: 纯图片 PDF 分块处理 (pdf_multimodal.py)

```
PDFMultimodalPreparationWorker._compute_tile_grid_if_needed()
    │
    ▼
    页面尺寸 (渲染后 px)?
        │
        ├── 宽 > 2200px 或 高 > 3000px 或 像素 > 6MP?
        │   └── Yes → calculate_tile_grid(width, height)
        │       │
        │       │ 计算需要几行几列:
        │       │   cols_needed = ceil(width / 2200), 限制 1..4
        │       │   rows_needed = ceil(height / 3000), 限制 1..4
        │       │   如像素仍超标 → 增加行/列直到满足
        │       │
        │       └── _render_adaptive_tiles(grid=(rows, cols))
        │           │
        │           ├── 渲染全分辨率页面图 (scale=1.0)
        │           ├── 按 grid 均匀裁剪:
        │           │   ├── tile_width = width // cols
        │           │   └── tile_height = height // rows
        │           ├── 最后一行/列撑满剩余
        │           └── 命名: page-N-tile-r{row}c{col}.png
        │               (行优先: r0c0 → r0c1 → r1c0 → r1c1 → ...)
        │
        └── No → 无需分块
            ├── pure_image_pdf_path → 单图送多模态
            └── 其他路线 → 固定 2x2 tiles (原有逻辑)

── 分块重建与拼接 (multimodal_reconstruction.py) ──
    │
    对每个 tile:
        │
        ├── 发送两张图给 LLM:
        │   ├── 图1: 全页缩略图 (全局上下文)
        │   │   └── 用于理解整体结构: 流程图、页面跳转链路、信息架构
        │   └── 图2: tile 高清图 (当前区域细节)
        │       └── 用于提取该区域的详细文本内容
        │
        └── Prompt 指示:
            ├── "第一张图是全局参考，第二张图是你应重点分析的部分"
            ├── "根据全局图理解整体结构，从高清图提取详细内容"
            └── "如果 tile 内容属于更大结构的一部分，保留上下文关系"
    │
    ▼
    _stitch_tile_markdown(tile_texts, rows, cols)
        │
        ├── 行优先顺序拼接 (r0c0, r0c1, ..., r1c0, ...)
        ├── 去重: 后一块开头与前一块末尾 >80% 重叠? → 跳过重复
        ├── 分隔符: 两块都是标题开头? → 插入 "---"
        └── 输出: 完整页面 Markdown
```

---

## 决策树 4: doc-pre 文本提取 (Baseline Adapter)

```
MarkItDownBaselineAdapter.extract()
    │
    ▼
    能导入 MarkItDown 库?
        ├── Yes → 执行 MarkItDown.convert()
        │   └── 返回 markdown 非空?
        │       ├── Yes
        │       │   └── 是 DOCX? ──Yes──→ 执行表格换行修复 (OOXML 直接解析)
        │       │   └── No → 直接返回 markdown
        │       └── No (空 markdown) → 进入 Fallback
        │
        └── No (导入失败) 或 执行异常
            └── 进入 Fallback

Fallback:
    │
    ├── 是 PDF (.pdf)?
    │   └── pdfplumber 可用?
    │       ├── Yes → 执行 PDF OCR 提取
    │       │   └── 对每页:
    │       │       ├── pdfplumber.extract_text() 有文本?
    │       │       │   ├── Yes → 使用提取文本，结构化 Markdown
    │       │       │   └── No → RapidOCR 可用?
    │       │       │       ├── Yes → 渲染页面 → OCR → 结构化 Markdown
    │       │       │       └── No → "> 该页无可用文本"
    │       │       └── 最终返回: "# filename\n\n## Page N\n..."
    │       └── No → 进入文本文件 Fallback
    │
    └── 不是 PDF → 文本文件直接读取?
        ├── .md/.markdown → 直接返回
        ├── .csv → 包裹在 ```csv 代码块中
        ├── 其他文本格式 → "# filename\n\n{内容}"
        └── 都不匹配 → Placeholder Markdown
```

---

## 决策树 5: 自适应 OCR 路由 (EFM pipeline_runner.py)

```
_classify_page_approach(cleaned_text, page_image_count, enable_ocr)
    │
    ▼
    len(cleaned_text) ≥ 20?
        ├── Yes
        │   └── 文本可读率 ≥ 60%? (_is_text_garbled)
        │       ├── Yes → text-first ✓ (跳过 OCR)
        │       └── No → 乱码，需要 OCR → 继续
        │
        └── No (文本 < 20 字符，空文本)
            └── 需要 OCR → 继续
                │
                ▼
            enable_ocr?
                ├── Yes → ocr-rebuild ✓
                └── No → text-first (无能为力)

── 可读率判定 (_is_text_garbled) ──
    │
    遍历每个非空格字符:
        ├── 在可读 Unicode 范围内? (ASCII printable, CJK, 全角符号)
        │   └── Yes → readable++
        │   └── No (replacement char, private-use, control char) → unreadable
        │
    readable / total < 0.60?
        ├── Yes → 乱码，触发 OCR
        └── No → 正常，跳过 OCR
```

---

## 决策树 6: PDF 页面处理 (EFM pipeline_runner.py)

```
build_page_data(pdf_path)
    │
    对每页:
    │
    ├── pdfplumber.extract_text() → cleaned_text
    ├── pdfplumber.extract_tables() → tables
    ├── pdfplumber.images → image_count
    ├── pypdfium2.render() → 页面截图
    │
    ▼
    _classify_page_approach() 决定处理方式?
    │
    ├── text-first (文本足够)
    │   └── 直接使用 cleaned_text
    │
    └── ocr-rebuild (文本不足/乱码) 且 enable_ocr?
        │
        ├── ocr_image_with_bbox(截图) → ocr_items (带 bbox)
        │   │
        │   ▼
        │   ocr_items 非空?
        │       ├── Yes
        │       │   ├── _tag_ocr_items_by_zone() → 三区域标注
        │       │   │   ├── TOP (y < 200) → 标题/标注
        │       │   │   ├── MIDDLE (200 ≤ y < 600)
        │       │   │   │   ├── 含内容关键词 且 不含 UI 标签 → CONTENT
        │       │   │   │   └── 其他 → SCREENSHOT
        │       │   │   └── BOTTOM (y ≥ 600) → CONTENT
        │       │   │
        │       │   ├── _extract_pdf_drawing_annotations() → 箭头/矩形/曲线
        │       │   │   ├── _annotate_arrows() → "→ 从「A」指向「B」"
        │       │   │   └── _detect_revision_markers() → 新增/删除/修改
        │       │   │
        │       │   └── _rebuild_ocr_to_markdown() → 结构化 Markdown
        │       │       └── 输出顺序: 标题 → 截图区域 → 内容区域 → 箭头 → 变更
        │       │
        │       └── No → 回退到 cleaned_text
        │
        └── No (OCR 不可用) → 使用 cleaned_text
            │
            ▼
        merge_text_evidence(primary_text, ocr_text)
            ├── 无 primary → 返回 secondary (OCR)
            ├── 无 secondary → 返回 primary
            └── 都有 → primary_lines + secondary 中新增的行

    ▼
    is_visual_risk 判定:
        ├── aspect_ratio ≥ 1.6 且 text < 900 → Yes
        ├── keyword_hits 命中 (flow/architecture/diagram/...) → Yes
        └── text < 180 → Yes
```

---

## 决策树 7: EFM 格式路由 (bundle_runner.py)

```
输入文件扩展名?
    │
    ├── .pdf / .ppt / .pptx
    │   └── process_visual_document()
    │       ├── .pdf → 直接复制 → run_pdf_pipeline()
    │       ├── .doc/.docx → Word COM 归一为 PDF → run_pdf_pipeline()
    │       │   └── 额外: build_embedded_media_review() (提取 word/media/*)
    │       └── .ppt/.pptx → PPT COM 归一为 PPTX+PDF → run_pdf_pipeline()
    │           └── 额外: build_embedded_media_review() (提取 ppt/media/*)
    │
    ├── .doc / .docx
    │   └── process_word_document()
    │       ├── .doc → Word COM 归一为 .docx
    │       ├── extract_docx_blocks() → 从 OOXML 提取段落/表格/图片
    │       ├── export_word_document() → source.md + final.md
    │       └── build_embedded_media_review() (提取 word/media/*)
    │
    ├── .xls / .xlsx
    │   └── process_workbook_document()
    │       ├── .xls → Excel COM 归一为 .xlsx
    │       ├── export_workbook_csvs() → csv/*.csv (每 sheet 一个)
    │       └── build_embedded_media_review() (提取 xl/media/*)
    │
    ├── .html / .htm / .md / .txt / .rst / .log
    │   └── process_text_document()
    │       ├── HTML → markitdown / markdownify / 朴素去标签 → Markdown
    │       └── 其他 → 直接作为正文
    │
    ├── .csv / .tsv / .json / .yaml / .xml / .py / .java / ...
    │   └── process_data_document()
    │       ├── .csv/.tsv → 额外渲染为 Markdown 表格预览 (前50行)
    │       └── 所有 → 包裹在 ```lang 代码块中
    │
    ├── .png / .jpg / .jpeg / .bmp / .gif / .webp / .svg / .ico
    │   └── process_image_document()
    │       ├── 复制图片到 assets/
    │       ├── 嵌入 ![]() 引用
    │       └── enable_ocr? → 尝试 OCR 提取文字
    │
    └── 其他 → ✗ 抛出 ValueError
```

---

## 决策树 8: 双引擎选主 (集成 Runner choose())

```
choose(source_path, doc_pre_result, efm_result)
    │
    doc_pre.final_exists? (doc_ok)
    efm.final_exists? (efm_ok)
    │
    ├── 是 Office 格式 (.doc/.docx/.ppt/.pptx/.xls/.xlsx) 且 efm_ok?
    │   └── → "efm" (EFM 完成 OOXML/table/media 保真路线)
    │
    ├── 是扩展格式 (图片/HTML/文本/数据/代码) 且 efm_ok?
    │   └── → "efm" (EFM 处理扩展格式路线)
    │
    ├── doc_ok 且 !efm_ok?
    │   └── → "doc-pre" (EFM 未产出 final.md)
    │
    ├── efm_ok 且 !doc_ok?
    │   └── → "efm" (doc-pre 未产出 final.md)
    │
    ├── doc_ok 且 efm_ok? (双方都成功)
    │   └── 比较 RANK[review_status]:
    │       ├── RANK[efm] > RANK[doc-pre]?
    │       │   └── → "efm" (EFM review status 更强)
    │       └── 平局或 doc-pre 更强?
    │           └── → "doc-pre" (平局偏好 doc-pre，保留原文措辞)
    │
    └── 都不成功?
        └── → "none" (无引擎产出 final.md)

── RANK 等级 ──
    pass              = 4
    skipped           = 3
    needs-human-review = 2
    needs-repair      = 1
    failed / not-run  = 0
```

---

## 决策树 9: 输出提升与链接重写 (promote())

```
promote(doc_dir, source_file, primary_engine, reason)
    │
    ▼
    selected = engines[primary_engine]
    │
    ├── selected.source_path 存在?
    │   └── 读取 source.md
    │       └── rewrite_markdown_links(source_body, engine_root, doc_dir)
    │           │
    │           ├── 在 ``` 代码块内? → ✗ 跳过
    │           ├── 目标是外部链接 (http/https/mailto/#)? → ✗ 跳过
    │           ├── 目标在 LOCAL_DOC_LINKS (source.md/final.md/...)? → ✗ 跳过
    │           ├── 源路径文件不存在? → ✗ 跳过
    │           └── → 重写为相对路径 (指向 engine-results/...)
    │
    ├── selected.final_path 存在?
    │   └── 读取 final.md → rewrite_markdown_links() → 同上规则
    │
    └── 写 link-check-report.json
        │
        check_markdown_links(final.md, doc_dir)
            │
            ├── 在 ``` 代码块内? → ✗ 跳过
            ├── 外部链接? → ✗ 跳过
            ├── 目标文件在 base_dir 下存在?
            │   ├── Yes → ✓ 通过
            │   └── No → ✗ 记录为 broken link (行号 + 目标)
            │
            └── 输出: {checked_local_link_count, broken_link_count, broken_links[]}
```

---

## 决策树 10: 多模态修复触发 (Post-Pipeline)

```
管线执行完毕
    │
    ▼
    存在 multimodal-repair-brief.json?
        │
        ├── No → ✓ 无需修复，管线结束
        │
        └── Yes (检测到纯图片 PDF)
            │
            ▼
            Agent 自动执行修复:
                │
                1. 读取 multimodal-repair-brief.json
                2. 读取 brief.page_images[*].path (所有页面截图)
                   或 brief.page_tiles[*][*].path (分块截图)
                3. 读取 source.md (OCR 基线文本)
                4. 多模态视觉分析:
                    ├── 标题层级
                    ├── 表格结构
                    ├── 段落分组
                    ├── 列表关系
                    └── 标注布局
                5. 修复 final.md:
                    ├── 规则: OCR text = 内容主干 (不得改写/意译/编造)
                    ├── 规则: screenshots = 结构参考
                    ├── 添加 Markdown 格式 (标题/表格/列表/图片引用)
                    └── 保留所有 OCR 文本原文
                6. 写回 final.md
                7. 确认修复完成
```

---

## pure_image_pdf_path 专用流程

```text
routing.py 判定为纯图片 PDF
    │
    ▼
pipeline.py:
    ├── baseline_adapter.extract() → 返回空 (无可提取文本)
    ├── pdf_preparation_worker.prepare() → 渲染页面 + 分块 (如需要)
    │   └── metadata["tile_grid"] = [rows, cols]  (记录分块信息)
    │
    ▼
multimodal_reconstruction_worker.reconstruct():
    ├── 检测 tile_grid?
    │   ├── Yes → 对每个 tile 调用 API 进行 _stitch_tile_markdown 拼接
    │   └── No → 对单张截图调用 API
    │
    ▼
pdf_repair_adapter.repair() → 生成 final.md
```

---

## 决策树 11: UE 文档区域分类 (EFM)

```text
_ocr_items_by_zone(ocr_items)
    │
    对每个 OCR item:
        y_norm = item.y_center (0-1000 归一化)
        text = item.text
        │
        y_norm < 200? (顶部 20%)
            ├── Yes → _ZONE_TOP (标题/标注区)
            └── No → 继续
                │
                y_norm >= 600? (底部 40%)
                    ├── Yes → _ZONE_CONTENT (功能描述区)
                    └── No → 中间 40% (截图区，可被内容覆盖)
                        │
                        has_content_keyword(text)?
                            (用户通过 / 启用/禁用 / 点击打开 / 开启后 / ...)
                            └── Yes → 继续
                                │
                                is_ui_label(text)?
                                    (Tab标签 / 一级 / 二级 / ℃ / Bar / icon / ...)
                                    ├── Yes → _ZONE_SCREENSHOT
                                    └── No → _ZONE_CONTENT
                        │
                        └── No (无内容关键词)
                            └── _ZONE_SCREENSHOT

── 最终输出顺序 ──
    1. _append_title_zone_markdown()    → 标题/标注
    2. _append_screenshot_zone_markdown() → 截图区域 (> 引用块)
    3. _append_content_zone_markdown()  → 功能描述
    4. _append_arrow_annotation_markdown() → 页面流转标注
    5. _append_revision_markdown()      → 变更标记
```

---

## 决策树 12: EFM OCR 区域自动分类

```text
OCR 文本块自动分类 (Phase 4)
    │
    对每条 OCR 文本:
        │
        ├── 行长 ≥ 15 字符 且 含规则说明用语?
        │   ("用户"、"启用"、"开启后"、"请"...)
        │   └── → 正文
        │
        ├── 是状态栏时间 / 开关状态 / 占位标记 / 纯短数字?
        │   ("21:05"、"ON"、"OFF"、"icon"、"Bar"、"插图"...)
        │   └── → UI 噪音
        │
        └── 短文本块 (4-8 字符)?
            └── → 不确定 (需人工判定)
                │
                ▼
            生成交互式报告: evidence/ocr-review.html
                ├── 左侧: 页面截图
                ├── 右侧: 每条 OCR 文本 + 分类标签
                ├── 点击可切换分类
                └── 导出决策 JSON → 下次运行自动读取
```

---

## 决策树 13: 完成标准检查

```text
管线结束 — 验收清单
    │
    ├── [1] batch-manifest.json 中有每个输入文档的记录?
    │   ├── Yes → ✓
    │   └── No → ✗ 失败
    │
    ├── [2] 每文档有 comparison.md + markfiledown-decision.json?
    │   ├── Yes → ✓
    │   └── No → ✗ 失败
    │
    ├── [3] 至少一个引擎成功的文档有 promoted final.md?
    │   ├── Yes → ✓
    │   └── No → ✗ (记录原因)
    │
    ├── [4] 引擎失败日志保留在 engine-results/ 下的 log 文件?
    │   ├── Yes → ✓
    │   └── No → 检查日志目录
    │
    ├── [5] link-check-report.json 的 broken_link_count == 0?
    │   ├── Yes → ✓
    │   └── No → ⚠ 链接损坏，需排查
    │
    ├── [6] report.html 生成并包含每文档决策?
    │   ├── Yes → ✓
    │   └── No → ✗ 失败
    │
    └── [7] 存在 multimodal-repair-brief.json?
        ├── Yes → ⚠ Agent 需执行自动多模态修复
        └── No → ✓ 管线完全结束
```

---

## 全局决策流总览

```text
用户输入 (文件/目录)
    │
    ▼
┌─────────────────────────────────────────┐
│ DT1: 输入发现与格式过滤                   │
│   → 文件列表                              │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ DT2: 双引擎路由                           │
│   → doc-pre 执行? / EFM 执行?            │
│   → PDF: 纯图片检测? → pure_image_pdf_path│
└─────────────────┬───────────────────────┘
                  │
          ┌───────┴───────┐
          ▼               ▼
┌───────────────┐ ┌───────────────┐
│ DT3: doc-pre   │ │ DT7: EFM 格式 │
│ 路由           │ │ 路由           │
│               │ │               │
│ DT3.5: 分块   │ │ DT5: OCR 路由 │
│ 处理 (如需要) │ │ DT6: PDF 页面 │
│ DT4: 文本提取  │ │ 处理           │
│ DT6: PDF 页面  │ │ DT11: UE 区域 │
│ 处理           │ │ 分类           │
│               │ │ DT12: OCR 自  │
│               │ │ 动分类         │
└───────┬───────┘ └───────┬───────┘
        │                 │
        ▼                 ▼
┌─────────────────────────────────────────┐
│ DT8: 双引擎选主 (choose)                 │
│   → primary_engine = doc-pre | efm | none│
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ DT9: 输出提升与链接重写 (promote)         │
│   → source.md + final.md + link-check   │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ DT10: 多模态修复触发 (Post-Pipeline)     │
│   → brief 存在? → Agent 自动修复          │
│   → pure_image_pdf_path: tile 拼接       │
└─────────────────┬───────────────────────┘
                  │
                  ▼
┌─────────────────────────────────────────┐
│ DT13: 完成标准检查                        │
│   → ✓ 全部通过 / ⚠ 需人工介入            │
└─────────────────────────────────────────┘
```
