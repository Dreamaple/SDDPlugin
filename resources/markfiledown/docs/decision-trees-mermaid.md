# MarkFileDown 0509 — 决策树 (Mermaid)

> **版本**: v1.1.0
> **最后更新**: 2026-06-02
> **覆盖范围**: 输入发现 → 格式路由 → 引擎选主 → OCR 路由 → 链接校验 → 多模态修复

---

## 全局决策流总览

```mermaid
flowchart TD
    A["用户输入 (文件/目录)"] --> DT1
    DT1["DT1: 输入发现与格式过滤"] --> DT2
    DT2["DT2: 双引擎路由"] --> D2A["doc-pre 路径"]
    DT2 --> D2B["EFM 路径"]

    D2A --> DT3["DT3: doc-pre 路由"]
    DT3 --> DT4["DT4: 文本提取"]
    DT4 --> DT6["DT6: PDF 页面处理"]

    D2B --> DT7["DT7: EFM 格式路由"]
    DT7 --> DT5["DT5: OCR 路由"]
    DT7 --> DT6
    DT7 --> DT11["DT11: UE 区域分类"]
    DT7 --> DT12["DT12: OCR 自动分类"]

    D2A --> DT8
    D2B --> DT8["DT8: 双引擎选主 (choose)"]
    DT8 -->|"doc-pre | efm | none"| DT9

    DT9["DT9: 输出提升与链接重写 (promote)"] --> DT10
    DT10["DT10: 多模态修复触发"] --> DT13
    DT13["DT13: 完成标准检查"] --> END["✅ 全部通过 / ⚠ 需人工介入"]
```

---

## DT1: 输入发现与格式过滤

```mermaid
flowchart TD
    A["用户提供输入"] --> B{"是单个文件?"}
    B -->|"是"| C["直接使用"]
    B -->|"否 (目录)"| D{"--recurse=on?"}
    D -->|"是"| E["递归扫描 **/*"]
    D -->|"否"| F["仅扫描顶层 *"]

    E --> G[过滤规则]
    F --> G

    subgraph G ["过滤规则"]
        G1["扩展名不在 SUPPORTED 集合 → ✗ 排除"]
        G2["文件名以 ~$ 开头 (Office 临时文件) → ✗ 排除"]
        G3["路径包含 excluded 部分<br/>(.git, outputs, __pycache__) → ✗ 排除"]
        G4["--source-format != auto → 仅保留匹配扩展名"]
    end

    G --> H{"有文件吗?"}
    H -->|"否"| I["✗ 抛出 FileNotFoundError"]
    H -->|"是"| J["去重 (SHA1 前8位 + 路径)"]
    J --> K["进入处理队列"]

    style I fill:#f88
    style K fill:#8f8
```

---

## DT2: 双引擎路由 (集成 Runner)

```mermaid
flowchart TD
    A["队列中每个源文件"] --> B{"源文件扩展名?"}

    B -->|"图片/HTML/文本<br/>数据/代码"| C1["doc-pre: ✗ 跳过<br/>(extended format, EFM)"]
    C1 --> C2["EFM: ✓ 进入 EFM 处理"]

    B -->|"PDF .pdf"| D1["doc-pre: ✓ 始终执行"]
    D1 --> D2["EFM: should_efm?"]
    D2 --> D3{"文件大小 > 80MB?"}
    D3 -->|"是"| D4["✗ 跳过 (PDF too large)"]
    D3 -->|"否"| D5["✓ 执行"]

    B -->|"Office<br/>doc/docx/ppt/pptx/xls/xlsx"| E1["doc-pre: ✓ 始终执行<br/>(通用文本提取)"]
    E1 --> E2["EFM: ✓ 始终执行<br/>(OOXML 直接提取)"]

    B -->|"其他不支持的格式"| F["✗ 报错"]

    style C1 fill:#ffa
    style D1 fill:#8f8
    style D4 fill:#f88
    style D5 fill:#8f8
    style E1 fill:#8f8
    style E2 fill:#8f8
    style F fill:#f88
```

---

## DT3: doc-pre 引擎路由 (routing.py)

