# EFM Pipeline UE 文档还原增强任务清单

> 目标：让 EFM pipeline 产出的 final.md 能完整替代原 PDF 阅读，
> 文字还原 + 结构重建 + 截图标注 + 箭头/修订标记识别。
> 按阶段执行，每阶段可独立验收。
>
> **状态图例**: ✅ 已完成 | 🔄 进行中 | ⏳ 待开始

---

## Phase 0：自适应路由策略（通用决策引擎） ✅

**目标**：管线自动判断每页用哪种方案（文本提取 / OCR重建）。

### T0.1 路由决策函数
- ✅ `pipeline_runner.py`: `_classify_page_approach()` — 基于文本质量、图片数量、文档总页数决策
- ✅ 返回值: `text-first` / `ocr-rebuild`
- ✅ 决策因子:
  - pdfplumber 文本 ≥ 20 字符且非乱码 → `text-first`（不浪费资源）
  - 文本为空/乱码 + 有内置图片 → `ocr-rebuild`（本地 RapidOCR 计算）
  - 其余 → `text-first`

### T0.2 多模态能力委托给调用方 agent ✅
- ✅ 管线不再直接调用任何 LLM API（无 `ANTHROPIC_API_KEY`、无 `--multimodal` 参数）
- ✅ 管线负责准备：`artifacts/pages/` 下的页面截图、tile 切片、region 区域裁剪
- ✅ 调用该 skill 的 agent 使用自身多模态视觉能力读取这些图片，补充 `final.md` 中纯文本无法表达的结构
- ✅ `pdf-agent-review-report.json` 为 agent 提供读图指导和质量检查依据

### T0.3 管线集成
- ✅ `build_page_data()` 路由逻辑简化为 `text-first` / `ocr-rebuild`
- ✅ `run_pdf_pipeline()` 无多模态参数
- ✅ CLI 无 `--multimodal` 参数
- ✅ `build_generic_final_markdown()` 显示每页的处理方式和 OCR 结构化结果
- ✅ 新增 `processing_approach`、`ocr_structured_md` 字段

---

## Phase 1：OCR 结构重建（不依赖 AI，纯 Python） ✅

**目标**：保留 RapidOCR 的 bounding box 数据，根据坐标重建文档结构。

### T1.1 保留 OCR 坐标数据
- **文件**: `pipeline_runner.py`
- **改动**: `ocr_image_text()` 当前只取 `item[1]`（文本），丢弃 `item[0]`（四边形坐标）和 `item[2]`（置信度）
- **新增函数**: `ocr_image_with_bbox(image_path) -> list[dict]`
  - 每个 dict: `{text, bbox: [[x1,y1],[x2,y2],[x3,y3],[x4,y4]], confidence, x_center, y_center, width, height}`
- **验收**: 跑一次测试 PDF，确认 OCR 结果包含坐标信息

### T1.2 OCR 行分组算法
- **文件**: `pipeline_runner.py`
- **改动**: `build_page_data()` 中 OCR 处理分支
- **新增函数**: `group_ocr_lines_into_rows(ocr_items: list[dict]) -> list[list[dict]]`
  - 按 y_center 分组，y 差值 < 行高阈值的视为同一行
  - 每行内按 x_center 从左到右排序
  - 返回按行组织的文本块列表
- **验收**: 同一行中的"功能名称 | 功能释义 | 交互说明"被归为一行

### T1.3 结构类型推断
- **文件**: `pipeline_runner.py`
- **新增函数**: `infer_block_role(line: list[dict]) -> str`
  - 居中大号文本（宽度 > 页面宽度 60%）→ `title`
  - 左侧短文本 + 右侧长文本 → `label_value_pair`（如"设计师：张逸欣"）
  - 水平排列 3+ 个短文本块 → `table_row`
  - 单个长文本块（> 15 字符）→ `paragraph`
  - 极短文本（< 4 字符）且无上下文 → `label`
  - 带序号的文本（"1."、"①"等）→ `list_item`
- **验收**: 分类结果对设置UE.pdf的 6 页合理

