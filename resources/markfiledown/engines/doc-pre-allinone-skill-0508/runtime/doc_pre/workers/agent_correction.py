from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..models import PageRecord, WorkingBundle

_SYSTEM_PROMPT = """你是一个文档质量校验与修正专家。

你的任务：对比 PDF 页面截图与已生成的 final.md，找出遗漏、错误或不准确的内容，并直接修正 final.md。

修正原则：
1. **完整性校验**：逐页对比截图和 final.md，确认每个页面上的所有重要信息都已体现在 final.md 中
2. **不丢失原文**：source.md 中已提取的文字内容必须保留在 final.md 中，不能因视觉修正而删除
3. **结构优先于 OCR 顺序**：当 OCR 线性顺序与页面视觉分区、缩进、容器、箭头、标号归属冲突时，以截图中的空间结构为准重新组织
4. **补充遗漏**：如果截图上存在但 final.md 未体现的信息（控件说明、标注文字、规则说明、提示文案等），必须补充到 final.md 的对应章节
5. **纠正错误**：如果 final.md 中的描述与截图不一致，以截图为准进行修正
6. **允许章节级重构**：对于视觉型页面，允许在保留总体章节框架的前提下，重写该页面小节的内部结构，以恢复正确的标号映射、父子层级、流程关系和配置矩阵
7. **不编造**：不要添加截图中不存在或 source.md 中未提及的内容
8. **显式保留未决点**：若个别标号或层级仍无法安全判断，集中列入待人工核查问题，而不是默认拍平或遗漏

输出要求：
- 直接修改 final.md 文件，覆盖原内容
- 在修改处附近添加 `<!-- agent-corrected: 简要说明修正原因 -->` 注释标记
- 完成后删除本请求文件
"""


class AgentCorrectionWorker:
    """Write a multi-modal correction request for the agent to verify and fix final.md.

    This runs AFTER the initial final.md is generated. The agent reads page
    screenshots alongside final.md, identifies missing/incorrect content,
    and writes a corrected final.md.
    """

    def correct(self, bundle: WorkingBundle) -> None:
        """Write a correction request JSON for the agent to process."""
        final_md = bundle.final_markdown
        source_md = bundle.draft_markdown

        pages: list[dict[str, Any]] = []
        for record in bundle.page_records:
            tile_paths = record.tile_paths or []
            region_paths = record.region_paths or []

            page_info: dict[str, Any] = {
                "page_number": record.page_number,
                "screenshot": record.screenshot_path or "",
                "tiles": tile_paths,
                "regions": region_paths,
                "ocr_text": record.metadata.get("raw_text", "") if record.metadata else "",
                "needs_visual_review": record.needs_visual_review,
            }
            pages.append(page_info)

        request = {
            "kind": "multimodal-correction-request",
            "version": "1.0",
            "bundle_dir": str(bundle.bundle_dir),
            "final_md": final_md,
            "source_md": source_md,
            "pages": pages,
            "system_prompt": _SYSTEM_PROMPT,
            "instructions": (
                "你正在执行 Stage 4 Agent Multi-modal Correction。\n\n"
                "当前 final.md 已由脚本 pipeline 生成。请执行以下操作：\n\n"
                "1. 阅读 final.md 全文，了解当前文档结构\n"
                "2. 逐页查看 screenshot（全页截图），对比 final.md 中对应章节\n"
                "3. 对标记为 needs_visual_review=true 的页面重点检查\n"
                "4. 如果页面含 tiles 或 regions，用它们查看细节\n"
                "5. 对照 source.md 确认所有 OCR 提取的文字都已保留\n"
                "6. 先做页面结构抽取，再做 markdown 修正：识别 page type、视觉分区、标号映射、父子层级、流程关系、配置矩阵\n"
                "7. 对带字母/数字标号的 UI 说明页，必须输出明确的‘标号 -> 控件/区域 -> 说明’映射，不能让标号文字漂浮\n"
                "8. 对设置页，必须先恢复树结构；例如父功能、子功能、模式、时间配置不可被 OCR 顺序拍平成同级\n"
                "9. 发现遗漏或错误时，可对该页面小节进行章节级重构，而不是只做局部补丁\n"
                "10. 修正后用 Markdown 注释 <!-- agent-corrected: 原因 --> 标记修改处\n"
                "11. 若仍有无法安全判断的标号归属或层级关系，集中写入待人工核查问题\n"
                "12. 如果 final.md 质量已足够，无需修改，直接删除本文件\n\n"
                "重要：这是通用校验步骤，对任何视觉型 PDF 都适用。"
                "不要假设 OCR 顺序正确；应以截图的空间结构作为结构依据，以 OCR 作为措辞依据。"
            ),
        }

        output_path = bundle.bundle_dir / "multimodal-correction-request.json"
        output_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        bundle.metadata["agent_correction"] = {
            "status": "request-written",
            "request_path": "multimodal-correction-request.json",
            "page_count": len(pages),
            "review_page_count": sum(1 for p in pages if p["needs_visual_review"]),
        }