```mermaid
flowchart TD
    A["输入文件扩展名?"] --> B{".xlsx / .xls / .csv?"}
    B -->|"是"| C["spreadsheet_pipeline<br/>confidence=0.98<br/>产物: CSV 导出 + manifest"]

    B -->|"否"| D{".docx?"}
    D -->|"是"| E["office_document_pipeline<br/>confidence=0.95<br/>产物: OOXML 文本提取 + evidence"]

    D -->|"否"| F{".pptx?"}
    F -->|"是"| G["presentation_pipeline<br/>confidence=0.95<br/>产物: 幻灯片提取 + 嵌入图片"]

    F -->|"否"| H{".pdf?"}
    H -->|"是"| I{"文件大小?"}
    I -->|"≥ 15MB"| J["complex_visual_pdf_path<br/>confidence=0.60"]
    I -->|"≥ 5MB"| K["mixed_pdf_path<br/>confidence=0.70"]
    I -->|"< 5MB"| L["simple_text_pdf_path<br/>confidence=0.65"]

    H -->|"否"| M["generic_file_pipeline<br/>confidence=0.50"]

    style C fill:#bbf
    style E fill:#bbf
    style G fill:#bbf
    style J fill:#ff9
    style K fill:#ff9
    style L fill:#ff9
    style M fill:#ddd
```

---

## DT4: doc-pre 文本提取 (Baseline Adapter)

```mermaid
flowchart TD
    A["MarkItDownBaselineAdapter.extract()"] --> B{"能导入 MarkItDown 库?"}

    B -->|"是"| C["执行 MarkItDown.convert()"]
    C --> D{"返回 markdown 非空?"}
    D -->|"是"| E{"是 DOCX?"}
    E -->|"是"| F["执行表格换行修复<br/>(OOXML 直接解析)"]
    E -->|"否"| G["直接返回 markdown"]
    D -->|"否 (空)"| H["进入 Fallback"]

    B -->|"否 (导入失败/异常)"| H

    subgraph Fallback ["Fallback"]
        H --> I{"是 PDF?"}
        I -->|"是"| J{"pdfplumber 可用?"}
        J -->|"是"| K["执行 PDF OCR 提取<br/>对每页:"]
        K --> L{"extract_text() 有文本?"}
        L -->|"是"| M["使用提取文本 → 结构化 Markdown"]
        L -->|"否"| N{"RapidOCR 可用?"}
        N -->|"是"| O["渲染页面 → OCR → 结构化 Markdown"]
        N -->|"否"| P["> 该页无可用文本"]
        J -->|"否"| Q["进入文本文件 Fallback"]
        I -->|"否"| R{"文本文件类型?"}
        R -->|".md/.markdown"| S["直接返回"]
        R -->|".csv"| T["包裹在 ```csv 代码块"]
        R -->|"其他文本"| U["# filename\n\n{内容}"]
        R -->|"都不匹配"| V["Placeholder Markdown"]
    end

    M --> W["返回: # filename\n\n## Page N\n..."]
    O --> W
    P --> W
    F --> G
    G --> DONE
    S --> DONE
    T --> DONE
    U --> DONE
    V --> DONE
    Q --> R
    DONE["✅ 返回 markdown"]

    style DONE fill:#8f8
    style H fill:#ffa
    style P fill:#f88
```

---

## DT5: 自适应 OCR 路由 (EFM)

```mermaid
flowchart TD
    A["_classify_page_approach<br/>cleaned_text, page_image_count, enable_ocr"] --> B{"len(cleaned_text) ≥ 20?"}

    B -->|"是"| C{"文本可读率 ≥ 60%?<br/>_is_text_garbled"}
    C -->|"是"| D["✅ text-first<br/>(跳过 OCR)"]
    C -->|"否 (乱码)"| E["需要 OCR → 继续"]

    B -->|"否 (< 20 字符/空)"| E

    E --> F{"enable_ocr?"}
    F -->|"是"| G["✅ ocr-rebuild"]
    F -->|"否"| H["⚠ text-first (无能为力)"]

    subgraph ReadableCheck ["可读率判定 _is_text_garbled"]
        RC1["遍历每个非空格字符"] --> RC2{"在可读 Unicode 范围内?<br/>ASCII printable / CJK / 全角符号"}
        RC2 -->|"是"| RC3["readable++"]
        RC2 -->|"否 (replacement char /<br/>private-use / control char)"| RC4["unreadable++"]
        RC3 --> RC5{"readable / total < 0.60?"}
        RC4 --> RC5
        RC5 -->|"是"| RC6["🔴 乱码 → 触发 OCR"]
        RC5 -->|"否"| RC7["✅ 正常 → 跳过 OCR"]
    end

    E -.-> ReadableCheck

    style D fill:#8f8
    style G fill:#8f8
    style H fill:#ffa
    style RC6 fill:#f88
    style RC7 fill:#8f8
