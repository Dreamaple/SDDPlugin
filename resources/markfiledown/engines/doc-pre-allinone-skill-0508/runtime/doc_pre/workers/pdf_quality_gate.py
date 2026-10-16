from __future__ import annotations

import json
from typing import Any

from ..models import WorkingBundle

_SYSTEM_PROMPT = """你是一个 PDF 文档质量校验专家。你的任务是验证 final.md 是否准确反映了原始 PDF 页面的视觉结构。

## 校验维度（按页面类型）

### 通用检查（所有页面）
1. **完整性**：截图上的所有重要文字是否都在 final.md 中有对应
2. **阅读顺序**：final.md 的行文顺序是否符合页面的视觉阅读顺序
3. **无编造**：final.md 中没有截图中不存在的内容

### 设置树页（settings_tree）
4. **父子层级**：父功能 → 子功能 → 模式/时间配置的嵌套是否正确
   - 反例：把子项提升为顶级同级项
   - 反例：时间配置脱离其父节点

### 标注 UI 页（annotated_ui）
5. **标号映射**：每个字母/数字标号是否都有明确的"标号 → 控件 → 说明"映射
   - 标号文字不能"漂浮"在正文中而没有归属
6. **页面分区**：顶部导航、主视图、说明卡、底部规则是否正确分区

### 流程页（flow）
7. **流程方向**：箭头的方向、分支的归属是否正确
8. **状态迁移**：起始状态 → 触发动作 → 结果/异常的链是否完整

### 配置矩阵页（variant_matrix）
9. **维度识别**：比较维度（配置/版本/场景）是否正确识别
10. **显隐关系**：不同变体下的显示/隐藏关系是否准确

### 布局页（layout）
11. **空间分区**：上/左/右/下分区的模块归属是否正确

## 判定标准

- **pass**：所有关键检查项通过，或仅有不影响理解的微小差异
- **fail**：存在至少一个关键检查项失败（层级错误、标号遗漏、流程方向错误等）
- **pass-with-notes**：基本通过，但有若干待人工核查的非关键问题

## 输出要求
- 生成结构化的 quality-gate-report.json
- 对每个 fail 项给出具体的 fix_suggestion
- 不直接修改 final.md，只输出报告
"""


