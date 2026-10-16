from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import PageRecord, WorkingBundle

_SYSTEM_PROMPT = """你是一个文档排版还原专家。你将看到一张文档页面截图和它的 OCR 文字。
任务：把页面内容还原为结构化的 Markdown，保留真正的文档正文，忽略纯视觉示例。

规则：
1. 先识别页面类型：目录页 / 变更表 / 标注规则页 / 信息架构页 / 页面布局页 / 标注 UI 页 / 设置树页 / 流程页 / 配置矩阵页 / 结束页。
2. 先做页面结构抽取，再写 Markdown：识别标题、子标题、正文、表格、视觉分区、标号映射、父子层级、流程关系、配置差异。
3. 页面结构以 screenshot / tiles / regions 为准；文字措辞以 OCR 为准。
4. 当 OCR 顺序与页面视觉结构冲突时，以视觉结构为准重排。
5. 识别编号或字母标注（如 a/b/c/d 或 1/2/3）的说明文字，并恢复为明确映射。
6. 识别表格内容，还原为 Markdown 表格。
7. 如果页面是 UI 截图标注说明，必须保留标号说明，并把“标号 -> 控件/区域 -> 说明”系统化输出。
8. 如果页面是设置页，必须恢复树结构；子功能、模式、时间配置、展开项不能被拍平成同级列表。
9. 忽略纯视觉示例：手势图标说明、色块/颜色说明、流程图控件示例、交互热区示例、变更标注示例框。
10. 如果页面只有目录/导航栏而没有正文内容，保留目录结构即可。
11. 不要编造不存在的内容。
12. 如果有无法安全判断的点，集中列入“待人工核查问题”。

**UI 截图还原（关键）：**
当页面包含带编号标注的 UI 界面截图时，必须优先恢复这四类结构：
- 页面分区（主视图 / 侧边说明 / 底部规则 / 变体区）
- 标号映射（标号 -> 指向控件 -> 说明）
- 状态规则（默认态 / 开启态 / 异常态 / 退出条件）
- 配置差异（不同变体、不同配置下的显隐关系）

如结构明确，可使用 ASCII art 辅助；但 ASCII art 不能替代标号映射表和层级树。

输出要求：纯 Markdown 文本，不需要任何解释或前缀。"""


class MultimodalReconstructionWorker:
    """Write a multimodal reconstruction request for agent visual processing.

    The agent (Claude Code) reads the request file, uses its own vision
    capabilities to process screenshots and tiles, then writes the result
    back to final.md.
    """

    def reconstruct(self, bundle: WorkingBundle) -> None:
        """Write a reconstruction request JSON for the agent to process."""
        source_md = bundle.draft_markdown

        pages: list[dict[str, Any]] = []
        for record in bundle.page_records:
            tile_grid = record.metadata.get("tile_grid") if record.metadata else None
            is_tiled = bool(tile_grid and isinstance(tile_grid, list) and len(tile_grid) == 2)

            tile_paths = record.tile_paths or []
            page_info: dict[str, Any] = {
                "page_number": record.page_number,
                "screenshot": record.screenshot_path or "",
                "ocr_text": record.metadata.get("raw_text", "") if record.metadata else "",
                "is_tiled": is_tiled,
                "tiles": tile_paths,
            }
            if is_tiled:
                page_info["tile_grid"] = tile_grid

            pages.append(page_info)

        request = {
            "kind": "multimodal-reconstruction-request",
            "version": "1.0",
            "bundle_dir": str(bundle.bundle_dir),
            "source_md": source_md,
            "pages": pages,
            "system_prompt": _SYSTEM_PROMPT,
            "instructions": (
                "对每个 page，使用视觉能力读取 screenshot（全页截图）"
                "以及 tiles（分块高清图，如存在）。按以下规则重建：\n\n"
                "1. 未分块的页面：直接读取 screenshot + ocr_text，但必须先抽取页面 schema（page type、zones、hierarchy、callouts、flows、variants），再输出 Markdown。\n"
                "2. 已分块的页面 (is_tiled=true)：\n"
                "   a. 先读取 screenshot 理解全局结构（流程图、链路、信息架构、主区/侧栏/底部规则）。\n"
                "   b. 按 tile 列表顺序读取每个 tile 高清图。\n"
                "   c. 对每个 tile，结合全页截图的上下文，从高清截图中提取详细内容。\n"
                "   d. 按行优先顺序 (r0c0 → r0c1 → r1c0 → ...) 拼接各 tile 结果。\n"
                "   e. 拼接时注意去除相邻 tile 之间的重复内容，但不要消解真实的父子层级和标号映射。\n\n"
                "3. 对带编号/字母标注的 UI 页，必须输出‘标号 -> 控件/区域 -> 说明’映射。\n"
                "4. 对设置页，必须恢复树结构；例如父功能、模式、自定义时间、子配置项不能被平铺为同级列表。\n"
                "5. **UI 截图可用 ASCII art 辅助还原**，但不能替代标号映射表、层级树和状态规则。\n"
                "6. 结构优先级：空间分区/箭头/缩进/容器 > OCR 顺序。\n"
                "7. 如果某个标号归属或父子层级仍无法确认，在文末集中列入‘待人工核查问题’。\n"
                "8. 将所有页面的重建结果写入 final.md，替换当前内容。\n"
                "9. 完成后删除本文件 (multimodal-reconstruction-request.json)。"
            ),
        }

        output_path = bundle.bundle_dir / "multimodal-reconstruction-request.json"
        output_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        bundle.metadata["multimodal_reconstruction"] = {
            "status": "request-written",
            "request_path": "multimodal-reconstruction-request.json",
            "page_count": len(pages),
            "tiled_page_count": sum(1 for p in pages if p["is_tiled"]),
        }