```

---

## DT6: PDF 页面处理 (EFM)

```mermaid
flowchart TD
    A["build_page_data(pdf_path)"] --> B["对每页:"]

    subgraph Extract ["页面数据提取"]
        B --> B1["pdfplumber.extract_text() → cleaned_text"]
        B1 --> B2["pdfplumber.extract_tables() → tables"]
        B2 --> B3["pdfplumber.images → image_count"]
        B3 --> B4["pypdfium2.render() → 页面截图"]
    end

    B4 --> C["_classify_page_approach() 决定处理方式"]

    C -->|"text-first<br/>(文本足够)"| D["直接使用 cleaned_text"]

    C -->|"ocr-rebuild<br/>(文本不足/乱码)"| E{"enable_ocr?"}
    E -->|"是"| F["ocr_image_with_bbox(截图) → ocr_items"]
    F --> G{"ocr_items 非空?"}

    G -->|"是"| H["_tag_ocr_items_by_zone() → 三区域标注"]
    H --> H1["TOP (y < 200) → 标题/标注区"]
    H --> H2["MIDDLE (200 ≤ y < 600)"]
    H2 --> H2a["含内容关键词 且 不含 UI 标签 → CONTENT"]
    H2 --> H2b["其他 → SCREENSHOT"]
    H --> H3["BOTTOM (y ≥ 600) → CONTENT"]

    H1 --> I["_extract_pdf_drawing_annotations()"]
    H2a --> I
    H2b --> I
    H3 --> I
    I --> I1["_annotate_arrows() → 从A指向B"]
    I --> I2["_detect_revision_markers() → 新增/删除/修改"]

    I1 --> J["_rebuild_ocr_to_markdown()"]
    I2 --> J
    J --> J1["输出顺序:<br/>标题 → 截图区域 → 内容区域 → 箭头 → 变更"]

    G -->|"否"| K["回退到 cleaned_text"]
    E -->|"否 (OCR 不可用)"| K

    K --> L["merge_text_evidence(primary_text, ocr_text)"]
    D --> L
    J1 --> L
    L --> L1["无 primary → 返回 secondary(OCR)"]
    L --> L2["无 secondary → 返回 primary"]
    L --> L3["都有 → primary_lines + secondary 新增行"]

    L1 --> M["is_visual_risk 判定"]
    L2 --> M
    L3 --> M

    M --> M1{"aspect_ratio ≥ 1.6<br/>且 text < 900?"}
    M1 -->|"是"| M4["⚠ visual_risk = Yes"]
    M1 -->|"否"| M2{"命中 keyword?<br/>flow/architecture/diagram?"}
    M2 -->|"是"| M4
    M2 -->|"否"| M3{"text < 180?"}
    M3 -->|"是"| M4
    M3 -->|"否"| M5["✅ visual_risk = No"]

    style M4 fill:#ffa
    style M5 fill:#8f8
    style D fill:#bbf
    style J1 fill:#bfb