### T1.4 Markdown 输出重建
- **文件**: `pipeline_runner.py`
- **改动**: `build_generic_final_markdown()` 和 OCR 输出路径
- **改动点**:
  - 废弃 `compact_excerpt(text, 420)` 截断逻辑，输出完整 OCR 文本
  - 根据 T1.3 推断的角色生成对应 Markdown：
    - `title` → `## 标题`
    - `label_value_pair` → `**标签**: 值`
    - `table_row` → `| 单元格1 | 单元格2 | ... |`
    - `paragraph` → 普通段落
    - `list_item` → `- 列表项`
    - `label` → 保留，不加修饰
- **验收**: final.md 不再是碎片文字，而是有标题、表格、列表的排版文档

---

## Phase 2：基于分区的页面结构重建 ✅

**目标**：UE 规范文档遵循固定的 3 区布局（顶部标题 → 中间截图UI标签 → 底部功能描述），
按 y 坐标 + 内容关键词将每页 OCR 结果分区，输出为有结构的 Markdown。

### T2.1 基于 y 坐标的分区检测 ✅
- **文件**: `pipeline_runner.py`
- **思路**: UE 文档每页分 3 区：
  - 顶部 0–20% (y < 200): 页标题、设计师信息、红色标注
  - 中间 20–60% (y 200–600): 设备截图中的 UI 标签
  - 底部 60–100% (y >= 600): 编号功能描述 + 交互规则
- **新增函数**: `_detect_page_zone(y_pct, text) -> str`
  - 结合 y 坐标和内容关键词判断
  - 中间区文本若包含功能描述关键词（用户/点击/开启后/toast）→ 提升为 content
  - 短文本/颜色代码/OFF/ON 标签 → screenshot
- **新增函数**: `_tag_ocr_items_by_zone(ocr_items) -> list[dict]`
  - 为每个 OCR 项添加 `_zone` 标记
- **验收**: 设置UE.pdf 6 页的分区结果合理

### T2.2 分区 Markdown 生成 ✅
- **文件**: `pipeline_runner.py`
- **改动**: `_rebuild_ocr_to_markdown()` 重写为按区输出
- **输出顺序**:
  1. Top 区 → `## 标题`、`**标签**: 值`、普通段落
  2. Screenshot 区 → 引用块包裹（`> **[截图区域]** ...`），UI 标签用反引号
  3. Content 区 → `### 编号. 标题`、`- 描述`、表格
- **验收**: final.md 中截图文字与功能描述有清晰分隔

### T2.3 管线集成 ✅
- **改动**: `build_page_data()` 调用 `_tag_ocr_items_by_zone()` 替代旧的截图检测
- **改动**: 页面数据字典中 `_region_type` → `_zone`
- **验收**: 管线正常运行，不再生成旧版碎片化输出

### T2.4 多模态截图标注（agent 执行）✅
- ✅ 管线不再调用多模态 API，改为输出素材供 agent 使用
- ✅ 管线输出：`artifacts/pages/` 页面截图、`artifacts/pages/tiles/` 局部切片
- ✅ agent 使用说明：使用自身视觉能力读取截图，生成类似 `![设置界面截图](...)` + `> 此处为设置界面截图，显示XXX功能` 的标注
- ✅ 管线产出 `pdf-agent-review-report.json` 告知哪些页面需要视觉增补
- ✅ 降级策略：无 agent 介入时，管线仍以纯文本骨架输出完整 final.md

### T2.5 截图污染过滤 ✅
- **文件**: `pipeline_runner.py`
- **改动**: screenshot 区的 OCR 结果默认用引用块包裹
- **验收**: final.md 中截图内文字与正文有视觉区分

---

## Phase 3：箭头与修订标记检测 ✅

**目标**：识别 PDF 中的箭头、新增/删除/修改标记，并在 Markdown 中标注。

### T3.1 PDF 绘制对象提取 ✅
- **文件**: `pipeline_runner.py`
- **新增函数**: `_extract_pdf_drawing_annotations(page, page_width, page_height) -> list[dict]`
  - 提取 lines / rects / curves，坐标归一化到 0-1000
  - 颜色标注（红色 = 修订，蓝色 = 箭头，绿色 = 新增）
  - **注意**: 设置UE.pdf 中线条对象极少（仅 Page 4 有 6 条短线，均为渲染伪影），
    实际箭头检测降级为文本关键词推断
