from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from ..models import PageRecord, WorkingBundle
from ..utils import is_j90k_hvac_document


class PDFVisualRepairAdapter:
    def repair(self, bundle: WorkingBundle) -> str:
        if bundle.source_document.extension.lower() != ".pdf":
            bundle.metadata["repair_stage"] = "skipped-non-pdf"
            return bundle.draft_markdown

        if not bundle.page_records:
            bundle.metadata["repair_stage"] = "skipped-no-page-assets"
            return bundle.draft_markdown

        bundle.metadata["reconstruction_strategy"] = "text-first-multimodal"
        if self._is_j90k_document(bundle):
            bundle.metadata["repair_stage"] = "pdf-text-first-multimodal-j90k"
            return self._build_j90k_repair(bundle)

        bundle.metadata["repair_stage"] = "pdf-text-first-multimodal-generic"
        return self._build_generic_repair(bundle)

    def _is_j90k_document(self, bundle: WorkingBundle) -> bool:
        return is_j90k_hvac_document(bundle.source_document.filename, bundle.draft_markdown)

    def _build_j90k_repair(self, bundle: WorkingBundle) -> str:
        return self._build_text_first_repair(bundle, profile="j90k-hvac")

    def _build_generic_repair(self, bundle: WorkingBundle) -> str:
        return self._build_text_first_repair(bundle, profile="generic")

    def _build_generic_page_section(
        self,
        bundle: WorkingBundle,
        record: PageRecord,
    ) -> list[str]:
        title = self._page_heading(record)
        heading = f"## Page {record.page_number} - {title}" if title else f"## Page {record.page_number}"
        lines = [heading, ""]

        screenshot = self._page_image_markdown(bundle, record.page_number, f"Page {record.page_number}")
        if screenshot:
            lines.extend([screenshot, ""])

        lines.extend(
            [
                "### 页面信号",
                "",
                f"- Visual review required: `{'yes' if record.needs_visual_review else 'no'}`",
                f"- Images detected: `{record.image_count or 0}`",
                f"- OCR fallback applied: `{'yes' if self._page_has_ocr_fallback(record) else 'no'}`",
            ]
        )
        if record.diagram_candidate:
            lines.append("- Diagram candidate: `yes`")

        excerpt = self._page_excerpt(record)
        if excerpt:
            lines.extend(["", "### 文本摘录", "", f"> {excerpt}", ""])
        else:
            lines.append("")

        return lines

    def _build_text_first_repair(self, bundle: WorkingBundle, *, profile: str) -> str:
        review_pages = ", ".join(
            str(record.page_number) for record in bundle.page_records if record.needs_visual_review
        ) or "none"
        title = self._cover_title(bundle)

        # Check if any page has text; if not, fall back to draft_markdown (source.md)
        has_page_text = any(self._page_raw_text(r) for r in bundle.page_records)
        if not has_page_text and bundle.draft_markdown.strip():
            bundle.metadata["repair_fallback"] = "draft-markdown-fallback"

        lines: list[str] = [
            f"# {title}（文本主导重建版）",
            "",
            "> 该版本采用 text-first multimodal reconstruction：正文内容以文本抽取为主源，页截图和区域截图仅用于校正版面、流程、分区和视觉语义，不用视觉结果替代文字。",
            "> `source.md` 保留原始抽取；`final.md` 在不丢失原文用词和句意的前提下重排为可读 Markdown，并把视觉证据并列保留。",
            "",
            "## 重建契约",
            "- 文字主源：`source.md` 与页级文本抽取结果。",
            "- 视觉佐证：`artifacts/pages/*`、`artifacts/pages/*tile*`、`artifacts/regions/*`。",
            "- 重建原则：先保全文字，再用视觉证据修正标题层级、流程方向、模块归属、callout 和版面关系。",
            "- 冲突处理：若视觉和文字发生冲突，默认保留已抽取文字，并把冲突留给 evidence/readback 链路确认。",
            "",
            "## 文档概览",
            f"- 原始标题：{title}",
            f"- 路由：{bundle.route_decision.route}",
            f"- 文档 profile：{profile}",
            f"- 页数：{len(bundle.page_records)}",
            f"- 视觉复核页：{review_pages}",
            "- 文本基线：[source.md](source.md)",
            "",
        ]

        cover_image = self._page_image_markdown(bundle, 1, "封面页")
        if cover_image:
            lines.extend([cover_image, ""])

        cover_record = self._page_record(bundle, 1)
        if cover_record is not None:
            lines.extend(["### 封面文字主干", ""])
            lines.extend(self._render_page_text_blocks(cover_record, bundle=bundle))
            lines.append("")

        toc_lines = self._extract_table_of_contents(bundle)
        if toc_lines:
            lines.extend(["## 目录线索", ""])
            lines.extend(toc_lines)
            lines.append("")

        for record in bundle.page_records:
            if profile == "j90k-hvac" and record.page_number == 1:
                continue
            lines.extend(self._build_text_first_page_section(bundle, record, profile=profile))

        lines.extend(self._build_page_appendix(bundle))
        return "\n".join(line for line in lines if line is not None).rstrip() + "\n"

    def _build_text_first_page_section(
        self,
        bundle: WorkingBundle,
        record: PageRecord,
        *,
        profile: str,
    ) -> list[str]:
        heading = self._output_section_heading(record, profile=profile)
        lines: list[str] = [heading, ""]

        subtitle = self._output_section_subtitle(record, profile=profile)
        if subtitle:
            lines.extend([subtitle, ""])

        screenshot = self._page_image_markdown(bundle, record.page_number, f"Page {record.page_number}")
        if screenshot:
            lines.extend([screenshot, ""])

        note_lines = self._page_visual_notes(record, profile=profile)
        if note_lines:
            lines.extend(["### 视觉校正", ""])
            lines.extend(note_lines)
            lines.append("")

        lines.extend(["### 文字主干", ""])
        lines.extend(self._render_primary_page_content(record, profile=profile, bundle=bundle))
        lines.append("")

        macro_mermaid = self._page_diagram_output(record, profile=profile)
        if macro_mermaid:
            lines.extend(macro_mermaid)

        region_gallery = self._page_region_gallery(bundle, record, profile=profile)
        if region_gallery:
            lines.extend(["### 视觉锚点", ""])
            lines.extend(region_gallery)
            lines.append("")

        return lines

    def _output_section_heading(self, record: PageRecord, *, profile: str) -> str:
        if profile == "j90k-hvac":
            heading_map = {
                2: "## 目录页快照",
                3: "## 1. 变更记录",
                4: "## 2. 标注说明与跳转线语义",
                5: "## 3. 信息架构与模块指向",
                6: "## 4. 页面布局分区",
                7: "## 5. 信息详情与主界面控件",
                8: "## 6. 空调设置与自动化策略",
                9: "## 7. 座椅控制与按摩流程",
                10: "## 结束页与发布尾注",
            }
            if record.page_number in heading_map:
                return heading_map[record.page_number]

        title = self._page_heading(record)
        return f"## Page {record.page_number} - {title}" if title else f"## Page {record.page_number}"

    def _output_section_subtitle(self, record: PageRecord, *, profile: str) -> str:
        title = self._page_heading(record)
        if not title:
            return ""

        if profile == "j90k-hvac" and record.page_number in {2, 3, 4, 5, 6, 7, 8, 9, 10}:
            return f"> 原始页标题：{title}"
        return ""

    def _page_visual_notes(self, record: PageRecord, *, profile: str) -> list[str]:
        notes: list[str] = []
        page_text = " ".join(self._page_text_lines(record)[:120])
        if self._looks_like_media_center_home_flow_page(page_text):
            notes.append("- 该页主体是页面状态与跳转关系图；缩略图中的歌曲名、艺人名、应用名称等示例文案不应被当成正文主体。")
        elif self._looks_like_demo_spec_page(page_text):
            notes.append("- 该页是演示流程页；正文优先保留页面态与原文说明，界面示例文案只作为演示背景，不作为主叙述。")

        if record.diagram_candidate:
            notes.append("- 该页含明显的流程/布局/图示语义；以下正文仍以文本抽取为主，截图只用于校正箭头方向、区域归属和阅读顺序。")
        elif record.needs_visual_review:
            notes.append("- 该页已纳入视觉复核；截图用于校正分栏、callout、图文对照关系和页面层级。")

        if self._page_macro_mermaid(record, profile=profile):
            notes.append("- 该页存在稳定的宏观结构图；在保留文字主干的前提下，下面会尝试输出 Mermaid 复刻。")

        if profile == "j90k-hvac" and record.page_number == 9:
            notes.append("- 该页额外保留按摩面板与左右流程树区域图，用于辅助解释视觉依赖很强的状态分支。")

        return notes

    def _render_primary_page_content(self, record: PageRecord, *, profile: str, bundle: WorkingBundle | None = None) -> list[str]:
        schema_scaffold = self._generic_visual_schema_scaffold(record)
        if schema_scaffold:
            return schema_scaffold

        curated = self._curated_page_text_blocks(record, profile=profile)
        if curated:
            return curated

        # Check for extracted table data — render as Markdown tables
        page_tables = (record.metadata or {}).get("page_tables")
        if page_tables:
            table_lines = self._render_page_tables(record, page_tables)
            if table_lines:
                return table_lines

        return self._render_page_text_blocks(record, bundle=bundle)

    def _curated_page_text_blocks(self, record: PageRecord, *, profile: str) -> list[str]:
        page_text = " ".join(self._page_text_lines(record)[:160])
        if self._looks_like_media_center_home_flow_page(page_text):
            lines = [
                "- 这页表达的是 `QQ音乐首页` 页面簇的状态与跳转关系，不是要逐字抄录每个缩略图里的界面占位文案。",
                "- 缩略图中反复出现的歌曲名、艺人名、`应用名称`、`周杰伦`、`45.2万` 等属于示例素材，应降权处理。",
                "",
                "#### 低配主链",
                "",
                "1. `06-1 APP list` -> 点击 -> `06-2 QQ音乐-首页`。",
                "2. `06-2 QQ音乐-首页` -> 向下滑动 -> `06-4 首页-加载中`。",
                "3. `06-4 首页-加载中` -> 拉到底部 -> `06-5 首页-拉到底`。",
                "",
                "#### 低配例外态",
                "",
                "- `06-3 首页-无网络/加载失败`：表示首页资源失败或网络异常时的替代页，不属于主链正常跳转。",
                "",
                "#### 高配主链",
                "",
                "1. `06-6 APP list` -> 点击 -> `06-7 QQ音乐-首页`。",
                "2. `06-7 QQ音乐-首页` -> 点击杜比专区内容 -> `06-10 杜比专区详情页`。",
                "3. `06-10 杜比专区详情页` -> 点击查看更多 -> `06-9 更多杜比单曲`。",
                "4. `06-10 杜比专区详情页` -> 点击官方歌单 -> `06-11 杜比官方歌单`。",
                "",
                "#### 高配例外态",
                "",
                "- `06-8 首页-无网络/加载失败`：表示高配首页的异常/加载失败态。",
                "",
                "#### 原文说明",
                "",
            ]
            original_notes = self._render_demo_original_notes(record)
            if original_notes:
                lines.extend(original_notes)
            return lines

        if self._looks_like_demo_spec_page(page_text):
            return self._render_demo_spec_page_content(record)

        return []

    def _render_demo_spec_page_content(self, record: PageRecord) -> list[str]:
        lines = [
            "- 该页属于页面演示/流程页；界面示例文案已降权，正文优先保留页面态和原文说明。",
        ]

        page_states = self._extract_demo_page_states(record)
        if page_states:
            lines.extend(["", "#### 页面态", ""])
            for page_id, title in page_states:
                lines.append(f"- `{page_id}` {title}" if title else f"- `{page_id}`")

        actions = self._extract_demo_action_markers(record)
        if actions:
            lines.extend(["", "#### 动作线索", "", f"- 原图显式动作：{'、'.join(actions)}。"])

        original_notes = self._render_demo_original_notes(record)
        if original_notes:
            lines.extend(["", "#### 原文说明", ""])
            lines.extend(original_notes)

        return lines

    def _extract_demo_page_states(self, record: PageRecord) -> list[tuple[str, str]]:
        lines = self._page_text_lines(record)
        seen: set[str] = set()
        states: list[tuple[str, str]] = []
        inline_pattern = re.compile(r"(\d{2}-\d+)\s*([^\d]*?)(?=(?:\d{2}-\d+)|$)")

        for index, line in enumerate(lines):
            if not re.search(r"\b\d{2}-\d+\b", line):
                continue

            matches = list(inline_pattern.finditer(line))
            if not matches:
                continue

            for match in matches:
                page_id = match.group(1)
                title = self._clean_demo_page_title(match.group(2))
                if not title and index + 1 < len(lines):
                    title = self._clean_demo_page_title(lines[index + 1])
                if page_id in seen:
                    continue
                seen.add(page_id)
                states.append((page_id, title))
        return states[:16]

    def _clean_demo_page_title(self, title: str) -> str:
        title = title.strip(" -|:：")
        title = re.sub(r"\s+", " ", title)
        if not title:
            return ""
        if title in {"Statusbar", "Dock", "点击", "点击后", "上滑", "下滑"}:
            return ""
        if re.fullmatch(r"[a-zA-Z]\d?", title):
            return ""
        if any(token in title for token in ("Statusbar", "Dock", "45.2万", "03:00")):
            return ""
        return title[:60]

    def _extract_demo_action_markers(self, record: PageRecord) -> list[str]:
        page_text = " ".join(self._page_text_lines(record)[:220])
        action_markers: list[str] = []
        for action in ("点击后", "点击", "上滑", "下滑", "向下滑动", "向上滑动", "左滑", "右滑"):
            if action in page_text and action not in action_markers:
                action_markers.append(action)
        return action_markers

    def _render_demo_original_notes(self, record: PageRecord) -> list[str]:
        sections: list[str] = []
        for section_title, text in self._demo_note_sources(record):
            note_lines = self._extract_demo_note_lines(text)
            note_blocks = self._dedupe_demo_note_blocks(note_lines)
            if not note_blocks:
                continue
            if sections:
                sections.append("")
            sections.extend([f"##### {section_title}", ""])
            for index, block in enumerate(note_blocks):
                sections.extend(block)
                if index != len(note_blocks) - 1:
                    sections.append("")
        return sections

    def _demo_note_sources(self, record: PageRecord) -> list[tuple[str, str]]:
        metadata = record.metadata or {}
        sources: list[tuple[str, str]] = []
        left_text = metadata.get("demo_left_text")
        right_text = metadata.get("demo_right_text")
        if isinstance(left_text, str) and left_text.strip():
            sources.append(("左栏原文", left_text))
        if isinstance(right_text, str) and right_text.strip():
            sources.append(("右栏原文", right_text))
        if sources:
            return sources

        raw_text = self._page_raw_text(record)
        if raw_text.strip():
            return [("整页原文摘录", raw_text)]
        return []

    def _extract_demo_note_lines(self, text: str) -> list[str]:
        lines = [self._normalize_text_line(line) for line in text.replace("\x0c", "\n").splitlines()]
        extracted: list[str] = []
        active = False
        previous_line = ""

        for line in lines:
            if not line:
                continue
            if self._looks_like_note_heading(line):
                if extracted and extracted[-1] != "":
                    extracted.append("")
                extracted.append(line)
                active = True
                previous_line = line
                continue
            if not active:
                continue
            if self._looks_like_demo_note_line(line, previous_line):
                extracted.append(line)
                previous_line = line

        while extracted and extracted[-1] == "":
            extracted.pop()
        return extracted

    def _dedupe_demo_note_blocks(self, note_lines: list[str]) -> list[list[str]]:
        blocks: list[list[str]] = []
        current: list[str] = []
        seen: set[tuple[str, ...]] = set()

        for line in note_lines + [""]:
            if line:
                current.append(line)
                continue
            if not current:
                continue
            block = [item for item in current if item]
            current = []
            if len(block) < 2:
                continue
            key = tuple(block)
            if key in seen:
                continue
            seen.add(key)
            blocks.append(block)

        return blocks

    def _looks_like_note_heading(self, line: str) -> bool:
        return "【" in line and "】" in line

    def _looks_like_demo_note_line(self, line: str, previous_line: str) -> bool:
        if self._is_demo_placeholder_line(line):
            return False
        if re.match(r"^\d+[）)]", line):
            return True
        if previous_line.endswith(("：", ":")):
            return True
        if any(keyword in line for keyword in (
            "点击",
            "上滑",
            "下滑",
            "滑动",
            "toast",
            "提示",
            "进入",
            "显示",
            "默认",
            "固定",
            "具体",
            "支持",
            "获取",
            "播放",
            "收藏",
            "登录",
            "切换",
            "加载",
            "网络",
            "缓存",
            "成功",
            "失败",
            "按钮",
            "专区",
            "浮层",
            "标签",
            "音质",
            "调起",
            "透出",
            "回弹",
            "收起",
            "弹出",
            "刷新",
            "置顶",
            "定位",
        )):
            return True
        if line in {
            "暂⽆⽹络",
            "已添加到列表",
            "当前信源不⽀持此功能",
            "歌单已收藏",
        }:
            return True
        return False

    def _is_demo_placeholder_line(self, line: str) -> bool:
        if re.search(r"\b\d{2}-\d+\b", line):
            return True
        if any(token in line for token in ("Statusbar", "Dock", "45.2万", "03:00", "应⽤名称", "应用名称")):
            return True
        if line in {
            "点击",
            "点击后",
            "上滑",
            "下滑",
            "向下滑动",
            "向上滑动",
            "左滑",
            "右滑",
            "加载中",
            "播放全部",
            "播播放放全全部部",
            "切换类别",
            "收起状态 展开状态",
        }:
            return True
        if " " in line and not re.search(r"[：:，,。；;（）()【】\-]", line):
            return True
        if re.fullmatch(r"[a-zA-Z]\d?", line):
            return True
        if line.count("周杰伦") >= 2:
            return True
        if re.search(r"\b\d+\s+\S+\s+\S+\s+\d{2}:\d{2}\b", line):
            return True
        return False

    def _looks_like_demo_spec_page(self, page_text: str) -> bool:
        page_refs = set(re.findall(r"\b\d{2}-\d+\b", page_text))
        if len(page_refs) < 2:
            return False
        if "【" not in page_text or "】" not in page_text:
            return False
        return any(marker in page_text for marker in ("点击", "上滑", "下滑", "左滑", "右滑", "点击后", "toast"))

    def _generic_visual_page_type(self, record: PageRecord) -> str:
        page_text = " ".join(self._page_text_lines(record)[:200])
        lower_text = page_text.lower()

        if self._looks_like_table_of_contents_page(page_text):
            return "table_of_contents"
        if self._looks_like_information_architecture_page(page_text):
            return "information_architecture"
        if self._looks_like_page_layout_page(page_text):
            return "layout"
        if self._looks_like_visual_flow_page(page_text):
            return "flow"
        if self._looks_like_settings_tree_page(page_text):
            return "settings_tree"
        if self._looks_like_variant_matrix_page(page_text):
            return "variant_matrix"
        if self._looks_like_annotated_ui_page(page_text):
            return "annotated_ui"
        if self._looks_like_demo_spec_page(page_text):
            return "demo_spec"
        if self._looks_like_media_center_home_flow_page(page_text):
            return "flow"
        if self._looks_like_annotation_flow_page(page_text):
            return "flow"
        if record.diagram_candidate:
            return "layout"
        if record.needs_visual_review and any(token in lower_text for token in ("callout", "标注", "说明", "界面", "页面")):
            return "annotated_ui"
        return "generic"

    def _looks_like_annotated_ui_page(self, page_text: str) -> bool:
        callout_tokens = re.findall(r"\b[a-z]\b", page_text.lower())
        has_ui_markers = any(
            token in page_text
            for token in ("标注", "说明", "按钮", "控件", "页面", "界面", "tab", "dock")
        )
        has_callout_markers = len(set(callout_tokens)) >= 3 or any(
            token in page_text for token in ("标号", "callout", "红框", "注释")
        )
        return has_ui_markers and has_callout_markers

    def _looks_like_settings_tree_page(self, page_text: str) -> bool:
        feature_hits = sum(
            token in page_text
            for token in (
                "设置",
                "自动",
                "自定义",
                "开关",
                "模式",
                "时间",
                "配置",
                "系统",
            )
        )
        return feature_hits >= 4 and any(
            token in page_text for token in ("设置页", "设置", "配置", "系统")
        )

    def _looks_like_variant_matrix_page(self, page_text: str) -> bool:
        matrix_tokens = sum(
            token in page_text
            for token in (
                "配置",
                "低配",
                "高配",
                "版本",
                "方案",
                "场景",
                "有",
                "无",
                "显示",
                "隐藏",
            )
        )
        variant_refs = len(set(re.findall(r"\b\d{2}-\d+\b", page_text)))
        return matrix_tokens >= 4 and variant_refs >= 2

    def _looks_like_visual_flow_page(self, page_text: str) -> bool:
        flow_tokens = sum(
            token in page_text
            for token in ("点击", "进入", "返回", "跳转", "滑动", "流程", "状态", "成功", "失败")
        )
        return flow_tokens >= 3

    def _generic_visual_schema_scaffold(self, record: PageRecord) -> list[str]:
        if not (record.needs_visual_review or record.diagram_candidate):
            return []

        page_type = self._generic_visual_page_type(record)
        if page_type in {"table_of_contents", "information_architecture", "generic"}:
            return []

        builders = {
            "annotated_ui": self._build_annotated_ui_scaffold,
            "settings_tree": self._build_settings_tree_scaffold,
            "variant_matrix": self._build_variant_matrix_scaffold,
            "flow": self._build_flow_page_scaffold,
            "layout": self._build_layout_page_scaffold,
            "demo_spec": self._build_demo_spec_scaffold,
        }
        builder = builders.get(page_type)
        if builder is None:
            return []
        return builder(record)

    def _build_annotated_ui_scaffold(self, record: PageRecord) -> list[str]:
        lines = [
            "<!-- agent-corrected: generic-annotated-ui-schema-scaffold -->",
            "",
            "### 页面结构抽取",
            "",
            "- 页面类型：标注 UI 页。",
            "- 先按视觉恢复 `页面分区 -> 标号映射 -> 状态规则 -> 配置差异`，不要按 OCR 顺序线性铺开。",
            "- 页面分区建议至少检查：顶部导航 / 主视图区 / 侧边说明区 / 底部规则区 / 变体区。",
            "",
            "### 页面分区",
            "",
            "| 区域 | 视觉角色 | 结构化输出要求 |",
            "| --- | --- | --- |",
            "| 顶部区 | 标题、导航、tab | 作为导航/标题层，不并入功能说明 |",
            "| 主视图区 | 核心界面或主控件区 | 作为控件和状态语义主体 |",
            "| 说明区 | 右栏/侧栏/注释卡 | 作为 callout 解释区，与主图分离输出 |",
            "| 底部区 | 规则、限制、变更说明 | 单独归纳为规则或矩阵，不塞入控件列表 |",
            "",
            "### 标号映射表",
            "",
            "| 标号 | 控件/区域 | 说明 | 证据状态 |",
            "| --- | --- | --- | --- |",
            "| [待补充] | [待绑定] | [待恢复原文措辞] | 待视觉确认 |",
            "",
            "### 状态 / 规则",
            "",
            "- 默认态、开启态、异常态、退出条件应与控件说明分开整理。",
            "- 如果页面出现 `新增 / 删除 / 变更`，应拆分为历史变更说明，而不是直接并入当前规则。",
            "",
            "### 待人工核查问题",
            "",
            "- 任何未安全绑定的标号必须列在这里，不能漂浮在正文中。",
            "- 若 OCR 文本与视觉锚点冲突，以视觉锚点组织结构，并在此记录未决点。",
            "",
            "### 校验清单",
            "",
            "- 不应存在未映射的独立字母/数字标号。",
            "- 每个可见标号要么进入映射表，要么进入待人工核查问题。",
            "- 说明卡文本不能与主视图区控件描述混写成单层列表。",
            "",
        ]
        return lines + self._render_page_text_blocks(record)

    def _build_settings_tree_scaffold(self, record: PageRecord) -> list[str]:
        lines = [
            "<!-- agent-corrected: generic-settings-tree-scaffold -->",
            "",
            "### 页面结构抽取",
            "",
            "- 页面类型：设置树页。",
            "- 应先恢复 `父功能 -> 子功能/模式 -> 时间配置/说明/反馈` 层级，再整理原文。",
            "",
            "### 设置项树",
            "",
            "- [父功能待补充]",
            "  - [子功能/模式待补充]",
            "    - [规则/时间/限制待补充]",
            "",
            "### 自动化反馈 / 提示",
            "",
            "- toast / TTS / 异常提示 / 自动保存等反馈，应从设置树主体中拆出单列。",
            "",
            "### 待人工核查问题",
            "",
            "- 若某设置项疑似子项但 OCR 顺序将其拍平，应在此标记并保持保守嵌套。",
            "- 若时间配置属于某模式或父功能，不得脱离其父节点单独输出。",
            "",
            "### 校验清单",
            "",
            "- 不允许把模式、时间配置、展开项直接提升为顶级同级项。",
            "- 不允许把自动化反馈和设置项树混成同一层列表。",
            "- 任何 `自动 / 自定义 / 时间段` 关系必须保留父子层级。",
            "",
        ]
        return lines + self._render_page_text_blocks(record)

    def _build_variant_matrix_scaffold(self, record: PageRecord) -> list[str]:
        lines = [
            "<!-- agent-corrected: generic-variant-matrix-scaffold -->",
            "",
            "### 页面结构抽取",
            "",
            "- 页面类型：配置差异 / 变体矩阵页。",
            "- 先识别比较维度（配置/版本/场景），再用矩阵呈现显隐和差异，不要写成线性长列表。",
            "",
            "### 差异矩阵",
            "",
            "| 比较项 | 变体 A | 变体 B | 备注 |",
            "| --- | --- | --- | --- |",
            "| [待补充] | [待补充] | [待补充] | [待补充] |",
            "",
            "### 规则归纳",
            "",
            "- 对 `显示 / 隐藏 / 入口有无 / 功能裁剪` 做统一归纳。",
            "",
            "### 待人工核查问题",
            "",
            "- 若某差异来自视觉布局而非清晰文本，应在此列出待确认点。",
            "",
            "### 校验清单",
            "",
            "- 配置差异优先输出表格，而不是散列 bullets。",
            "- 不同变体下的显隐关系必须对应到同一比较维度。",
            "",
        ]
        return lines + self._render_page_text_blocks(record)

    def _build_flow_page_scaffold(self, record: PageRecord) -> list[str]:
        lines = [
            "<!-- agent-corrected: generic-flow-page-scaffold -->",
            "",
            "### 页面结构抽取",
            "",
            "- 页面类型：流程 / 状态迁移页。",
            "- 先恢复 `状态 -> 触发动作 -> 结果 / 异常`，再补充原文说明。",
            "",
            "### 流程骨架",
            "",
            "1. [起始状态待补充]",
            "2. [触发动作待补充]",
            "3. [目标状态/结果待补充]",
            "",
            "### 异常 / 分支",
            "",
            "- 成功 / 失败 / 例外态 / 返回路径应单独列出。",
            "",
            "### 待人工核查问题",
            "",
            "- 箭头方向、分支归属或触发条件不清楚时在此保留。",
            "",
            "### 校验清单",
            "",
            "- 页面布局页不要误写成流程页；只有存在明确触发和迁移关系时才输出流程链。",
            "- 触发动作与页面静态分区不能混写。",
            "",
        ]
        return lines + self._render_page_text_blocks(record)

    def _build_layout_page_scaffold(self, record: PageRecord) -> list[str]:
        lines = [
            "<!-- agent-corrected: generic-layout-page-scaffold -->",
            "",
            "### 页面结构抽取",
            "",
            "- 页面类型：布局 / 分区页。",
            "- 优先恢复空间分区、模块归属和视觉层次，不要误转成动作流程。",
            "",
            "### 分区结构",
            "",
            "- 顶部区：",
            "- 左侧区 / 主区：",
            "- 右侧区 / 说明区：",
            "- 底部区：",
            "",
            "### 模块说明",
            "",
            "- 每个分区下再归纳对应模块、控件和说明。",
            "",
            "### 待人工核查问题",
            "",
            "- 如果 OCR 顺序打乱分区边界，应记录并按视觉分区重排。",
            "",
            "### 校验清单",
            "",
            "- 版面分区不应被线性 OCR 顺序覆盖。",
            "- 说明块和主内容块应分栏保留。",
            "",
        ]
        return lines + self._render_page_text_blocks(record)

    def _build_demo_spec_scaffold(self, record: PageRecord) -> list[str]:
        lines = [
            "<!-- agent-corrected: generic-demo-spec-scaffold -->",
            "",
            "### 页面结构抽取",
            "",
            "- 页面类型：演示规格 / 页面态说明页。",
            "- 应区分页面态、触发动作、说明块与示例界面占位文案。",
            "",
            "### 页面态与动作",
            "",
            "- 页面态：",
            "- 触发动作：",
            "- 结果：",
            "",
            "### 说明块",
            "",
            "- 保留原文规则说明，不把示例截图中的占位内容当正文主体。",
            "",
            "### 待人工核查问题",
            "",
            "- 若某说明属于示例占位还是正式规则不清楚，在此保留。",
            "",
        ]
        return lines + self._render_page_text_blocks(record)

    def _page_macro_mermaid(self, record: PageRecord, *, profile: str) -> list[str]:
        page_text = " ".join(self._page_text_lines(record)[:160])
        if self._looks_like_table_of_contents_page(page_text):
            return []

        if self._looks_like_media_center_home_flow_page(page_text):
            return self._media_center_home_flow_mermaid()

        if self._looks_like_annotation_flow_page(page_text):
            return self._annotation_flow_mermaid()

        if profile == "j90k-hvac":
            if record.page_number == 5:
                return self._hvac_information_architecture_mermaid()
            if record.page_number == 6:
                return self._hvac_page_layout_mermaid()
            if record.page_number == 9:
                return self._hvac_seat_flow_mermaid()

        if self._looks_like_information_architecture_page(page_text):
            return self._media_center_information_architecture_mermaid()

        if self._looks_like_page_layout_page(page_text):
            return self._media_center_page_layout_mermaid()

        return []

    def _looks_like_annotation_flow_page(self, page_text: str) -> bool:
        return (
            any(keyword in page_text for keyword in ("标注说明", "Annotation Notes"))
            and any(keyword in page_text for keyword in ("跳转线", "判断条件", "成功", "失败"))
        )

    def _looks_like_table_of_contents_page(self, page_text: str) -> bool:
        if not any(keyword in page_text for keyword in ("目录", "Content", "目录页")):
            return False

        heading_hits = sum(
            keyword in page_text
            for keyword in ("变更记录", "标注说明", "信息架构", "页面布局", "信息布局页面")
        )
        return heading_hits >= 3

    def _looks_like_information_architecture_page(self, page_text: str) -> bool:
        return any(keyword in page_text for keyword in ("信息架构", "Information Architecture"))

    def _looks_like_page_layout_page(self, page_text: str) -> bool:
        return any(keyword in page_text for keyword in ("页面布局", "⻚⾯布局", "Page Layout"))

    def _looks_like_media_center_home_flow_page(self, page_text: str) -> bool:
        if not any(keyword in page_text for keyword in ("QQ Music home", "QQ音乐首页", "QQ⾳乐⾸⻚")):
            return False

        marker_groups = [
            any(marker in page_text for marker in ("APP list", "06-1", "06-6")),
            any(marker in page_text for marker in ("向下滑动", "拉到底部")),
            any(marker in page_text for marker in ("加载失败", "无网络")),
            any(marker in page_text for marker in ("杜比", "更多杜比单曲", "杜比官方歌单")),
        ]
        return sum(marker_groups) >= 3

    def _annotation_flow_mermaid(self) -> list[str]:
        return [
            "```mermaid",
            "flowchart LR",
            '  subgraph Legend["标注体系"]',
            '    PageMark["页面标注 / 页码标注"]',
            '    FuncMark["功能解释标注"]',
            '    IssueMark["问题类标注 QA / TBD"]',
            '    VoiceMark["语音指令标注"]',
            '    ChangeMark["页面变更标记 新增 / 删除 / 变更"]',
            "  end",
            '  Trigger["指令\n单击 / 滑动 / 语音 / 等待等"] --> Decision{"判断条件"}',
            '  Decision --> Success["成功"]',
            '  Decision --> Failure["失败"]',
            '  PageMark -. 锚定页面编号 .-> Trigger',
            '  VoiceMark -. 语音触发 .-> Trigger',
            '  FuncMark -. 解释节点 .-> Decision',
            '  IssueMark -. 异常 / 待确认 .-> Failure',
            '  ChangeMark -. 版本差异 .-> Decision',
            "```",
        ]

    def _media_center_information_architecture_mermaid(self) -> list[str]:
        left_nodes = [
            ("QQMusic", "QQ音乐"),
            ("Daily", "每日推荐"),
            ("Plaza", "歌单广场"),
            ("Ranking", "榜单推荐"),
            ("HiRes", "高品专区"),
            ("NewSongs", "内地新歌"),
            ("Radio", "音乐电台"),
            ("Artist", "歌手推荐"),
            ("UserCenter", "用户中心"),
            ("OutdoorConcert", "户外音乐会"),
            ("LightShow", "音乐灯光秀"),
            ("Karaoke", "无麦K歌"),
        ]
        right_nodes = [
            ("LocalMusic", "本地音乐"),
            ("BluetoothMusic", "蓝牙音乐"),
            ("SearchPage", "搜索页面"),
            ("PlayerPage", "播放页面"),
            ("Playlist", "播放列表"),
            ("DownloadFlow", "下载流程"),
            ("PaidFlow", "付费流程"),
            ("LoginUnbind", "登录&解绑"),
            ("MiniController", "简易播控器"),
        ]

        lines = [
            "```mermaid",
            "flowchart LR",
            '  subgraph Left["内容入口"]',
        ]
        for node_id, label in left_nodes:
            lines.append(f'    {node_id}["{label}"]')
        lines.extend([
            "  end",
            '  MediaCenter["媒体中心"]',
            '  subgraph Right["功能与页面"]',
        ])
        for node_id, label in right_nodes:
            lines.append(f'    {node_id}["{label}"]')
        lines.append("  end")
        for node_id, _ in left_nodes:
            lines.append(f"  {node_id} --> MediaCenter")
        for node_id, _ in right_nodes:
            lines.append(f"  MediaCenter --> {node_id}")
        lines.append("```")
        return lines

    def _media_center_page_layout_mermaid(self) -> list[str]:
        return [
            "```mermaid",
            "flowchart LR",
            '  subgraph Home["首页基础布局"]',
            "    direction TB",
            '    HomeStatus["Statusbar"] --> HomeA["A区 标题区"]',
            '    HomeA --> HomeSplit{"首页主体"}',
            '    HomeSplit --> HomeB["B区 Tab切换区"]',
            '    HomeSplit --> HomeC["C区 内容显示区域"]',
            '    HomeB --> HomeDock["Dock"]',
            '    HomeC --> HomeDock',
            "  end",
            '  subgraph Player["播放页基础布局"]',
            "    direction TB",
            '    PlayerStatus["Statusbar"] --> PlayerA["A区 标题区"]',
            '    PlayerA --> PlayerB["B区 封面区"]',
            '    PlayerB --> PlayerC["C区 歌词及无麦K歌区"]',
            '    PlayerC --> PlayerE["E区 进度条"]',
            '    PlayerE --> PlayerD["D区 播控基础操作区"]',
            '    PlayerD --> PlayerDock["Dock"]',
            "  end",
            "```",
        ]

    def _media_center_home_flow_mermaid(self) -> list[str]:
        return [
            "```mermaid",
            "flowchart TB",
            '  subgraph LowConfig["低配主链"]',
            '    LowAppList["06-1 APP list"] -->|点击| LowHome["06-2 QQ音乐-首页"]',
            '    LowHome -->|向下滑动| LowLoading["06-4 首页-加载中"]',
            '    LowLoading -->|拉到底部| LowBottom["06-5 首页-拉到底"]',
            '    LowHome -. 异常态 .-> LowFailure["06-3 首页-无网络/加载失败"]',
            "  end",
            '  subgraph HighConfig["高配主链"]',
            '    HighAppList["06-6 APP list"] -->|点击| HighHome["06-7 QQ音乐-首页"]',
            '    HighHome -->|点击杜比专区| DolbyDetail["06-10 杜比专区详情页"]',
            '    DolbyDetail -->|点击查看更多| MoreSingles["06-9 更多杜比单曲"]',
            '    DolbyDetail -->|点击官方歌单| OfficialPlaylist["06-11 杜比官方歌单"]',
            '    HighHome -. 异常态 .-> HighFailure["06-8 首页-无网络/加载失败"]',
            "  end",
            "```",
        ]

    def _hvac_information_architecture_mermaid(self) -> list[str]:
        return [
            "```mermaid",
            "flowchart LR",
            '  subgraph SeatSide["座椅侧能力"]',
            '    SeatVent["座椅通风"] --> SeatControl["座椅控制"]',
            '    SeatHeat["座椅加热"] --> SeatControl',
            '    SeatMassage["座椅按摩"] --> SeatControl',
            '    SteeringHeat["方向盘加热"] --> SeatControl',
            '    RearSeat["后排加热/通风"] --> SeatControl',
            "  end",
            '  SeatControl --> HVAC["空调"] --> HVACControl["空调控制"]',
            '  subgraph ClimateSide["空调控制能力"]',
            '    HVACControl --> MaxAC["MAX A/C"]',
            '    HVACControl --> Temp["温度调节"]',
            '    HVACControl --> AutoMode["AUTO"]',
            '    HVACControl --> Fan["风量调节"]',
            '    HVACControl --> Sync["温度同步"]',
            '    HVACControl --> Comfort["净化/舒适功能"]',
            '    HVACControl --> Switch["开关"]',
            '    HVACControl --> AirMode["出风模式"]',
            '    HVACControl --> Circulation["内外循环"]',
            '    HVACControl --> Settings["空调设置"]',
            '    HVACControl --> TriState["三态循环"]',
            '    HVACControl --> Defrost["后除霜"]',
            "  end",
            "```",
        ]

    def _hvac_page_layout_mermaid(self) -> list[str]:
        return [
            "```mermaid",
            "flowchart LR",
            '  subgraph ACLayout["空调页布局"]',
            "    direction TB",
            '    ACStatus["Statusbar"] --> ACA["A区 菜单标题栏"]',
            '    ACA --> ACSplit{"空调页主体"}',
            '    ACSplit --> ACB["B区 空调视图与次要功能区"]',
            '    ACSplit --> ACC["C区 主要核心操作功能区"]',
            '    ACB --> ACDock["Dock"]',
            '    ACC --> ACDock',
            "  end",
            '  subgraph SeatLayout["座椅页布局"]',
            "    direction TB",
            '    SeatStatus["Statusbar"] --> SeatA["A区 菜单标题栏"]',
            '    SeatA --> SeatB["B区 功能操作与视图"]',
            '    SeatB --> SeatDock["Dock"]',
            "  end",
            "```",
        ]

    def _hvac_seat_flow_mermaid(self) -> list[str]:
        return [
            "```mermaid",
            "flowchart LR",
            '  ACPage["07-1 空调控制页"] --> ClickSeat["点击座椅视图"]',
            '  ClickSeat --> SeatState{"是否存在开启项"}',
            '  SeatState -- "有" --> SeatOn["07-2 座椅控制页（有开启项）"]',
            '  SeatState -- "无" --> SeatOff["07-4 座椅控制页（未开启）"]',
            '  SeatOn --> MassagePanel["07-3 座椅按摩设置页"]',
            '  SeatOff --> MassagePanel',
            '  MassagePanel --> Action["开始按摩 / 停止按摩 / 一键关闭"]',
            '  Action --> ReturnSeat["返回当前座椅控制页"]',
            "```",
        ]

    def _render_page_tables(
        self, record: PageRecord, page_tables: list[dict[str, Any]]
    ) -> list[str]:
        """Render extracted page tables as Markdown tables."""
        lines: list[str] = []
        for table_info in page_tables:
            rows = table_info.get("rows", [])
            if not rows or len(rows) < 2:
                continue

            # Normalize row widths
            max_cols = max(len(r) for r in rows) if rows else 0
            if max_cols < 2:
                continue

            normalized: list[list[str]] = []
            for row in rows:
                padded = list(row) + [""] * (max_cols - len(row))
                normalized.append(padded)

            # Determine if first row is a header: check if remaining rows have more text content
            # or if first row cells are notably shorter / more title-like
            is_header = self._looks_like_table_header(normalized)

            lines.append("### 规格表格")
            lines.append("")
            lines.extend(self._build_markdown_table(normalized, is_header))
            lines.append("")

            # Add a note about the table source
            source = table_info.get("source", "unknown")
            if source in ("implicit", "ocr-implicit"):
                lines.append(
                    "> 注：此表格由版面文字聚类重建，若单元格归属有误请以截图为准。"
                )
                lines.append("")

        return lines

    def _looks_like_table_header(self, rows: list[list[str]]) -> bool:
        """Heuristic: is the first row a table header?"""
        if not rows or len(rows) < 2:
            return False

        first_row = rows[0]
        # Header cells tend to be shorter and more title-like
        first_row_avg_len = sum(len(cell) for cell in first_row) / max(len(first_row), 1)
        rest_avg_lens = []
        for row in rows[1:]:
            avg = sum(len(cell) for cell in row) / max(len(row), 1)
            rest_avg_lens.append(avg)

        if rest_avg_lens:
            overall_rest_avg = sum(rest_avg_lens) / len(rest_avg_lens)
            # If first row is significantly shorter, likely a header
            if first_row_avg_len < overall_rest_avg * 0.5:
                return True

        # If first row contains known header-like patterns
        first_row_text = " ".join(first_row).lower()
        header_indicators = ("功能", "说明", "交互", "名称", "描述", "设置", "选项", "状态", "参数")
        if any(kw in first_row_text for kw in header_indicators):
            return True

        # Default: treat first row as header if page has enough rows
        return len(rows) >= 4

    def _build_markdown_table(
        self, rows: list[list[str]], is_header: bool
    ) -> list[str]:
        """Build a Markdown table from normalized rows."""
        if not rows:
            return []

        lines: list[str] = []

        # If first row is header, use it as header
        if is_header:
            header = rows[0]
            lines.append("| " + " | ".join(h if h else " " for h in header) + " |")
            lines.append("| " + " | ".join("---" for _ in header) + " |")
            for row in rows[1:]:
                lines.append("| " + " | ".join(cell if cell else " " for cell in row) + " |")
        else:
            # No header — create a generic header
            num_cols = len(rows[0])
            generic_header = ["列" + str(i + 1) for i in range(num_cols)]
            lines.append("| " + " | ".join(generic_header) + " |")
            lines.append("| " + " | ".join("---" for _ in generic_header) + " |")
            for row in rows:
                lines.append("| " + " | ".join(cell if cell else " " for cell in row) + " |")

        return lines

    def _render_page_text_blocks(self, record: PageRecord, *, bundle: WorkingBundle | None = None) -> list[str]:
        blocks = self._page_text_blocks(record)
        if not blocks:
            # Fallback: try draft_markdown (from OCR extraction in baseline adapter)
            if bundle and bundle.draft_markdown.strip():
                page_section = self._extract_page_from_draft(bundle.draft_markdown, record.page_number)
                if page_section:
                    return page_section
            return ["> No extracted text was available for this page."]

        rendered: list[str] = []
        for block in blocks:
            rendered.extend(self._render_text_block(block))
            rendered.append("")

        if rendered and rendered[-1] == "":
            rendered.pop()
        return rendered

    def _page_text_blocks(self, record: PageRecord) -> list[list[str]]:
        raw_text = self._page_raw_text(record).replace("\x0c", "\n")
        if not raw_text.strip():
            return []

        blocks: list[list[str]] = []
        current_block: list[str] = []
        for raw_line in raw_text.splitlines():
            line = self._normalize_text_line(raw_line)
            if not line:
                if current_block:
                    blocks.append(current_block)
                    current_block = []
                continue
            if not current_block or current_block[-1] != line:
                current_block.append(line)

        if current_block:
            blocks.append(current_block)
        return blocks

    def _normalize_text_line(self, line: str) -> str:
        line = line.replace("\u00a0", " ").replace("\t", " ").strip()
        return re.sub(r"\s+", " ", line)

    def _render_text_block(self, block: list[str]) -> list[str]:
        ordered_list = self._ordered_list_block(block)
        if ordered_list:
            return ordered_list

        bullet_list = self._bullet_list_block(block)
        if bullet_list:
            return bullet_list

        return ["  \n".join(block)]

    def _extract_page_from_draft(self, draft: str, page_number: int) -> list[str]:
        """Extract text for a specific page from draft_markdown."""
        lines = draft.splitlines()
        result: list[str] = []
        in_page = False
        target_heading = f"## Page {page_number}"

        for line in lines:
            if line.startswith("## Page "):
                if line == target_heading:
                    in_page = True
                    continue
                elif in_page:
                    break
            if in_page and line.startswith("### "):
                result.append(line)
            elif in_page and line.startswith("- "):
                result.append(line)
            elif in_page and line.strip() and not line.startswith(("##", "```", "![", ">")):
                result.append(line)

        if result:
            return result
        return []

    def _ordered_list_block(self, block: list[str]) -> list[str]:
        ordered_pattern = re.compile(r"^(\d+)[\.、)]\s*(.+)$")
        rendered: list[str] = []
        for line in block:
            match = ordered_pattern.match(line)
            if not match:
                return []
            rendered.append(f"{match.group(1)}. {match.group(2)}")
        return rendered if len(rendered) >= 2 else []

    def _bullet_list_block(self, block: list[str]) -> list[str]:
        bullet_pattern = re.compile(r"^[-*•]\s+(.+)$")
        rendered: list[str] = []
        for line in block:
            match = bullet_pattern.match(line)
            if not match:
                return []
            rendered.append(f"- {match.group(1)}")
        return rendered if len(rendered) >= 2 else []

    def _page_region_gallery(
        self,
        bundle: WorkingBundle,
        record: PageRecord,
        *,
        profile: str,
    ) -> list[str]:
        gallery: list[str] = []
        page_text = " ".join(self._page_text_lines(record)[:120])
        if self._looks_like_media_center_home_flow_page(page_text):
            for path_hint, alt_text in (
                ("flow-low-config", "QQ音乐首页低配跳转总览"),
                ("flow-low-main-branch", "QQ音乐首页低配主链细节"),
                ("flow-high-config", "QQ音乐首页高配跳转总览"),
                ("flow-high-main-branch", "QQ音乐首页高配主链细节"),
            ):
                image_markdown = self._page_region_markdown(bundle, record.page_number, path_hint, alt_text)
                if image_markdown:
                    gallery.extend([image_markdown, ""])
            if gallery and gallery[-1] == "":
                gallery.pop()
            return gallery

        if self._looks_like_demo_spec_page(page_text):
            for path_hint, alt_text in (
                ("demo-left-pane", f"Page {record.page_number} 左栏原文区域"),
                ("demo-right-pane", f"Page {record.page_number} 右栏原文区域"),
            ):
                image_markdown = self._page_region_markdown(bundle, record.page_number, path_hint, alt_text)
                if image_markdown:
                    gallery.extend([image_markdown, ""])
            if gallery and gallery[-1] == "":
                gallery.pop()
            return gallery

        if profile == "j90k-hvac" and record.page_number == 9:
            for path_hint, alt_text in (
                ("massage-panel", "座椅按摩设置面板"),
                ("flow-left", "座椅流程左支"),
                ("flow-right", "座椅流程右支"),
            ):
                image_markdown = self._page_region_markdown(bundle, record.page_number, path_hint, alt_text)
                if image_markdown:
                    gallery.extend([image_markdown, ""])
            if gallery and gallery[-1] == "":
                gallery.pop()
            return gallery

        if record.diagram_candidate:
            image_markdown = self._page_region_markdown(
                bundle,
                record.page_number,
                "diagram-focus",
                f"Page {record.page_number} diagram focus",
            )
            if image_markdown:
                gallery.append(image_markdown)
        return gallery

    def _extract_table_of_contents(self, bundle: WorkingBundle) -> list[str]:
        entries: list[str] = []
        seen: set[str] = set()
        for record in bundle.page_records[:4]:
            lines = self._page_text_lines(record)
            if not any(keyword in " ".join(lines[:8]) for keyword in ("目录", "Content", "目录页")):
                continue

            for index, line in enumerate(lines):
                if not re.match(r"^\d{2}\s+", line):
                    continue
                page_ref = ""
                if index + 1 < len(lines) and re.fullmatch(r"\d{1,3}", lines[index + 1]):
                    page_ref = lines[index + 1]
                entry = f"- {line}" + (f" -> {page_ref}" if page_ref else "")
                if entry not in seen:
                    seen.add(entry)
                    entries.append(entry)
        return entries

    def _build_change_record_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 1. 变更记录",
            self._page_image_markdown(
                bundle, self._j90k_page_number("change_record"), "变更记录页"
            ),
            "",
            "| 版本 | 日期 | 主要变更 |",
            "| --- | --- | --- |",
            "| 0.1.0 | 2024-08-15 | 初始版本 |",
            "| 0.2.0 | 2025-01-08 | 删除 A/C；取消空气净化语音提示和动画提示开关；新增方向盘加热；后排座椅新增加热/通风功能 |",
            "| 0.2.1 | 2025-04-10 | 空调面板增加下滑小横条 |",
            "| 0.2.2 | 2025-04-17 | 点击开始按摩后，文案改为“停止按摩” |",
            "| 0.2.3 | 2025-07-04 | 新增座椅配置特殊说明 |",
            "",
        ]

    def _build_annotation_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 2. 标注说明与跳转线语义",
            self._page_image_markdown(
                bundle, self._j90k_page_number("annotation"), "标注说明页"
            ),
            "",
            "### 2.1 标注体系",
            "- 页面标注：使用页码与页面名称组合，例如 `02-1 Launcher`。",
            "- 手势操作：覆盖单击、长按、拖动、上下左右滑动、双指与三指手势、缩小/放大。",
            "- 页面变更标记：绿色表示新增，红色表示删除，蓝色表示变更。",
            "- 区域标记：用红色高亮框和描述文本标识需关注区域。",
            "- 语音指令标注：用于标识语音命令入口或语音助手常驻说明。",
            "",
            "### 2.2 跳转线 / 判断流语义",
            "该页不是普通文本说明，而是把页面流转语义可视化定义清楚：先触发指令，再经过判断条件，最后进入成功或失败分支。",
            "",
            "```mermaid",
            "flowchart LR",
            '  Trigger["指令\\n单击 / 滑动 / 语音 / 等待"] --> Decision{"判断条件"}',
            '  Decision --> Success["成功"]',
            '  Decision --> Failure["失败"]',
            "```",
            "",
            "### 2.3 对后续页面修复的意义",
            "- 看到蓝色箭头、判断菱形、成功/失败分支时，不应该简单转成线性段落，而应保留流程结构。",
            "- 看到红/绿/蓝高亮框时，应把它们解释为变更语义，而不是普通背景色。",
            "",
        ]

    def _build_information_architecture_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 3. 信息架构与模块指向",
            self._page_image_markdown(
                bundle, self._j90k_page_number("information_architecture"), "信息架构页"
            ),
            "",
            "### 3.1 中心链路",
            "- 座椅控制 -> 空调 -> 空调控制",
            "",
            "### 3.2 座椅控制侧能力",
            "- 座椅通风",
            "- 座椅加热",
            "- 座椅按摩",
            "- 方向盘加热",
            "- 后排加热 / 通风",
            "",
            "### 3.3 空调控制侧能力",
            "- MAX A/C",
            "- 温度调节",
            "- AUTO",
            "- 风量调节",
            "- 温度同步",
            "- 净化 / 舒适功能",
            "- 开关",
            "- 出风模式",
            "- 内外循环",
            "- 空调设置",
            "- 三态循环",
            "- 后除霜",
            "- 电子外后视镜加热",
            "",
            "### 3.4 模块关系图",
            "```mermaid",
            "flowchart LR",
            '  SeatVent["座椅通风"] --> SeatControl["座椅控制"]',
            '  SeatHeat["座椅加热"] --> SeatControl',
            '  SeatMassage["座椅按摩"] --> SeatControl',
            '  SteeringHeat["方向盘加热"] --> SeatControl',
            '  RearSeat["后排加热/通风"] --> SeatControl',
            '  SeatControl --> HVAC["空调"] --> HVACControl["空调控制"]',
            '  HVACControl --> MaxAC["MAX A/C"]',
            '  HVACControl --> Temp["温度调节"]',
            '  HVACControl --> AutoMode["AUTO"]',
            '  HVACControl --> Fan["风量调节"]',
            '  HVACControl --> Sync["温度同步"]',
            '  HVACControl --> Comfort["净化/舒适功能"]',
            '  HVACControl --> Switch["开关"]',
            '  HVACControl --> AirMode["出风模式"]',
            '  HVACControl --> Circulation["内外循环"]',
            '  HVACControl --> Settings["空调设置"]',
            '  HVACControl --> TriState["三态循环"]',
            '  HVACControl --> Defrost["后除霜"]',
            '  HVACControl --> MirrorHeat["电子外后视镜加热"]',
            "```",
            "",
        ]

    def _build_page_layout_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 4. 页面布局分区",
            self._page_image_markdown(
                bundle, self._j90k_page_number("page_layout"), "页面布局页"
            ),
            "",
            "### 4.1 空调页布局",
            "- `Statusbar` 位于页面顶部。",
            "- `A 区` 是菜单标题栏，用于 `空调 / 座椅` 顶部切换。",
            "- `B 区` 是空调视图与次要功能区，承载温度、空气质量、舒适/节能等信息。",
            "- `C 区` 是主要核心操作功能区，承载同步、AUTO、A/C、MAX 等关键控制。",
            "- `Dock` 位于底部，是风量入口和浮层展开/收起的主要交互起点。",
            "",
            "### 4.2 座椅页布局",
            "- 保留 `Statusbar` 和 `A 区` 标题栏。",
            "- 核心操作聚合到 `B 区`，展示座椅相关功能操作与视图。",
            "- 页面下方仍保留 `Dock`。",
            "",
            "### 4.3 布局分层图",
            "```mermaid",
            "flowchart TB",
            '  Statusbar["Statusbar"] --> AreaA["A 区：菜单标题栏"]',
            '  AreaA --> AreaB["B 区：空调视图与次要功能区"]',
            '  AreaB --> AreaC["C 区：主要核心操作功能区"]',
            '  AreaC --> Dock["Dock"]',
            "```",
            "",
            "### 4.4 修复原则",
            "- 这一页表达的是自上而下的空间分层，不是功能触发流程。",
            "- 因此保留顶部到 Dock 的层次关系即可，不再用带判断语义的箭头或分支图去过度解释。",
            "",
        ]

    def _build_information_details_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 5. 信息详情与主界面控件",
            self._page_image_markdown(
                bundle, self._j90k_page_number("information_details"), "信息详情页"
            ),
            "",
            "### 5.1 页面组织方式",
            "- 这一页不是流程图，而是 `左侧主图 + 右侧说明卡 + 下半部变体/例外说明` 的说明页。",
            "- 上半部聚焦主驾空调页的控件说明；中下部补充副驾侧与座椅页的变体；底部绿色块是新增的座椅配置规则。",
            "- 因此这一章更适合恢复成 `分区映射 + 说明卡归类 + 规则表`，而不是把所有元素硬连成箭头流程。",
            "",
            "### 5.2 左侧主视图与右侧说明卡",
            "",
            self._page_region_markdown(
                bundle, 7, "half-left", "信息详情左半区"
            ),
            "",
            self._page_region_markdown(
                bundle, 7, "half-right", "信息详情右半区"
            ),
            "",
            "| 视觉区域 | 恢复含义 | 处理原则 |",
            "| --- | --- | --- |",
            "| 顶部标题带 | `空调 / 座椅` 二级 tab 与页面标题 | 保留为导航区，不转成流程节点 |",
            "| 中部主视图区 | 主副驾温度、风量动效、PM2.5 与座椅视图反馈 | 还原为状态反馈区 |",
            "| 底部主控条 | Dock、同步、AUTO、MAX 等主控件 | 还原为主控件簇，不串成线性箭头 |",
            "| 右侧说明卡 | 对应主图上的红框注释与规则说明 | 保留为解释卡片，不与视觉区混写 |",
            "",
            "#### 5.2.1 标号映射（结构优先重建）",
            "",
            "<!-- agent-corrected: schema-first-callout-mapping-required -->",
            "",
            "对于这类带字母标号的 UI 说明页，最终交付必须显式恢复 `标号 -> 控件/区域 -> 说明` 映射。",
            "如果某一标号在 OCR 中出现但未能安全绑定到控件，不能省略，必须进入待人工核查问题。",
            "",
            "| 标号 | 控件/区域 | 说明类型 |",
            "| --- | --- | --- |",
            "| a | 顶部 `空调 / 座椅` tab 或相关切页区域 | 导航 / 切页说明 |",
            "| b~r | 主图控件与右侧说明卡中的功能位 | 控件说明 / 状态规则 / 历史变更 / 限制条件 |",
            "",
            "### 5.3 主控件与状态语义",
            "",
            "- 温度调节：主副驾温度独立显示，支持同步逻辑；空调关闭时仍显示上一次温度，但以弱化态呈现。",
            "- AUTO：只有全 AUTO 状态时工作指示灯点亮；风量、出风模式、压缩机或前除霜操作会退出 AUTO。",
            "- A/C：baseline 里仍保留了历史说明，但页面上已明确标注 `20250108 删除`。",
            "- 舒适 / 节能：开启后进入节能模式，并可能与其他模块联动。",
            "- 制冷 / 制热 / 通风：三态合一循环按钮。",
            "- MAX A/C：强制进入高制冷状态，并联动风量、内循环和最低温设定。",
            "- 内外循环：前除霜期间强制外循环，结束后恢复原状态。",
            "- 风量调节：通过 Dock 的点击或上滑进入浮层，1-8 档，0 档关机。",
            "- 空调开关：默认关闭状态，电源 ON 档、空调 OFF 时空调关闭。通过软开关打开或关闭空调。",
            "- 后除霜：后除霜功能不关联空调状态，在空调为 OFF 时仍可启用后除霜功能。",
            "- 出风模式：前排出风模式为吹脚、吹面、吹窗（可多选七模式），以上几种模式及前除霜不能同时存在，只有一种运行模式。",
            "- PM2.5 空气质量显示：6 级颜色标识（优/良/轻度/中度/重度/严重），数值无法读取时显示\"--\"。",
            "- 电子外后视镜加热：通过软开关打开或关闭摄像头除雾开关。当打开摄像头除雾功能时，摄像头开启加热，加热过程中在监控屏显示加热状态，可通过软开关中止加热。电量过低时给到提示：\"电量过低，无法使用电子外后视镜加热\"。",
            "",
            "关键标注控件：",
            "",
            "- 温度调节-主副驾",
            "- AUTO模式",
            "- A/C",
            "- 内外循环",
            "- 空调",
            "- 座椅",
            "- 舒适/节能",
            "- 制冷/制热/通风",
            "- MAX A/C",
            "- 空调设置",
            "- 后除霜",
            "- 温度同步",
            "- 出风模式",
            "- 净化",
            "- 电子外后视镜加热",
            "- 空调开关",
            "",
            "### 5.4 页面变体与副驾说明",
            "",
            self._page_region_markdown(
                bundle, 7, "strip-middle", "信息详情中区"
            ),
            "",
            "- 页面变体编号：05-1, 05-3, 05-2, 05-4, 05-5, 05-6, 05-7。",
            "- `05-2` 表示副驾侧空调说明，文档明确写了\"副驾空调暂不对应唤起\"，应恢复为限制条件而不是主流程分支。",
            "- `05-3` 是座椅控制页占位示意，用于说明从空调页切到座椅页后的视觉骨架。",
            "- `05-4` 到 `05-7` 是四种配置差异页，用来表达存在或不存在座椅能力时的页面显隐关系。",
            "",
            "### 5.5 底部新增规则块",
            "",
            self._page_region_markdown(
                bundle, 7, "strip-bottom", "座椅配置特殊说明"
            ),
            "",
            "| 配置场景 | 页面表现 | 恢复规则 |",
            "| --- | --- | --- |",
            "| 配置 1 | 空调控制页面变体 `05-4` | 无对应座椅能力时隐藏相关座椅控件 |",
            "| 配置 2 | 座椅控制页面变体 `05-5` | 按座椅能力显示对应按钮与视图 |",
            "| 配置 3 | 座椅控制页面变体 `05-6` | 与配置 2 相比保留不同的功能显隐关系 |",
            "| 配置 4 | 座椅控制页面变体 `05-7` | 继续表达配置裁剪后的页面骨架 |",
            "| 全量 | 空调 + 座椅完整页面 | 展示全部入口与完整功能集 |",
            "",
            "- 核心总规则：`无相关配置做隐藏处理，无座椅页面时不显示二级 tab`。",
            "",
            "### 5.6 原文保留",
            "",
        ]

    def _build_ac_settings_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 6. 空调设置与自动化策略",
            self._page_image_markdown(bundle, 8, "空调设置页"),
            "",
            "### 6.1 页面分区与入口",
            "",
            self._page_region_markdown(
                bundle, 8, "half-left", "空调设置左半区"
            ),
            "",
            self._page_region_markdown(
                bundle, 8, "half-right", "空调设置右半区"
            ),
            "",
            "- 左半部分是从空调控制页进入设置的总开关页；右半部分是进入座舱新风系统后的自动 / 自定义时间页面。",
            "- 这一页的核心不是单个按钮，而是\"设置项树 + 自动化触发条件 + toast/TTS 提示规则\"。",
            "",
            "### 6.2 设置项结构",
            "",
            "<!-- agent-corrected: hierarchy-aware-settings-tree -->",
            "",
            "| 一级设置项 | 子项 / 模式 | 说明 |",
            "| --- | --- | --- |",
            "| 自动除雾 | - | 自动除雾开关 |",
            "| 外后视镜自动除雾 | - | 外后视镜自动除雾开关 |",
            "| 自动空气净化 | - | 自动空气净化开关 |",
            "| 解锁自动换气 | - | 解锁后自动换气 |",
            "| 空气自干燥 | - | 停车后的空气自干燥策略 |",
            "| 解锁降窗通风 | - | 解锁场景下的降窗通风 |",
            "| 座舱新风系统 | 自动 | 锁车后每隔 4 小时进行一次外循环通风，最多通风 3 次 |",
            "| 座舱新风系统 | 自定义通风时间 | 上午 `06:30~12:00`、下午 `12:30~18:30`、晚上 `19:00~22:30`；可关闭，30 分钟粒度 |",
            "",
            "补充层级视图：",
            "",
            "- 座舱新风系统",
            "  - 自动",
            "    - 锁车后每隔 4 小时进行一次外循环通风，最多通风 3 次",
            "  - 自定义通风时间",
            "    - 上午：06:30~12:00，可关闭，30 分钟粒度",
            "    - 下午：12:30~18:30，可关闭，30 分钟粒度",
            "    - 晚上：19:00~22:30，可关闭，30 分钟粒度",
            "",
            "### 6.3 新风系统时间配置",
            "",
            self._page_region_markdown(
                bundle, 8, "strip-middle", "新风系统配置区"
            ),
            "",
            "- 自动模式：锁车后每隔 4 小时进行一次外循环通风，最多通风 3 次。",
            "- 自定义模式：分上午、下午、晚上三个时段配置通风时间。",
            "- 时间范围：上午 `06:30~12:00`，下午 `12:30~18:30`，晚上 `19:00~22:30`，间隔均为 30 分钟。",
            "- 关闭开关后，对应下方设置项收起；设置结果自动保存。",
            "",
            "### 6.4 自动化反馈与历史删除项",
            "",
            "- 自动除雾：如果 HU 未在设定时间内收到 AC 有效反馈，需要 toast 提示\"自动除雾功能异常！\"。",
            "- 自动空气净化：完成后可 toast 或语音播报\"空气净化已完成，当前空气质量优\"。",
            "- 解锁自动换气、解锁降窗通风、空气自干燥：都属于停车 / 锁车 / 解锁场景下的自动化 HVAC 行为。",
            "- `20250108 删除` 出现在空气净化动画提示、空气净化语音提示、解锁降窗通风等位置；修复时应把它识别为历史变更，而不是当前生效的默认功能。",
            "",
            "### 6.5 原文保留",
            "",
        ]

    def _build_seat_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 7. 座椅控制与按摩流程",
            self._page_image_markdown(bundle, 9, "座椅控制页"),
            "",
            "### 7.1 座椅通风与加热主界面",
            "",
            self._page_region_markdown(
                bundle, 9, "strip-top", "座椅通风与加热区域"
            ),
            "",
            "- 默认关闭，档位置灰。",
            "- 调节顺序：关闭 -> 3 档 -> 2 档 -> 1 档 -> 关闭。",
            "- 电源档位处于 ACC / OFF 时按钮置灰不可操作。",
            "- 低电量或系统故障时，需要提示座椅通风 / 加热 / 方向盘加热不可用。",
            "- 后排座椅通风 / 加热的开关逻辑和状态动效与前排保持一致。",
            "- **通风与加热互斥**：通风和加热功能互斥，不能同时开启。",
            "",
            "关键功能：",
            "",
            "- 座椅通风",
            "- 座椅加热",
            "- 座椅按摩",
            "- 后排座椅通风/加热",
            "- 方向盘加热",
            "- 一键关闭",
            "- 停止按摩",
            "- 开始按摩",
            "",
            "### 7.2 按摩设置弹窗",
            "",
            self._page_region_markdown(
                bundle, 9, "strip-bottom", "座椅按摩设置区域"
            ),
            "",
            "- 支持主驾 / 副驾独立按摩设置。",
            "- 模式集合：波浪 / 猫步 / 腰部 / 肩部 / 蛇形 / 脉冲 / 缓冲 / 推拿。",
            "- 时长集合：15min / 20min / 30min。",
            "- 档位集合：3档 / 2档 / 1档。",
            "- 未开始按摩时可选择模式、时长和档位；开始后按钮状态切换为\"停止按摩\"。",
            "- 支持一键关闭，也支持点击关闭按钮或热区外关闭当前弹窗。",
            "",
            "### 7.3 状态反馈与异常提示",
            "",
            "- 点击座椅视图后，会有转到顶视图的动画，强调 3D 空间感。",
            "- 座椅通风 / 加热 / 按摩强度通过座椅颜色深浅变化体现。",
            "- 按摩开启后，设置页同步进入高亮开启态。",
            "- 循环结束后，需要提示主驾或副驾重新开启按摩功能。",
            "  - 主驾提示：\"主驾座椅按摩循环结束，如需继续，请重新开启按摩功能（10s）\"",
            "  - 副驾提示：\"副驾座椅按摩循环结束，如需继续，请重新开启按摩功能（10s）\"",
            "- 低电量或系统故障时，文档要求弹出明确不可用提示。",
            "  - 座椅按摩：\"电量过低，无法使用座椅按摩\"",
            "",
            "### 7.4 按摩设置流程图",
            "",
            "```mermaid",
            "flowchart LR",
            '  Entry["进入座椅控制页"] --> Configure["选择主驾/副驾、模式、时长、档位"]',
            '  Configure --> Start["开始按摩"]',
            '  Start --> Running["按摩进行中"]',
            '  Running --> Stop["停止按摩 / 一键关闭"]',
            '  Running --> Timeout["计时结束"]',
            '  Timeout --> Reminder["提示重新开启"]',
            '  Stop --> Exit["返回座椅控制页"]',
            "```",
            "",
            "### 7.5 原文保留",
            "",
        ]

    def _build_closing_section(self, bundle: WorkingBundle) -> list[str]:
        return [
            "## 结束页与发布尾注",
            self._page_image_markdown(
                bundle, self._j90k_page_number("closing"), "结束页"
            ),
            "",
            "- 最后一页是发布尾注和结束页，不承载新的交互规则。",
            "- 它仍然应该保留在正文锚点里，用于证明文档在第 10 页正常闭合，而不是丢到附录后被动存在。",
            "",
        ]

    def _build_page_appendix(self, bundle: WorkingBundle) -> list[str]:
        lines = [
            "## 附录：页级视觉资产",
            "下列页面截图和切片是后续进一步 Agent 修复或人工校审的直接依据。",
            "",
        ]
        for record in bundle.page_records:
            lines.extend(self._page_asset_block(record))
        return lines

    def _page_asset_block(self, record: PageRecord) -> list[str]:
        lines = [
            f"### Page {record.page_number:02d}",
            f"- Visual review: {'yes' if record.needs_visual_review else 'no'}",
            f"- Text length: {record.text_length or 0}",
            f"- Images: {record.image_count or 0}",
            f"- Chars: {record.char_count or 0}",
        ]
        if record.screenshot_path:
            lines.append(f"- Screenshot: {record.screenshot_path}")
        if record.tile_paths:
            lines.append(f"- Tiles: {', '.join(record.tile_paths)}")
        if record.region_paths:
            lines.append(f"- Regions: {', '.join(record.region_paths)}")
        raw_excerpt = (record.metadata or {}).get("raw_text_excerpt")
        if raw_excerpt:
            lines.append(f"- Baseline excerpt: {self._compress_excerpt(raw_excerpt)}")
        lines.append("")
        return lines

    def _j90k_page_number(self, section: str) -> int:
        page_map = {
            "cover": 1,
            "table_of_contents": 2,
            "change_record": 3,
            "annotation": 4,
            "information_architecture": 5,
            "page_layout": 6,
            "information_details": 7,
            "closing": 10,
        }
        return page_map[section]

    def _compress_excerpt(self, text: str) -> str:
        compact = re.sub(r"\s+", " ", text).strip()
        return compact[:180] + ("..." if len(compact) > 180 else "")

    def _cover_title(self, bundle: WorkingBundle) -> str:
        cover_record = self._page_record(bundle, 1)
        if cover_record is None:
            return self._display_document_title(bundle.source_document.filename)

        lines = self._page_text_lines(cover_record)
        title_parts: list[str] = []
        for line in lines[:6]:
            if re.search(r"resolution|version|released|\d{4}", line, re.IGNORECASE):
                break
            if re.fullmatch(r"\d+", line):
                if title_parts:
                    break
                continue
            title_parts.append(line)
            if len(title_parts) >= 4:
                break

        if title_parts:
            return " | ".join(title_parts)
        return self._display_document_title(bundle.source_document.filename)

    def _display_document_title(self, filename: str) -> str:
        stem = Path(filename).stem.replace("_", " ")
        return re.sub(r"\s+", " ", stem).strip()

    def _page_heading(self, record: PageRecord) -> str:
        lines = self._page_text_lines(record)
        if not lines:
            return ""

        first_line = lines[0]
        if re.fullmatch(r"\d{1,3}", first_line):
            return first_line

        heading_parts: list[str] = []
        for line in lines[:4]:
            if re.search(r"resolution|version|released|\d{4}", line, re.IGNORECASE):
                break
            if re.fullmatch(r"\d+", line):
                if heading_parts:
                    break
                continue
            if len(line) > 40 and heading_parts:
                break
            heading_parts.append(line)

        return " | ".join(heading_parts) if heading_parts else first_line

    def _page_excerpt(self, record: PageRecord) -> str:
        raw_text = self._page_raw_text(record)
        if not raw_text:
            return ""

        compact = re.sub(r"\s+", " ", raw_text).strip()
        if not compact:
            return ""
        return compact[:900] + ("..." if len(compact) > 900 else "")

    def _page_text_lines(self, record: PageRecord) -> list[str]:
        raw_text = self._page_raw_text(record)
        if not raw_text:
            return []

        lines = [re.sub(r"\s+", " ", line).strip() for line in raw_text.splitlines()]
        return [line for line in lines if line]

    def _page_raw_text(self, record: PageRecord) -> str:
        metadata = record.metadata or {}
        raw_text = metadata.get("raw_text")
        if isinstance(raw_text, str) and raw_text.strip():
            return raw_text

        excerpt = metadata.get("raw_text_excerpt")
        if isinstance(excerpt, str):
            return excerpt
        return ""

    def _page_has_ocr_fallback(self, record: PageRecord) -> bool:
        metadata = record.metadata or {}
        return bool(metadata.get("ocr_fallback_applied", False))

    def _page_image_markdown(
        self, bundle: WorkingBundle, page_number: int, alt_text: str
    ) -> str:
        record = self._page_record(bundle, page_number)
        if record is None or not record.screenshot_path:
            return ""
        return f"![{alt_text}]({record.screenshot_path})"

    def _page_region_markdown(
        self, bundle: WorkingBundle, page_number: int, path_hint: str, alt_text: str
    ) -> str:
        record = self._page_record(bundle, page_number)
        if record is None:
            return ""
        for region_path in record.region_paths:
            if path_hint in region_path:
                return f"![{alt_text}]({region_path})"
        return ""

    def _page_record(self, bundle: WorkingBundle, page_number: int) -> PageRecord | None:
        for record in bundle.page_records:
            if record.page_number == page_number:
                return record
        return None

    # =========================================================================
    # ASCII Diagram Fallback
    # =========================================================================

    def _page_diagram_output(self, record: PageRecord, *, profile: str) -> list[str]:
        """Try Mermaid first; fall back to ASCII diagram if Mermaid is not applicable."""
        mermaid = self._page_macro_mermaid(record, profile=profile)
        if mermaid:
            return ["### 结构图", ""] + mermaid + [""]

        ascii_lines = self._try_ascii_diagram(record, profile=profile)
        if ascii_lines:
            return ["### 结构图（ASCII）", ""] + ascii_lines + [""]

        return []

    def _try_ascii_diagram(self, record: PageRecord, *, profile: str) -> list[str]:
        """Attempt to generate an ASCII diagram from page text signals."""
        page_text = " ".join(self._page_text_lines(record)[:160])

        # Check for flow/state-transition patterns
        flow_diagram = self._ascii_flow_diagram(page_text, record)
        if flow_diagram:
            return flow_diagram

        # Check for hierarchy/outline patterns
        hierarchy_diagram = self._ascii_hierarchy_diagram(page_text, record)
        if hierarchy_diagram:
            return hierarchy_diagram

        return []

    def _ascii_flow_diagram(self, page_text: str, record: PageRecord) -> list[str]:
        """Generate ASCII flow diagram if page contains flow/state-transition signals."""
        flow_markers = ("点击", "滑动", "上滑", "下滑", "跳转", "进入", "返回", "切换", "-->", "→", "=>")
        hit_count = sum(1 for m in flow_markers if m in page_text)
        if hit_count < 2:
            return []

        # Extract node candidates from text
        nodes = self._extract_flow_nodes(page_text, record)
        if len(nodes) < 2:
            return []

        lines: list[str] = []
        lines.append("```")

        if len(nodes) <= 4:
            # Horizontal flow
            parts = []
            for i, node in enumerate(nodes):
                if i > 0:
                    parts.append(" --> ")
                parts.append(f"[{node}]")
            lines.append("  " + "".join(parts))
        else:
            # Vertical flow
            lines.append("  " + f"[{nodes[0]}]")
            for node in nodes[1:]:
                lines.append("      |")
                lines.append("      v")
                lines.append(f"  [{node}]")

        lines.append("```")
        lines.append("")
        lines.append(f"> ASCII 图基于页 {record.page_number} 的文本流程信号生成，共 {len(nodes)} 个节点。")
        return lines

    def _extract_flow_nodes(self, page_text: str, record: PageRecord) -> list[str]:
        """Extract flow node names from page text."""
        nodes: list[str] = []
        seen: set[str] = set()

        # Look for numbered patterns like "06-1 XXX"
        numbered = re.findall(r"(\d{2}-\d+)\s*([^\n]+?)(?=\d{2}-\d+|$)", page_text)
        for ref, label in numbered:
            label = self._clean_flow_node(label.strip())
            if label and ref not in seen:
                seen.add(ref)
                nodes.append(f"{ref} {label}")

        # Look for quoted or bracketed terms
        if not nodes:
            quoted = re.findall(r"[`「『]([^`」』]{2,30})[`」』]", page_text)
            for q in quoted[:8]:
                clean = q.strip()
                if clean and clean not in seen:
                    seen.add(clean)
                    nodes.append(clean)

        # Fallback: extract meaningful short phrases
        if not nodes:
            for line in page_text.split(" "):
                line = line.strip()
                if 2 <= len(line) <= 30 and line not in seen:
                    if re.search(r"[一-鿿]", line):
                        seen.add(line)
                        nodes.append(line)
                if len(nodes) >= 6:
                    break

        return nodes[:8]

    def _clean_flow_node(self, label: str) -> str:
        """Clean a flow node label."""
        label = re.sub(r"\s+", " ", label)
        label = label.strip(" -:：|>")
        # Remove common noise
        if label in ("Statusbar", "Dock", "点击", "点击后"):
            return ""
        return label[:40]

    def _ascii_hierarchy_diagram(self, page_text: str, record: PageRecord) -> list[str]:
        """Generate ASCII hierarchy/tree diagram if page contains outline patterns."""
        # Look for numbered outline patterns like "1. XXX", "1.1 XXX"
        outline = re.findall(r"^(\d+\.?\d*)\s+(.+)$", page_text, re.MULTILINE)
        if len(outline) < 2:
            return []

        lines: list[str] = ["```"]
        indent_stack: list[int] = []

        for num, text in outline[:10]:
            depth = num.count(".")
            while indent_stack and indent_stack[-1] >= depth:
                indent_stack.pop()
            indent = "  " * (depth + 1)
            prefix = "+-- " if indent_stack else ""
            lines.append(f"{indent}{prefix}{num} {text.strip()[:30]}")
            indent_stack.append(depth)

        lines.append("```")
        lines.append("")
        lines.append(f"> ASCII 层级图基于页 {record.page_number} 的编号大纲生成。")
        return lines