```

---

## DT7: EFM 格式路由 (bundle_runner.py)

```mermaid
flowchart TD
    A["输入文件扩展名?"] --> B{".pdf / .ppt / .pptx?"}
    B -->|"是"| C["process_visual_document()"]
    C --> C1[".pdf → 直接复制 → run_pdf_pipeline()"]
    C --> C2[".doc/.docx → Word COM 归一为 PDF<br/>→ run_pdf_pipeline()<br/>+ build_embedded_media_review()"]
    C --> C3[".ppt/.pptx → PPT COM 归一为 PPTX+PDF<br/>→ run_pdf_pipeline()<br/>+ build_embedded_media_review()"]

    B -->|"否"| D{".doc / .docx?"}
    D -->|"是"| E["process_word_document()"]
    E --> E1[".doc → Word COM 归一为 .docx"]
    E1 --> E2["extract_docx_blocks()<br/>→ OOXML 提取段落/表格/图片"]
    E2 --> E3["export_word_document()<br/>→ source.md + final.md"]
    E3 --> E4["build_embedded_media_review()<br/>(word/media/*)"]

    D -->|"否"| F{".xls / .xlsx?"}
    F -->|"是"| G["process_workbook_document()"]
    G --> G1[".xls → Excel COM 归一为 .xlsx"]
    G1 --> G2["export_workbook_csvs()<br/>→ csv/*.csv (每 sheet 一个)"]
    G2 --> G3["build_embedded_media_review()<br/>(xl/media/*)"]

    F -->|"否"| H{".html/.htm/.md/.txt/.rst/.log?"}
    H -->|"是"| I["process_text_document()"]
    I --> I1["HTML → markitdown/markdownify/去标签"]
    I --> I2["其他 → 直接作为正文"]

    H -->|"否"| J{".csv/.tsv/.json/.yaml/.xml<br/>/.py/.java/...?"}
    J -->|"是"| K["process_data_document()"]
    K --> K1[".csv/.tsv → 额外渲染 Markdown 表格预览(前50行)"]
    K --> K2["所有 → 包裹在 ```lang 代码块"]

    J -->|"否"| L{".png/.jpg/.jpeg/.bmp<br/>.gif/.webp/.svg/.ico?"}
    L -->|"是"| M["process_image_document()"]
    M --> M1["复制图片到 assets/"]
    M1 --> M2["嵌入 ![]() 引用"]
    M2 --> M3{"enable_ocr?"}
    M3 -->|"是"| M4["尝试 OCR 提取文字"]
    M3 -->|"否"| M5["跳过 OCR"]

    L -->|"否"| N["✗ 抛出 ValueError"]

    style N fill:#f88
    style C1 fill:#bbf
    style C2 fill:#bbf
    style C3 fill:#bbf
    style E4 fill:#bbf
    style G3 fill:#bbf
```

---

## DT8: 双引擎选主 (集成 Runner choose)

```mermaid
flowchart TD
    A["choose(source_path, doc_pre_result, efm_result)"] --> B["doc_pre.final_exists? → doc_ok<br/>efm.final_exists? → efm_ok"]

    B --> C{"Office 格式<br/>且 efm_ok?"}
    C -->|"是"| D["→ efm<br/>(OOXML/table/media 保真路线)"]

    C -->|"否"| E{"扩展格式(图片/HTML/文本<br/>/数据/代码) 且 efm_ok?"}
    E -->|"是"| F["→ efm<br/>(EFM 扩展格式路线)"]

    E -->|"否"| G{"doc_ok 且 !efm_ok?"}
    G -->|"是"| H["→ doc-pre<br/>(EFM 未产出 final.md)"]

    G -->|"否"| I{"efm_ok 且 !doc_ok?"}
    I -->|"是"| J["→ efm<br/>(doc-pre 未产出 final.md)"]

    I -->|"否"| K{"doc_ok 且 efm_ok?<br/>(双方都成功)"}
    K -->|"是"| L{"RANK[efm] > RANK[doc-pre]?"}
    L -->|"是"| M["→ efm<br/>(EFM review status 更强)"]
    L -->|"否 (平局或 doc-pre 更强)"| N["→ doc-pre<br/>(平局偏好 doc-pre，保留原文措辞)"]

    K -->|"否"| O{"都不成功?"}
    O -->|"是"| P["→ none<br/>(无引擎产出 final.md)"]

    subgraph Rank ["RANK 等级"]
        R1["pass = 4"]
        R2["skipped = 3"]
        R3["needs-human-review = 2"]
        R4["needs-repair = 1"]
        R5["failed / not-run = 0"]
    end

    L -.-> Rank

    style D fill:#bbf
    style F fill:#bbf
    style H fill:#bfb
    style J fill:#bbf
    style M fill:#bbf
    style N fill:#bfb
    style P fill:#f88