- **验收**: 绘制对象被提取（虽然该 PDF 无有效箭头）

### T3.2 箭头语义标注 ✅
- **文件**: `pipeline_runner.py`
- **新增函数**: `_annotate_arrows(drawing_items, ocr_items) -> list[str]`
  - 对每条有意义的线条（length > 20），在起终点附近找最近 OCR 文本
  - 生成：`→ 从「A」指向「B」`
- **降级策略**: 设置UE.pdf 无有效箭头 → 不输出箭头标注
- **验收**: 管线不报错，箭头标注为空时不输出该段落

### T3.3 修订关键词检测 ✅
- **文件**: `pipeline_runner.py`
- **新增函数**: `_detect_revision_markers(ocr_items) -> list[dict]`
  - 检测关键词：新增/增加/添加/删除/移除/修改/变更/调整/更新
  - 按 OCR item 级别检测（比全文检测更精确的上下文）
  - 输出到 final.md 的 `### 变更标记` 段落
  - 去重：相同文本只输出一次
- **验收**: 设置UE.pdf Page 2 和 Page 3 中的修订关键词被正确标注：
  - `[新增] 2023-10-07新增`
  - `[修改] 2023-10-07修改`
  - `[删除] 2023-10-07删除`

---

## Phase 4：分类过滤废弃 & 最终整合 ✅

**目标**：清理 Phase 1-3 引入后的代码，确保管线稳定闭合。

### T4.1 废弃 body/noise/uncertain 分类 ✅
- **文件**: `pipeline_runner.py`
- **已移除**: `_classify_text_line()`, `_parse_ocr_result_lines()`, `_build_classified_ocr_text()`, `_build_ocr_review_html()`, `_load_classification_decisions()`
- **已移除**: 相关常量 `_UI_NOISE_PATTERNS`, `_BODY_ACTION_MARKERS`
- **已更新**: `SKILL.md` 中关于分类过滤的描述 → 更新为 zone-based 重建
- **验收**: 管线正常运行，不再生成 ocr-review.html

### T4.2 统一 Markdown 输出格式 ✅
- **文件**: `pipeline_runner.py`
- **输出格式**:
  ```markdown
  ## 页面标题

  ### OCR 结构还原

  页标题 / 标注信息

  > **[截图区域]** 以下文字来自页面截图插图：
  >
  > UI 标签（截图内文字）

  功能描述段落...
  - **标签**: 值

  ### 变更标记

  - [新增] xxx
  - [修改] xxx
  - [删除] xxx
  ```
- **验收**: 设置UE.pdf 的 final.md 可以通读，不跳脱

### T4.3 回归测试 ✅
- **测试**: 用设置UE.pdf 完整跑一次
- **结果**: 管线正常完成，不再生成废弃文件，final.md 可读性明显改善

---

## 依赖与风险

| 风险 | 应对 |
| --- | --- |
| RapidOCR bounding box 精度不够 | 用 y 坐标容差分组，不依赖精确坐标 |
| pdfplumber 无法提取某些 PDF 的线条对象 | 降级为纯文本关键词检测（T3.3） |
| 多模态识别需求 | 管线输出截图/tile素材，调用方 agent 用自身视觉能力读图，不依赖外部 API key |
| 截图区域检测误判 | screenshot 区 OCR 结果默认用引用块包裹，与正文区分 |

## 执行顺序建议

1. ~~T0.1 → T0.3~~（Phase 0，自适应路由）
2. ~~T1.1 → T1.4~~（Phase 1，OCR 结构重建）
3. ~~T2.1 → T2.5~~（Phase 2，分区页面重建）
4. ~~T3.1 → T3.3~~（Phase 3，箭头 + 修订标记）
5. ~~T4.1 → T4.3~~（Phase 4，清理 + 整合）
6. ~~T2.4~~（多模态截图标注 → 已改为 agent 使用说明）