class PDFQualityGateWorker:
    """Write a quality verification request for the agent to validate final.md
    against page screenshots.

    This runs AFTER Stage 4 Agent Correction. The agent reads page screenshots
    alongside final.md, produces a structured pass/fail report per page covering
    hierarchy, callout mapping, flow direction, and spatial zones.

    If the overall verdict is 'fail', the agent also produces fix_suggestions
    that can be fed back into a targeted repair round.
    """

    def verify(self, bundle: WorkingBundle) -> None:
        """Write a quality gate request JSON for the agent to process."""
        final_md = bundle.final_markdown
        source_md = bundle.draft_markdown

        pages: list[dict[str, Any]] = []
        for record in bundle.page_records:
            tile_paths = record.tile_paths or []
            region_paths = record.region_paths or []

            # Infer page type from existing metadata or signals
            page_type = self._infer_page_type(record, bundle)

            page_info: dict[str, Any] = {
                "page_number": record.page_number,
                "screenshot": record.screenshot_path or "",
                "tiles": tile_paths,
                "regions": region_paths,
                "ocr_text": record.metadata.get("raw_text", "") if record.metadata else "",
                "needs_visual_review": record.needs_visual_review,
                "diagram_candidate": record.diagram_candidate,
                "page_type": page_type,
            }
            pages.append(page_info)

        # Build the checklist template based on detected page types
        checklist_template = self._build_checklist_template(pages)

        # Track repair round info
        repair_rounds = bundle.metadata.get("quality_gate", {}).get("repair_rounds", 0)

        request = {
            "kind": "quality-gate-request",
            "version": "1.0",
            "bundle_dir": str(bundle.bundle_dir),
            "final_md": final_md,
            "source_md": source_md,
            "pages": pages,
            "checklist_template": checklist_template,
            "repair_round": repair_rounds,
            "max_repair_rounds": 2,
            "system_prompt": _SYSTEM_PROMPT,
            "instructions": (
                "你正在执行 Stage 5 Quality Gate — 多模态最终校验。\n\n"
                "当前 final.md 已由脚本管线和 Stage 4 Agent Correction 处理过。\n"
                "请执行以下操作：\n\n"
                "1. 阅读 final.md 全文，了解当前文档结构\n"
                "2. 逐页查看 screenshot（全页截图），对比 final.md 中对应章节\n"
                "3. 对标记为 needs_visual_review=true 的页面重点检查\n"
                "4. 如果页面含 tiles 或 regions，用它们查看细节\n"
                "5. 对照 source.md 确认所有 OCR 文字都已保留\n"
                "6. 按 checklist_template 中的检查项逐页校验：\n"
                "   - 通用：完整性、阅读顺序、无编造\n"
                "   - settings_tree：父子层级嵌套正确\n"
                "   - annotated_ui：标号映射完整、页面分区正确\n"
                "   - flow：流程方向正确、状态迁移链完整\n"
                "   - variant_matrix：维度识别正确、显隐关系准确\n"
                "   - layout：空间分区正确、模块归属正确\n"
                "7. 对每个检查项给出 pass/fail/skip 判定和详细说明\n"
                "8. 对 fail 项给出具体的 fix_suggestion（说明需要在 final.md 的哪个位置做什么修改）\n"
                "9. 生成 quality-gate-report.json，包含：\n"
                "   - overall_verdict: pass / fail / pass-with-notes\n"
                "   - pages: 每页的 verdict、checks、issues、fix_suggestion\n"
                "   - summary: total_pages、passed、failed、skipped\n\n"
                "重要：\n"
                "- 这是通用校验步骤，对任何视觉型 PDF 都适用\n"
                "- 不要假设 OCR 顺序正确；以截图的空间结构作为结构依据\n"
                "- 以 OCR 作为措辞依据\n"
                "- 不要直接修改 final.md，只输出报告\n"
                f"- 当前是第 {repair_rounds + 1} 轮校验（最多 {2} 轮）\n"
            ),
        }

        output_path = bundle.bundle_dir / "quality-gate-request.json"
        output_path.write_text(
            json.dumps(request, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        bundle.metadata["quality_gate"] = {
            "status": "request-written",
            "request_path": "quality-gate-request.json",
            "page_count": len(pages),
            "review_page_count": sum(1 for p in pages if p["needs_visual_review"]),
            "repair_round": repair_rounds,
        }

    # ── Page type inference ──────────────────────────────────────────────

    def _infer_page_type(self, record, bundle: WorkingBundle) -> str:
        """Infer page type from existing metadata signals and text content."""
        # If the repair adapter already classified the page, use that
        metadata = record.metadata or {}
        raw_text = metadata.get("raw_text", "") or ""

        # Use the same heuristics as the repair adapter for consistency
        text_200 = raw_text[:200]

        if self._looks_like_settings_tree(text_200):
            return "settings_tree"
        if self._looks_like_annotated_ui(text_200):
            return "annotated_ui"
        if self._looks_like_flow(text_200):
            return "flow"
        if self._looks_like_variant_matrix(text_200):
            return "variant_matrix"
        if self._looks_like_layout(text_200):
            return "layout"
        if self._looks_like_table_of_contents(text_200):
            return "table_of_contents"
        if self._looks_like_demo_spec(text_200):
            return "demo_spec"

        return "generic"

    def _looks_like_settings_tree(self, text: str) -> bool:
        feature_hits = sum(
            token in text for token in (
                "设置", "自动", "自定义", "开关", "模式", "时间", "配置", "系统",
            )
        )
        return feature_hits >= 4 and any(
            token in text for token in ("设置页", "设置", "配置", "系统")
        )

    def _looks_like_annotated_ui(self, text: str) -> bool:
        import re
        callout_tokens = re.findall(r"\b[a-z]\b", text.lower())
        has_ui_markers = any(
            token in text for token in ("标注", "说明", "按钮", "控件", "页面", "界面", "tab", "dock")
        )
        has_callout_markers = len(set(callout_tokens)) >= 3 or any(
            token in text for token in ("标号", "callout", "红框", "注释")
        )
        return has_ui_markers and has_callout_markers

    def _looks_like_flow(self, text: str) -> bool:
        flow_tokens = sum(
            token in text for token in ("点击", "进入", "返回", "跳转", "滑动", "流程", "状态", "成功", "失败")
        )
        return flow_tokens >= 3

    def _looks_like_variant_matrix(self, text: str) -> bool:
        import re
        matrix_tokens = sum(
            token in text for token in (
                "配置", "低配", "高配", "版本", "方案", "场景", "有", "无", "显示", "隐藏",
            )
        )
        variant_refs = len(set(re.findall(r"\b\d{2}-\d+\b", text)))
        return matrix_tokens >= 4 and variant_refs >= 2

    def _looks_like_layout(self, text: str) -> bool:
        return any(keyword in text for keyword in ("页面布局", "Page Layout", "分区", "布局分区"))

    def _looks_like_table_of_contents(self, text: str) -> bool:
        return any(keyword in text for keyword in ("目录", "Content", "目录页"))

    def _looks_like_demo_spec(self, text: str) -> bool:
        import re
        page_refs = set(re.findall(r"\b\d{2}-\d+\b", text))
        if len(page_refs) < 2:
            return False
        if "【" not in text or "】" not in text:
            return False
        return any(marker in text for marker in ("点击", "上滑", "下滑", "左滑", "右滑", "点击后", "toast"))

    # ── Checklist template builder ───────────────────────────────────────

    def _build_checklist_template(self, pages: list[dict[str, Any]]) -> dict[str, list[dict[str, str]]]:
        """Build a type-specific checklist template.

        Returns a dict mapping page_type → list of check items.
        """
        type_checklists: dict[str, list[dict[str, str]]] = {}

        # Determine which page types are present
        present_types = set(p["page_type"] for p in pages)

        # Generic checks (always present)
        type_checklists["generic"] = [
            {
                "category": "completeness",
                "description": "完整性：截图上的所有重要文字是否都在 final.md 中有对应",
            },
            {
                "category": "reading_order",
                "description": "阅读顺序：final.md 的行文顺序是否符合页面的视觉阅读顺序",
            },
            {
                "category": "no_fabrication",
                "description": "无编造：final.md 中没有截图中不存在的内容",
            },
        ]

        # Settings tree checks
        if "settings_tree" in present_types:
            type_checklists["settings_tree"] = type_checklists["generic"] + [
                {
                    "category": "hierarchy",
                    "description": "父子层级：父功能 → 子功能 → 模式/时间配置的嵌套是否正确，子项未被提升为顶级",
                },
                {
                    "category": "automation_feedback",
                    "description": "自动化反馈：toast/TTS/异常提示是否从设置树主体中正确拆分",
                },
            ]

        # Annotated UI checks
        if "annotated_ui" in present_types:
            type_checklists["annotated_ui"] = type_checklists["generic"] + [
                {
                    "category": "callout_mapping",
                    "description": "标号映射：每个字母/数字标号都有明确的'标号 → 控件 → 说明'映射，标号文字不漂浮",
                },
                {
                    "category": "zone_partitioning",
                    "description": "页面分区：顶部导航、主视图、说明卡、底部规则是否正确分区",
                },
            ]

        # Flow checks
        if "flow" in present_types:
            type_checklists["flow"] = type_checklists["generic"] + [
                {
                    "category": "flow_direction",
                    "description": "流程方向：箭头的方向、分支的归属是否正确",
                },
                {
                    "category": "state_transition",
                    "description": "状态迁移：起始状态 → 触发动作 → 结果/异常的链是否完整",
                },
            ]

        # Variant matrix checks
        if "variant_matrix" in present_types:
            type_checklists["variant_matrix"] = type_checklists["generic"] + [
                {
                    "category": "dimension_identification",
                    "description": "维度识别：比较维度（配置/版本/场景）是否正确识别",
                },
                {
                    "category": "visibility_rules",
                    "description": "显隐关系：不同变体下的显示/隐藏关系是否准确",
                },
            ]

        # Layout checks
        if "layout" in present_types:
            type_checklists["layout"] = type_checklists["generic"] + [
                {
                    "category": "spatial_zones",
                    "description": "空间分区：上/左/右/下分区的模块归属是否正确",
                },
            ]

        return type_checklists