```

---

## DT9: 输出提升与链接重写 (promote)

```mermaid
flowchart TD
    A["promote(doc_dir, source_file, primary_engine, reason)"] --> B["selected = engines[primary_engine]"]

    B --> C{"selected.source_path 存在?"}
    C -->|"是"| D["读取 source.md"]
    D --> E["rewrite_markdown_links<br/>(source_body, engine_root, doc_dir)"]
    E --> F["链接重写规则"]

    subgraph RewriteRules ["链接重写规则"]
        F --> F1{"在 ``` 代码块内?"}
        F1 -->|"是"| F1x["✗ 跳过"]
        F1 -->|"否"| F2{"目标是外部链接?<br/>http/https/mailto/#"}
        F2 -->|"是"| F2x["✗ 跳过"]
        F2 -->|"否"| F3{"目标在 LOCAL_DOC_LINKS?<br/>source.md/final.md/..."}
        F3 -->|"是"| F3x["✗ 跳过"]
        F3 -->|"否"| F4{"源路径文件存在?"}
        F4 -->|"否"| F4x["✗ 跳过"]
        F4 -->|"是"| F5["✅ 重写为相对路径<br/>(指向 engine-results/...)"]
    end

    C -->|"否"| G

    G{"selected.final_path 存在?"} -->|"是"| H["读取 final.md"]
    H --> I["rewrite_markdown_links() → 同上规则"]
    I --> J["写 link-check-report.json"]
    G -->|"否"| J

    J --> K["check_markdown_links(final.md, doc_dir)"]

    subgraph LinkCheck ["链接校验"]
        K --> K1{"在 ``` 代码块内?"}
        K1 -->|"是"| K1x["✗ 跳过"]
        K1 -->|"否"| K2{"外部链接?"}
        K2 -->|"是"| K2x["✗ 跳过"]
        K2 -->|"否"| K3{"目标文件在 base_dir 下存在?"}
        K3 -->|"是"| K3x["✅ 通过"]
        K3 -->|"否"| K3y["✗ 记录 broken link<br/>(行号 + 目标)"]
        K3x --> K4["输出: {checked_local_link_count,<br/>broken_link_count, broken_links[]}"]
        K3y --> K4
    end

    J -.-> LinkCheck

    style F1x fill:#f88
    style F2x fill:#f88
    style F3x fill:#f88
    style F4x fill:#f88
    style F5 fill:#8f8
    style K3x fill:#8f8
    style K3y fill:#f88
```

---

## DT10: 多模态修复触发 (Post-Pipeline)

```mermaid
flowchart TD
    A["管线执行完毕"] --> B{"存在<br/>multimodal-repair-brief.json?"}

    B -->|"否"| C["✅ 无需修复，管线结束"]

    B -->|"是 (检测到纯图片 PDF)"| D["Agent 自动执行修复"]

    subgraph RepairSteps ["自动修复流程"]
        D --> D1["1. 读取 multimodal-repair-brief.json"]
        D1 --> D2["2. 读取 brief.page_images[*].path<br/>(所有页面截图)"]
        D2 --> D3["3. 读取 source.md (OCR 基线文本)"]
        D3 --> D4["4. 多模态视觉分析"]
        D4 --> D4a["标题层级"]
        D4 --> D4b["表格结构"]
        D4 --> D4c["段落分组"]
        D4 --> D4d["列表关系"]
        D4 --> D4e["标注布局"]
        D4a --> D5["5. 修复 final.md"]
        D4b --> D5
        D4c --> D5
        D4d --> D5
        D4e --> D5
        D5 --> D5a["规则: OCR text = 内容主干<br/>(不得改写/意译/编造)"]
        D5a --> D5b["规则: screenshots = 结构参考"]
        D5b --> D5c["添加 Markdown 格式<br/>(标题/表格/列表/图片引用)"]
        D5c --> D5d["保留所有 OCR 文本原文"]
        D5d --> D6["6. 写回 final.md"]
        D6 --> D7["7. 确认修复完成"]
    end

    style C fill:#8f8
    style D fill:#ffa
    style D5a fill:#f88
    style D5b fill:#bbf
```

---

## DT11: UE 文档区域分类 (EFM)

```mermaid
flowchart TD
    A["_ocr_items_by_zone(ocr_items)<br/>对每个 OCR item:"] --> B["y_norm = item.y_center (0-1000 归一化)<br/>text = item.text"]

    B --> C{"y_norm < 200?<br/>(顶部 20%)"}
    C -->|"是"| D["_ZONE_TOP<br/>标题/标注区"]

    C -->|"否"| E{"y_norm >= 600?<br/>(底部 40%)"}
    E -->|"是"| F["_ZONE_CONTENT<br/>功能描述区"]
    E -->|"否"| G["中间 40% (截图区,可被内容覆盖)"]

    G --> H{"has_content_keyword(text)?<br/>用户通过/启用/禁用/点击打开/开启后"}
    H -->|"否"| I["_ZONE_SCREENSHOT"]
    H -->|"是"| J{"is_ui_label(text)?<br/>Tab标签/一级/二级/℃/Bar/icon"}
    J -->|"是"| I
    J -->|"否"| K["_ZONE_CONTENT"]

    subgraph Output ["最终输出顺序"]
        O1["1. _append_title_zone_markdown()<br/>   → 标题/标注"]
        O2["2. _append_screenshot_zone_markdown()<br/>   → 截图区域 (> 引用块)"]
        O3["3. _append_content_zone_markdown()<br/>   → 功能描述"]
        O4["4. _append_arrow_annotation_markdown()<br/>   → 页面流转标注"]
        O5["5. _append_revision_markdown()<br/>   → 变更标记"]
        O1 --> O2 --> O3 --> O4 --> O5
    end

    D -.-> Output
    F -.-> Output
    K -.-> Output
    I -.-> Output

    style D fill:#ffd
    style F fill:#bfb
    style I fill:#ddd
    style K fill:#bfb
```

---

## DT12: EFM OCR 区域自动分类

```mermaid
flowchart TD
    A["OCR 文本块自动分类 (Phase 4)<br/>对每条 OCR 文本:"] --> B{"行长 ≥ 15 字符<br/>且含规则说明用语?<br/>(用户/启用/开启后/请)"}

    B -->|"是"| C["✅ 正文"]

    B -->|"否"| D{"是状态栏时间/开关状态<br/>/占位标记/纯短数字?<br/>(21:05/ON/OFF/icon/Bar/插图)"}
    D -->|"是"| E["⚠ UI 噪音"]

    D -->|"否"| F{"短文本块 (4-8 字符)?"}
    F -->|"是"| G["❓ 不确定 (需人工判定)"]
    F -->|"否"| H["❓ 不确定 (需人工判定)"]

    G --> I["生成交互式报告:<br/>evidence/ocr-review.html"]
    H --> I
    I --> I1["左侧: 页面截图"]
    I --> I2["右侧: 每条 OCR 文本 + 分类标签"]
    I1 --> I3["点击可切换分类"]
    I2 --> I3
    I3 --> I4["导出决策 JSON<br/>→ 下次运行自动读取"]

    style C fill:#8f8
    style E fill:#ffa
    style G fill:#ddd
    style H fill:#ddd
```

---

## DT13: 完成标准检查

```mermaid
flowchart TD
    A["管线结束 — 验收清单"] --> C1{"[1] batch-manifest.json<br/>有每个输入文档记录?"}
    C1 -->|"是"| C1a["✅"]
    C1 -->|"否"| C1b["✗ 失败"]

    C1a --> C2{"[2] 每文档有 comparison.md<br/>+ markfiledown-decision.json?"}
    C2 -->|"是"| C2a["✅"]
    C2 -->|"否"| C2b["✗ 失败"]

    C2a --> C3{"[3] 至少一个引擎成功的文档<br/>有 promoted final.md?"}
    C3 -->|"是"| C3a["✅"]
    C3 -->|"否"| C3b["✗ (记录原因)"]

    C3a --> C4{"[4] 引擎失败日志保留在<br/>engine-results/ 下的 log 文件?"}
    C4 -->|"是"| C4a["✅"]
    C4 -->|"否"| C4b["检查日志目录"]

    C4a --> C5{"[5] link-check-report.json<br/>的 broken_link_count == 0?"}
    C5 -->|"是"| C5a["✅"]
    C5 -->|"否"| C5b["⚠ 链接损坏，需排查"]

    C5a --> C6{"[6] report.html 生成<br/>并包含每文档决策?"}
    C6 -->|"是"| C6a["✅"]
    C6 -->|"否"| C6b["✗ 失败"]

    C6a --> C7{"[7] 存在<br/>multimodal-repair-brief.json?"}
    C7 -->|"是"| C7a["⚠ Agent 需执行自动多模态修复"]
    C7 -->|"否"| C7b["✅ 管线完全结束"]

    style C1b fill:#f88
    style C2b fill:#f88
    style C3b fill:#f88
    style C4b fill:#ffa
    style C5b fill:#ffa
    style C6b fill:#f88
    style C7a fill:#ffa
    style C7b fill:#8f8
    style C1a fill:#8f8
    style C2a fill:#8f8
    style C3a fill:#8f8
    style C4a fill:#8f8
    style C5a fill:#8f8
    style C6a fill:#8f8
```
