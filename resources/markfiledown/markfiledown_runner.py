from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# ── Pipeline State File ────────────────────────────────────────────────
# The runner writes this file after extraction. The Agent reads it to
# determine what to do next. The runner does NOT control flow.
#
# Pipeline stages (defined in SKILL.md, enforced by Agent):
#   initialized → extracting → extract_done → repair_pending →
#   repairing → repair_done → verifying → verified → finalized / failed
#
# Per-file task checklist (each file has its own tasks):
#   1. Engine extraction  (always)
#   2. Multimodal visual repair  (visual-heavy PDFs only)
#   3. Quality verification  (always)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _state_path(output_root: Path) -> Path:
    return output_root / "_pipeline-state.json"


def write_pipeline_state(output_root: Path, files: list[dict[str, Any]]) -> None:
    """Write the pipeline state file after extraction completes.

    Each file dict contains: source_name, source_path, doc_id, stage,
    needs_repair, output_dir, final_path, error.
    """
    summary = {"done": 0, "repair_pending": 0, "failed": 0}
    for f in files:
        stage = f.get("stage", "pending")
        if stage in summary:
            summary[stage] += 1

    # Determine overall pipeline stage
    if any(f["stage"] == "failed" for f in files):
        pipeline_stage = "extract_done"  # Still proceed with successful files
    else:
        pipeline_stage = "extract_done"

    state = {
        "version": "1.0",
        "pipeline_stage": pipeline_stage,
        "created_at": files[0].get("created_at", _now_iso()),
        "updated_at": _now_iso(),
        "output_root": str(output_root),
        "total_files": len(files),
        "files": files,
        "summary": summary,
    }

    sp = _state_path(output_root)
    sp.parent.mkdir(parents=True, exist_ok=True)
    sp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


def load_state(output_root: Path) -> dict[str, Any] | None:
    """Load existing pipeline state if present. Used by Agent to check progress."""
    sp = _state_path(output_root)
    if not sp.exists():
        return None
    try:
        return json.loads(sp.read_text(encoding="utf-8"))
    except Exception:
        return None


def check_repair(output_root: Path) -> None:
    """Print a report of which files need multimodal repair.

    The Agent uses this to determine what repair work remains.
    """
    state = load_state(output_root)
    if state is None:
        print("[repair-check] No pipeline state found.", file=sys.stderr)
        return

    print(f"[repair-check] Pipeline stage: {state.get('pipeline_stage')}", file=sys.stderr)
    print(f"[repair-check] {state.get('total_files', 0)} file(s):", file=sys.stderr)

    for f in state.get("files", []):
        stage = f["stage"]
        repair_flag = " ← REPAIR NEEDED" if f.get("needs_repair") else ""
        error_info = f" (error: {f.get('error', '')[:80]})" if stage == "failed" else ""
        print(f"  [{stage}] {f['source_name']}{repair_flag}{error_info}", file=sys.stderr)

    # Re-evaluate repair flags based on actual output
    changed = False
    for f in state.get("files", []):
        if f["stage"] in ("extract_done", "done") and not f.get("needs_repair"):
            doc_dir = Path(f.get("output_dir", ""))
            if doc_dir.exists() and _is_visual_heavy_output(doc_dir):
                f["needs_repair"] = True
                f["stage"] = "repair_pending"
                changed = True
                print(f"  [repair-check] {f['source_name']} → flagged for repair", file=sys.stderr)

    if changed:
        state["updated_at"] = _now_iso()
        _write_json(_state_path(output_root), state)

    # Print actionable summary
    pending_repair = [f for f in state.get("files", []) if f.get("needs_repair") and f["stage"] in ("repair_pending", "extract_done")]
    if pending_repair:
        print(f"\n[repair-check] {len(pending_repair)} file(s) require agent multimodal repair:", file=sys.stderr)
        for f in pending_repair:
            doc_dir = Path(f.get("output_dir", ""))
            source_md = doc_dir / "source.md"
            pages_dir = doc_dir / "artifacts" / "pages"
            print(f"  - {f['source_name']}:", file=sys.stderr)
            print(f"    final.md:    {doc_dir / 'final.md'}", file=sys.stderr)
            print(f"    source.md:   {'yes' if source_md.exists() else 'MISSING'}", file=sys.stderr)
            print(f"    screenshots: {'yes' if pages_dir.exists() else 'MISSING'}", file=sys.stderr)
    else:
        print("\n[repair-check] No files require multimodal repair.", file=sys.stderr)


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _is_visual_heavy_output(doc_dir: Path) -> bool:
    """Check if a document's output indicates it needs agent repair.

    v2: 优先读取引擎写出的结构化标记 needs-repair.json（插图级复核，
    纯文本文档 → needs_repair=false，Agent 零视觉参与）。
    旧的关键词扫描（视觉修复版/complex_visual_pdf_path 等）已废弃——
    它们会把所有 PDF 无条件误判为需要视觉修复。
    """
    marker = doc_dir / "needs-repair.json"
    if marker.exists():
        try:
            payload = json.loads(marker.read_text(encoding="utf-8"))
            return bool(payload.get("needs_repair", False))
        except Exception:
            pass  # 标记损坏 → 回退旧启发式
    # 旧版启发式兜底（仅保留可靠信号）
    if (doc_dir / "multimodal-correction-request.json").exists():
        return True
    if (doc_dir / ".multimodal-repair-request.json").exists():
        return True
    final = doc_dir / "final.md"
    if final.exists():
        text = final.read_text(encoding="utf-8", errors="replace")
        if "[待补充]" in text:
            return True
    return False


def _file_needs_visual_repair(src: Path) -> bool:
    """Heuristic: does this file likely need visual repair?"""
    if src.suffix.lower() != ".pdf":
        return False
    name_lower = src.name.lower()
    return any(kw in name_lower for kw in ["ux", "ue", "交互", "视觉", "mockup", "spec"])


def _build_task_list(src: Path, needs_repair: bool) -> list[dict[str, Any]]:
    """Build the per-file task checklist written into the state file."""
    ext = src.suffix.lower()
    tasks = [
        {
            "name": "Engine extraction",
            "status": "pending",
            "description": f"Run {'EFM' if ext != '.pdf' else 'doc-pre/EFM'} engine on {src.name}",
        },
    ]
    if needs_repair:
        tasks.append({
            "name": "Multimodal visual repair",
            "status": "pending",
            "description": "Compare page screenshots with extracted text, rebuild structure",
        })
    tasks.append({
        "name": "Quality verification",
        "status": "pending",
        "description": "Check final.md exists, has content, assets linked correctly",
    })
    if ext == ".pdf":
        tasks.append({
            "name": "Quality gate verification",
            "status": "pending",
            "description": "Multimodal agent verifies hierarchy, callout mapping, flow direction against screenshots",
        })
    return tasks


SUPPORTED = {".pdf", ".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv"}
EFM_SUPPORTED = {".doc", ".docx", ".ppt", ".pptx", ".xls", ".xlsx", ".csv"}
# Extended formats handled by EFM engine.
EFM_EXTRA_SUPPORTED = {
    ".png", ".jpg", ".jpeg", ".bmp", ".gif", ".tif", ".tiff", ".webp", ".svg", ".ico",
    ".html", ".htm", ".md", ".mdx", ".markdown", ".txt", ".rst", ".log",
    ".tsv", ".json", ".yaml", ".yml", ".xml", ".toml", ".ini",
    ".py", ".java", ".kt", ".go", ".rs", ".c", ".cpp", ".h", ".hpp", ".cs",
    ".rb", ".php", ".sh", ".bat", ".ps1", ".sql", ".js", ".ts", ".tsx",
    ".jsx", ".vue", ".svelte", ".css",
}
SUPPORTED |= EFM_EXTRA_SUPPORTED
EXCLUDED_PARTS = {".git", "outputs", "engine-results", "normalized", "artifacts", "__pycache__"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text.rstrip() + "\n", encoding="utf-8")


def write_json(path: Path, data: Any) -> None:
    write_text(path, json.dumps(data, ensure_ascii=False, indent=2))


def load_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def slug(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).replace(" ", " ").replace(" ", "_")
    safe = []
    for ch in text:
        if ch in '<>:"/\\|?*' or ord(ch) < 32:
            safe.append("_")
        elif ch.isalnum() or ch in {"-", "_", ".", "(", ")"} or "一" <= ch <= "鿿":
            safe.append(ch)
        else:
            safe.append("_")
    return re.sub(r"_+", "_", "".join(safe)).strip("_.-")[:80] or "document"


def sha1_8(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:8]


def sanitize_filename(path: Path, tmp_dir: Path) -> Path:
    """Normalize problematic Unicode in filenames that break terminal encoding.

    Creates a sanitized copy in tmp_dir only when the original filename
    contains characters that are likely to cause encoding failures
    (e.g. U+2024 ONE DOT LEADER, non-ASCII dots, invisible chars).
    Returns the original path if no sanitization is needed.
    """
    stem = path.stem
    # Check for characters that commonly cause encoding issues
    problematic = False
    for ch in stem:
        cat = unicodedata.category(ch)
        # Non-printing, format chars, or "other" punctuation that isn't a normal dot/hyphen
        if cat.startswith("C") or (cat == "Po" and ch not in {".", "-", "_", "·"}):
            problematic = True
            break
    if not problematic:
        return path

    # Build a safe filename: keep alnum + CJK + normal punctuation, replace the rest
    safe_chars = []
    for ch in path.name:
        if ch.isalnum() or ch in {"-", "_", ".", "(", ")"} or "一" <= ch <= "鿿":
            safe_chars.append(ch)
        else:
            safe_chars.append("_")
    safe_name = re.sub(r"_+", "_", "".join(safe_chars)).strip("_.-")
    if not safe_name:
        safe_name = "document" + path.suffix
    elif not safe_name.endswith(path.suffix):
        safe_name = safe_name + path.suffix

    tmp_dir.mkdir(parents=True, exist_ok=True)
    safe_path = tmp_dir / safe_name
    # Avoid collision with existing temp files
    if safe_path.exists():
        base = safe_name.rsplit(path.suffix, 1)[0] if path.suffix else safe_name
        counter = 1
        while safe_path.exists():
            safe_path = tmp_dir / f"{base}_{counter}{path.suffix}"
            counter += 1

    shutil.copy2(path, safe_path)
    return safe_path


def doc_id(path: Path) -> str:
    return f"{slug(path.stem)}-{sha1_8(path)}"


def py_cmd(spec: str) -> list[str]:
    if spec.endswith(" -3"):
        exe, arg = spec.rsplit(" ", 1)
        return [exe, arg]
    return [spec]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="MarkFileDown runner — single-engine format routing")
    p.add_argument("--input-path", default="")
    p.add_argument("--input-file", action="append", default=[])
    p.add_argument("--output-root", required=True)
    p.add_argument("--recurse", default="on", choices=["on", "off"])
    p.add_argument("--python-exe", default=sys.executable)
    p.add_argument("--check-repair", action="store_true", help="Check which files need multimodal repair")
    p.add_argument("--quality-gate", action="store_true", help="Run Stage 5 multimodal quality gate (PDF only)")
    return p.parse_args()


def excluded(path: Path, root: Path | None = None) -> bool:
    try:
        parts = path.relative_to(root).parts if root is not None else path.parts
    except ValueError:
        parts = path.parts
    return any(part in EXCLUDED_PARTS for part in parts)


def discover(args: argparse.Namespace) -> list[Path]:
    files: list[Path] = []
    if args.input_path:
        root = Path(args.input_path).resolve()
        if root.is_file():
            files.append(root)
        elif root.is_dir():
            pat = "**/*" if args.recurse == "on" else "*"
            files.extend(p for p in root.glob(pat) if p.is_file() and not excluded(p, root))
        else:
            raise FileNotFoundError(root)
    for item in args.input_file:
        p = Path(item).resolve()
        if not p.is_file():
            raise FileNotFoundError(p)
        files.append(p)
    allowed = SUPPORTED
    out: list[Path] = []
    seen: set[str] = set()
    for p in files:
        key = str(p.resolve()).lower()
        if key not in seen and p.suffix.lower() in allowed and not p.name.startswith("~$"):
            seen.add(key)
            out.append(p.resolve())
    if not out:
        raise FileNotFoundError("No supported input files were found.")
    return out


def run(command: list[str], cwd: Path, log: Path) -> dict[str, Any]:
    log.parent.mkdir(parents=True, exist_ok=True)
    try:
        env = os.environ.copy()
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONUTF8"] = "1"
        cp = subprocess.run(command, cwd=str(cwd), env=env, capture_output=True, text=True, encoding="utf-8", errors="replace", check=False)
        text = (cp.stdout or "") + (cp.stderr or "")
        log.write_text(text, encoding="utf-8")
        return {"exit_code": cp.returncode, "log_path": str(log), "log_excerpt": re.sub(r"\s+", " ", text).strip()[:700]}
    except Exception as exc:
        msg = f"{type(exc).__name__}: {exc}"
        log.write_text(msg + "\n", encoding="utf-8")
        return {"exit_code": -1, "log_path": str(log), "log_excerpt": msg}


def find_doc_root(root: Path) -> Path | None:
    if not root.exists():
        return None
    finals = [p for p in root.iterdir() if p.is_dir() and (p / "final.md").exists()]
    if finals:
        return max(finals, key=lambda p: (p / "final.md").stat().st_mtime)
    dirs = [p for p in root.iterdir() if p.is_dir()]
    return max(dirs, key=lambda p: p.stat().st_mtime) if dirs else None


# ── Format-based engine routing ────────────────────────────────────────

ENGINE_DIRS = {
    "doc-pre": "doc-pre-allinone-skill-0508",
    "efm": "efm-multidoc-markdown-bundle",
}
RUNNER_FILES = {
    "doc-pre": "pipeline_runner.py",
    "efm": "bundle_runner.py",
}
# EFM engine's PDF route args.
EFM_PDF_ROUTE_ARGS = {
    "--source-format": "pdf",
    "--ocr": "on",
    "--asset-links": "on",
}


def route_engine(source: Path) -> str:
    """Route to appropriate engine based on file extension.

    PDFs → EFM engine (produces structured OCR with bbox for ASCII reconstruction)
    Office → EFM engine (OOXML extraction)
    Extended formats → EFM engine
    """
    return "efm"


# ── ASCII structure reconstruction for image-only / OCR-heavy PDFs ────

def _detect_image_only_pdf(engine_result_root: Path) -> bool:
    """Check if the engine output indicates an image-only or OCR-heavy PDF."""
    # Check for EFM's multimodal repair brief
    if (engine_result_root / "multimodal-repair-brief.json").exists():
        return True
    # Check integrity metrics
    metrics = load_json(engine_result_root / "integrity-metrics.json")
    raw_total = metrics.get("raw_block_total", 0)
    page_count = metrics.get("page_count", 1) or 1
    avg = raw_total / page_count
    return avg < 50


def _copy_evidence_data(engine_result_root: Path, doc_dir: Path) -> None:
    """Copy evidence data from engine output before cleanup."""
    ev_src = engine_result_root / "evidence"
    ev_dst = doc_dir / "_evidence"
    if ev_src.exists() and not ev_dst.exists():
        shutil.copytree(ev_src, ev_dst)


def _parse_efm_final_md(final_md_path: Path) -> list[dict[str, Any]]:
    """Parse EFM engine's final.md to extract page-level structured data.

    EFM's final.md has this structure per page:
    - `## Page Title` — page heading
    - `![N](artifacts/pages/page-NNNN-full.png)` — page screenshot ref
    - `> **[截图区域]** 以下文字来自页面截图插图：` — screenshot zone block
    - Rest is content zone text

    Returns list of page dicts with zone-separated text.
    """
    if not final_md_path.exists():
        return []

    text = final_md_path.read_text(encoding="utf-8", errors="replace")
    pages = []

    # Split by page separators (--- or ## Page N)
    # First, try to find page sections
    page_pattern = re.compile(r'\n---\n|\n## (?!\s*MarkFileDown|Page \d{2})')

    # Split by the existing page structure in EFM output
    sections = re.split(r'\n---\n', text)

    for section in sections:
        section = section.strip()
        if not section:
            continue

        page_data: dict[str, Any] = {
            "title": "",
            "top_zone": [],
            "screenshot_zone": [],
            "content_zone": [],
        }

        lines = section.splitlines()
        in_screenshot_block = False
        found_title = False

        for line in lines:
            stripped = line.strip()

            # Skip empty lines
            if not stripped:
                continue

            # Skip image references
            if stripped.startswith("!["):
                continue

            # Skip metadata lines
            if stripped.startswith("> 该版本") or stripped.startswith("> Baseline"):
                continue

            # Title detection
            if stripped.startswith("## ") and not found_title:
                page_data["title"] = stripped[3:].strip()
                found_title = True
                continue

            # Skip document overview headers
            if stripped.startswith("## ") and stripped in (
                "## 文档概览", "## 修复后的章节骨架", "## 附录：页级视觉资产",
                "## 页面截图"
            ):
                continue

            # Screenshot zone block
            if "**[截图区域]**" in stripped:
                in_screenshot_block = True
                continue

            # Skip blockquote markers
            if stripped.startswith(">"):
                clean = stripped.lstrip("> ").strip()
                if clean and clean != "**[截图区域]** 以下文字来自页面截图插图：":
                    if in_screenshot_block:
                        page_data["screenshot_zone"].append(clean)
                continue

            # If we were in screenshot block but hit non-blockquote text, end block
            if in_screenshot_block and not stripped.startswith(">"):
                in_screenshot_block = False

            # Content zone text
            if not in_screenshot_block:
                page_data["content_zone"].append(stripped)

        if page_data["title"] or page_data["content_zone"]:
            pages.append(page_data)

    return pages


def _build_ascii_page_from_efm(page: dict[str, Any], page_num: int) -> str:
    """Convert parsed EFM page data to clean ASCII-structured Markdown."""
    lines: list[str] = []

    title = page.get("title", "")
    top_items = page.get("top_zone", [])
    screenshot_items = page.get("screenshot_zone", [])
    content_items = page.get("content_zone", [])

    # ── Title ──
    if title:
        lines.append(f"## {title}")
        lines.append("")
    elif top_items:
        # Use first meaningful top item as title
        for t in top_items:
            if len(t) > 3 and not _filter_noise(t):
                lines.append(f"## {t}")
                lines.append("")
                break

    # ── Screenshot zone: UI labels as compact reference ──
    if screenshot_items:
        # Filter noise and group
        clean_labels = [t for t in screenshot_items if not _filter_noise(t) and len(t) > 1]
        if clean_labels:
            # Check for tabular patterns (multiple items that look like table cells)
            has_table = any(
                "|" in t or "Tab" in t or "一级" in t or "二级" in t
                for t in clean_labels
            )
            if has_table:
                lines.append("**界面控件：**")
                lines.append("")
                for t in clean_labels:
                    if "|" in t:
                        # Already a table row
                        lines.append(f"> {t}")
                    else:
                        lines.append(f"> `{t}`")
                lines.append("")
            else:
                # UI labels as compact list
                lines.append("**界面标注：**")
                lines.append("")
                # Group short labels together
                short_labels = [t for t in clean_labels if len(t) <= 8]
                long_labels = [t for t in clean_labels if len(t) > 8]
                if short_labels:
                    short_formatted = " | ".join(f"`{t}`" for t in short_labels[:10])
                    lines.append(f"> {short_formatted}")
                    if len(short_labels) > 10:
                        short_formatted2 = " | ".join(f"`{t}`" for t in short_labels[10:20])
                        lines.append(f"> {short_formatted2}")
                for t in long_labels:
                    lines.append(f"> {t}")
                lines.append("")

    # ── Content zone: functional descriptions ──
    if content_items:
        # Filter noise
        clean_content = [t for t in content_items if not _filter_noise(t) and len(t) >= 3]
        if clean_content:
            # Detect structure patterns
            has_numbered = any(re.match(r"^[\d①-⓿]+[\.、．]", t) for t in clean_content)
            has_toast = any("toast" in t or "提示" in t for t in clean_content)
            has_rules = any(kw in t for t in clean_content for kw in [
                "用户通过", "启用", "开启后", "点击", "关闭", "打开",
                "操作过频", "故障", "目标状态", "依据信号"
            ])

            if has_numbered or has_rules:
                lines.append("**功能说明：**")
                lines.append("")
                for t in clean_content:
                    if re.match(r"^[\d①-⓿]+[\.、．]", t):
                        lines.append(f"- {t}")
                    elif has_toast and ("toast" in t or "提示" in t):
                        lines.append(f"- {t}")
                    else:
                        lines.append(t)
                lines.append("")
            elif has_toast:
                lines.append("**交互规则：**")
                lines.append("")
                for t in clean_content:
                    lines.append(f"- {t}")
                lines.append("")
            else:
                # Plain text — just output
                for t in clean_content:
                    lines.append(t)
                lines.append("")

    # ── ASCII flow diagram for pages with interaction sequences ──
    flow_keywords = ["点击", "开启", "关闭", "确认", "取消", "弹窗",
                     "确定", "弹框", "条件", "判断", "→", "然后"]
    flow_items = [t for t in content_items if any(kw in t for kw in flow_keywords)]
    if len(flow_items) >= 3:
        lines.append("**页面流转：**")
        lines.append("")
        lines.append("```")
        # Extract key actions
        actions = []
        for t in flow_items[:6]:
            for kw in ["点击", "开启", "关闭", "确认", "取消"]:
                if kw in t:
                    # Extract the action + target
                    idx = t.find(kw)
                    action = t[idx:idx+20].rstrip("，。,.：:")
                    if action not in actions:
                        actions.append(action)
                    break
        if actions:
            lines.append("  [触发]")
            for i, action in enumerate(actions):
                lines.append("    ↓")
                lines.append(f"  [{action}]")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _build_ascii_markdown(doc_dir: Path) -> str:
    """Build clean ASCII-structured Markdown from EFM engine output.

    Parses the EFM engine's final.md structure and rebuilds it as
    clean Markdown with:
    - Zone-based layout (title / screenshot labels / content)
    - ASCII flow diagrams for interaction sequences
    - UI labels as compact reference blocks
    - Proper heading/list structure
    """
    # Try parsing EFM's final.md structure
    final_md = doc_dir / "final.md"
    pages = _parse_efm_final_md(final_md)

    if not pages:
        # Fallback: use source.md
        source_md = doc_dir / "source.md"
        if source_md.exists():
            text = source_md.read_text(encoding="utf-8", errors="replace")
            idx = text.find("\n## ")
            if idx > 0:
                text = text[idx:]
            return text.strip() + "\n"
        return ""

    lines: list[str] = []
    for i, page in enumerate(pages, 1):
        page_md = _build_ascii_page_from_efm(page, i)
        if page_md:
            lines.append(page_md)
            lines.append("---")
            lines.append("")

    # Add page screenshot references at the end
    pages_dir = doc_dir / "artifacts" / "pages"
    if pages_dir.exists():
        lines.append("## 页面截图参考")
        lines.append("")
        for img in sorted(pages_dir.glob("page-*-full.png")):
            pnum = int(img.stem.split('-')[1])
            lines.append(f"![Page {pnum}]({img.relative_to(doc_dir).as_posix()})")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


# ── Zone classification for UE spec documents ─────────────────────────
# UE spec documents follow a 3-zone layout per page:
#   TOP (y: 0-20%):     page titles, annotations, designer info
#   MIDDLE (y: 20-60%): device screenshots with embedded UI labels
#   BOTTOM (y: 60-100%): numbered functional descriptions with rules

_ZONE_TOP = "top"
_ZONE_SCREENSHOT = "screenshot"
_ZONE_CONTENT = "content"

_CONTENT_KEYWORDS = [
    "用户通过", "启用/禁用", "用户点击", "点击打开", "点击关闭",
    "开启后，", "关闭后，", "不满足", "无法从",
    "请尽快维修", "请尽快处理", "按钮置灰", "高亮",
    "操作过频", "锁止状态", "已经", "故障显示",
    "可方便地", "可减少", "可更加", "可重新",
    "踩下刹车", "踩下制动", "系好安全带",
    "弹框消失", "流程结束", "确认弹窗", "二次确认",
    "依据信号", "反馈显示", "确定关闭", "显示toast",
    # Auto/Seat/HVAC domain-specific functional description patterns
    "后除霜", "前除霜", "外后视镜", "后视镜加热",
    "出风模式", "内外循环", "温度同步",
    "pm2.5", "PM2.5", "空气质量", "净化",
    "互斥", "提示语", "不可用", "通风", "加热", "按摩",
    "新风系统", "自定义通风", "座舱",
    "默认态", "开启态", "关闭态", "置灰态",
    "电源", "档位", "ACC", "空调系统",
    "toast", "提醒", "播报", "TTS",
]

_UI_LABEL_INDICATORS = [
    "Tab标签", "一级", "二级", "制冷中", "℃", "Bar",
    "icon", "插图", "UI可以", "READY",
    "（-40）", "（-20）", "标准(0)", "21:05",
]


def _detect_zone(y_norm: float, text: str) -> str:
    """Classify OCR item zone based on y position and content keywords."""
    if y_norm < 200:
        return _ZONE_TOP
    if y_norm >= 600:
        return _ZONE_CONTENT
    # Middle zone: check for content override
    has_content = any(kw in text for kw in _CONTENT_KEYWORDS)
    is_ui = any(kw in text for kw in _UI_LABEL_INDICATORS)
    if has_content and not is_ui:
        return _ZONE_CONTENT
    return _ZONE_SCREENSHOT


def _filter_noise(text: str) -> bool:
    """Return True if text is UI noise and should be skipped."""
    if not text or len(text.strip()) < 2:
        return True
    s = text.strip()
    # Skip time patterns
    if re.match(r"^\d{1,2}:\d{2}$", s):
        return True
    # Skip pure hex colors
    if re.match(r"^[0-9A-Fa-f]{6}$", s):
        return True
    # Skip known noise
    noise = {"READY", "Bar", "插图", "icon", "con", "PO"}
    if s in noise:
        return True
    # Skip very short fragments that aren't meaningful
    if len(s) <= 3 and not any("一" <= c <= "鿿" for c in s):
        return True
    return False


def _build_ascii_page_structure(ocr_items: list[dict[str, Any]], page_num: int) -> str:
    """Build ASCII-structured Markdown for one page from OCR items with bbox."""
    # Tag items with zones
    for item in ocr_items:
        text = item.get("text", "")
        y = item.get("y_center", 500)
        item["_zone"] = _detect_zone(y, text)

    lines: list[str] = []

    # ── TOP zone: page title ──
    top_items = sorted(
        [i for i in ocr_items if i.get("_zone") == _ZONE_TOP],
        key=lambda x: (x.get("y_center", 0), x.get("x_center", 0))
    )
    top_texts = []
    for item in top_items:
        t = item["text"].strip()
        if not _filter_noise(t):
            top_texts.append(t)

    if top_texts:
        # First meaningful text is the page title
        title = top_texts[0]
        lines.append(f"## {title}")
        lines.append("")
        # Rest of top items as metadata
        if len(top_texts) > 1:
            meta = [t for t in top_texts[1:] if len(t) > 3]
            if meta:
                lines.append(f"> {' | '.join(meta)}")
                lines.append("")

    # ── SCREENSHOT zone: UI labels as reference block ──
    screenshot_items = sorted(
        [i for i in ocr_items if i.get("_zone") == _ZONE_SCREENSHOT],
        key=lambda x: (x.get("y_center", 0), x.get("x_center", 0))
    )
    ui_labels = []
    for item in screenshot_items:
        t = item["text"].strip()
        if not _filter_noise(t) and len(t) > 1:
            ui_labels.append(t)

    if ui_labels:
        # Group UI labels by vertical proximity (rows)
        rows = _group_into_rows(ui_labels, screenshot_items)
        if rows:
            lines.append("**界面截图区域标注：**")
            lines.append("")
            for row in rows:
                if len(row) == 1:
                    lines.append(f"> `{row[0]}`")
                else:
                    # Multiple items on same row → table-like layout
                    row_formatted = " | ".join(f"`{t}`" for t in row)
                    lines.append(f"> {row_formatted}")
            lines.append("")

    # ── CONTENT zone: functional descriptions ──
    content_items = sorted(
        [i for i in ocr_items if i.get("_zone") == _ZONE_CONTENT],
        key=lambda x: (x.get("y_center", 0), x.get("x_center", 0))
    )
    content_texts = []
    for item in content_items:
        t = item["text"].strip()
        if not _filter_noise(t) and len(t) >= 4:
            content_texts.append(t)

    if content_texts:
        # Detect if content has numbered items → list structure
        numbered = [t for t in content_texts if re.match(r"^[\d①-⓿]+[\.、．]", t)]
        if numbered and len(numbered) > len(content_texts) * 0.3:
            # It's a numbered list
            lines.append("**功能说明：**")
            lines.append("")
            for t in content_texts:
                if re.match(r"^[\d①-⓿]+[\.、．]", t):
                    lines.append(f"- {t}")
                else:
                    lines.append(f"  {t}")
            lines.append("")
        else:
            # Check for toast/rules patterns → list
            rules = [t for t in content_texts if any(
                kw in t for kw in ["toast", "提示", "开启后", "关闭后", "点击", "启用", "操作"]
            )]
            if rules and len(rules) > len(content_texts) * 0.4:
                lines.append("**交互规则：**")
                lines.append("")
                for t in content_texts:
                    lines.append(f"- {t}")
                lines.append("")
            else:
                # Plain text content
                for t in content_texts:
                    lines.append(t)
                lines.append("")

    # ── ASCII flow diagram for pages with arrow/transition hints ──
    flow_hints = [t for t in content_texts if any(
        kw in t for kw in ["点击", "→", "然后", "最后", "确认", "取消", "弹窗",
                          "确定", "打开", "关闭", "条件", "判断"]
    )]
    if len(flow_hints) >= 3:
        lines.append("**页面流转：**")
        lines.append("")
        lines.append("```")
        # Build a simple ASCII flow from sequential hints
        steps = []
        for t in flow_hints[:5]:
            # Extract the action keyword
            for kw in ["点击", "开启", "关闭", "确认", "取消"]:
                if kw in t:
                    steps.append(t[:30])
                    break
        if steps:
            lines.append(f"  [用户操作]")
            for i, step in enumerate(steps):
                arrow = "    ↓" if i < len(steps) - 1 else "    ↓"
                lines.append(arrow)
                lines.append(f"  [{step}]")
        lines.append("```")
        lines.append("")

    return "\n".join(lines)


def _group_into_rows(texts: list[str], items: list[dict]) -> list[list[str]]:
    """Group OCR items into rows based on y_center proximity."""
    if not items:
        return []
    # Group by y_center with tolerance of 30
    groups: list[list[str]] = []
    current_y = items[0].get("y_center", 0)
    current_row: list[str] = [texts[0]] if texts else []

    for i, item in enumerate(items[1:], 1):
        y = item.get("y_center", 0)
        if abs(y - current_y) <= 30:
            if i < len(texts):
                current_row.append(texts[i])
        else:
            if current_row:
                groups.append(current_row)
            current_row = [texts[i]] if i < len(texts) else []
            current_y = y
    if current_row:
        groups.append(current_row)
    return groups


def _clean_doc_pre_markdown(text: str) -> str:
    """Post-process doc-pre's final.md to reduce over-structured ### headings.

    The doc-pre engine often outputs every OCR line as a `### heading`.
    This function demotes consecutive ### headings to:
    - Plain text if they look like UI labels / short fragments
    - List items if they look like functional descriptions
    - Keeps only the first heading per page as a real section heading
    """
    lines = text.splitlines()
    result: list[str] = []
    consecutive_headings: list[str] = []
    in_fence = False

    def flush_headings():
        """Flush accumulated consecutive headings with smart structuring."""
        nonlocal consecutive_headings
        if not consecutive_headings:
            return

        # Filter out UI noise (short fragments, timestamps, status labels)
        noise_patterns = {
            "READY", "OFF", "ON", "Bar", "插图", "icon", "con",
        }
        meaningful = []
        for h in consecutive_headings:
            stripped = h.strip().lstrip("#").strip()
            # Skip noise patterns
            if stripped in noise_patterns:
                continue
            # Skip pure numbers or very short fragments (< 2 chars)
            if len(stripped) < 2:
                continue
            # Skip time-like patterns (21:05)
            if re.match(r"^\d{1,2}:\d{2}$", stripped):
                continue
            # Skip pure hex color codes
            if re.match(r"^[0-9A-Fa-f]{6}$", stripped):
                continue
            meaningful.append(stripped)

        if len(meaningful) == 1:
            # Single heading — keep as section heading
            result.append(f"### {meaningful[0]}")
        elif len(meaningful) == 0:
            pass  # All noise, skip entirely
        else:
            # Multiple items — use first as heading, rest as list or text
            result.append(f"### {meaningful[0]}")
            # Check if the rest look like functional descriptions (toast messages, rules)
            all_descriptions = all(
                any(kw in m for kw in ["用户", "启用", "开启后", "点击", "关闭", "打开",
                                        "显示toast", "提示", "操作", "故障", "目标状态",
                                        "请选择", "可选择", "依据信号"])
                for m in meaningful[1:]
            )
            if all_descriptions and len(meaningful) > 1:
                for m in meaningful[1:]:
                    result.append(f"- {m}")
            else:
                for m in meaningful[1:]:
                    result.append(m)

        result.append("")  # Blank line after section
        consecutive_headings = []

    for line in lines:
        # Preserve code fences
        if line.lstrip().startswith("```"):
            flush_headings()
            in_fence = not in_fence
            result.append(line)
            continue
        if in_fence:
            result.append(line)
            continue

        # Detect ### headings (but not ## or #)
        if re.match(r"^#{3}\s", line) and not re.match(r"^#{1,2}\s", line):
            consecutive_headings.append(line)
        else:
            flush_headings()
            result.append(line)

    flush_headings()  # Flush any remaining

    # Clean up excessive blank lines (max 2 consecutive)
    cleaned = re.sub(r"\n{4,}", "\n\n\n", "\n".join(result))
    return cleaned.strip() + "\n"


# ── Quality gate: detect & resolve duplicate output dirs ──────────────

def _content_hash(doc_dir: Path) -> str | None:
    """Return SHA1 of final.md content, or None if missing."""
    final = doc_dir / "final.md"
    if not final.exists():
        return None
    return sha1_8(final)


def quality_gate(output_root: Path) -> None:
    """Detect duplicate output directories (same file content, different names)
    and merge them, keeping the directory with the more descriptive name.

    This prevents the common failure mode where a sanitized temp copy of the
    input file produces a second output directory alongside the original.
    """
    dirs = [p for p in output_root.iterdir() if p.is_dir() and (p / "final.md").exists()]
    if len(dirs) < 2:
        return

    # Group by content hash
    by_hash: dict[str, list[Path]] = {}
    for d in dirs:
        h = _content_hash(d)
        if h is not None:
            by_hash.setdefault(h, []).append(d)

    for h, group in by_hash.items():
        if len(group) < 2:
            continue

        # Keep the dir whose name contains more non-ASCII (likely the original)
        def name_score(p: Path) -> int:
            return sum(1 for c in p.name if ord(c) > 127)

        group.sort(key=name_score, reverse=True)
        keeper = group[0]
        for dup in group[1:]:
            # Copy any assets from dup that don't exist in keeper
            for asset_name in ["artifacts", "assets"]:
                dup_src = dup / asset_name
                keeper_dst = keeper / asset_name
                if dup_src.exists():
                    if not keeper_dst.exists():
                        shutil.copytree(dup_src, keeper_dst)
                    else:
                        # Merge individual files
                        for item in dup_src.rglob("*"):
                            if item.is_file():
                                rel = item.relative_to(dup_src)
                                target = keeper_dst / rel
                                if not target.exists():
                                    target.parent.mkdir(parents=True, exist_ok=True)
                                    shutil.copy2(item, target)
            # Also copy source.md if keeper doesn't have it
            if not (keeper / "source.md").exists() and (dup / "source.md").exists():
                shutil.copy2(dup / "source.md", keeper / "source.md")
            # Remove the duplicate directory
            try:
                shutil.rmtree(dup)
                print(f"  [quality-gate] Merged duplicate dir into: {keeper.name} (removed: {dup.name})")
            except OSError:
                pass


# ── Process single document ────────────────────────────────────────────

def process(source: Path, output_root: Path, args: argparse.Namespace, skill_root: Path) -> dict[str, Any]:
    # ── Quality gate step 1: normalize filename before processing ──
    # Prevents duplicate output dirs when original filename has problematic
    # Unicode characters (e.g. U+2024 ONE DOT LEADER) that cause terminal
    # encoding errors, forcing the user to create a sanitized temp copy.
    tmp_dir = output_root / ".sanitize-tmp"
    actual_source = sanitize_filename(source, tmp_dir)

    doc_dir = output_root / doc_id(actual_source)
    doc_dir.mkdir(parents=True, exist_ok=True)
    logs = doc_dir / "logs"
    engine_name = route_engine(source)
    engine_dir = skill_root / "engines" / ENGINE_DIRS[engine_name]
    engine_out = doc_dir / "engine-results" / engine_name
    engine_out.mkdir(parents=True, exist_ok=True)
    py = py_cmd(args.python_exe)

    # Build engine command (all formats route to EFM)
    runner = engine_dir / RUNNER_FILES[engine_name]
    ext = source.suffix.lower()
    cmd = py + [str(runner)]

    if ext == ".pdf":
        cmd += [
            "--input-path", str(actual_source),
            "--output-root", str(engine_out),
            "--source-format", "pdf",
            "--markdown-style", "technical",
            "--pdf-agent-validation", "off",
            "--asset-links", "on",
            "--ocr", "on",
        ]
    elif ext in {".doc", ".docx"}:
        cmd += [
            "--input-path", str(actual_source),
            "--output-root", str(engine_out),
            "--source-format", ext.lstrip("."),
            "--markdown-style", "technical",
            "--pdf-agent-validation", "off",
            "--asset-links", "on",
            "--ocr", "on",
            "--recurse", "off",
        ]
    elif ext in {".ppt", ".pptx"}:
        cmd += [
            "--input-path", str(actual_source),
            "--output-root", str(engine_out),
            "--source-format", ext.lstrip("."),
            "--markdown-style", "technical",
            "--pdf-agent-validation", "off",
            "--asset-links", "on",
            "--ocr", "on",
            "--recurse", "off",
        ]
    elif ext in {".xls", ".xlsx", ".csv"}:
        cmd += [
            "--input-path", str(actual_source),
            "--output-root", str(engine_out),
            "--source-format", ext.lstrip("."),
            "--markdown-style", "technical",
            "--pdf-agent-validation", "off",
            "--asset-links", "on",
            "--ocr", "on",
            "--recurse", "off",
        ]
    else:
        # Extended formats (images, HTML, text, data, code)
        cmd += [
            "--input-path", str(actual_source),
            "--output-root", str(engine_out),
            "--source-format", "auto",
            "--markdown-style", "technical",
            "--pdf-agent-validation", "off",
            "--asset-links", "on",
            "--ocr", "on",
            "--recurse", "off",
        ]

    result = run(cmd, engine_dir, logs / f"{engine_name}.log")

    # Find the engine's output directory
    engine_result_root = find_doc_root(engine_out)
    if engine_result_root is None:
        # EFM might have put output directly in engine_out
        if (engine_out / "final.md").exists():
            engine_result_root = engine_out
        else:
            raise RuntimeError(f"Engine {engine_name} failed to produce output for {source.name}. Log: {result.get('log_excerpt', '')}")

    # Copy final.md and assets to doc_dir (clean, no decoration)
    final_src = engine_result_root / "final.md"
    if final_src.exists():
        content = final_src.read_text(encoding="utf-8", errors="replace")
        # If it starts with "## MarkFileDown Decision", strip the header block
        if "## MarkFileDown Decision" in content:
            sep = content.find("\n---\n")
            if sep > 0:
                body = content[sep + 5:]
                if not body.startswith("#"):
                    body = body.lstrip()
                content = body
        # Post-process: clean up doc-pre's over-structured ### headings
        content = _clean_doc_pre_markdown(content)
        write_text(doc_dir / "final.md", content)
    else:
        raise RuntimeError(f"Engine {engine_name} did not produce final.md for {actual_source.name}")

    # Copy assets directory if it exists
    for asset_dir_name in ["artifacts", "assets"]:
        asset_src = engine_result_root / asset_dir_name
        if asset_src.exists():
            asset_dst = doc_dir / asset_dir_name
            if asset_dst.exists():
                shutil.rmtree(asset_dst)
            shutil.copytree(asset_src, asset_dst)

    # For image-only / OCR-heavy PDFs, rebuild final.md with ASCII structure
    # First copy evidence data before cleanup, then use it for reconstruction
    if source.suffix.lower() == ".pdf" and _detect_image_only_pdf(engine_result_root):
        _copy_evidence_data(engine_result_root, doc_dir)
        ascii_md = _build_ascii_markdown(doc_dir)
        if ascii_md and len(ascii_md.strip()) > 50:
            write_text(doc_dir / "final.md", ascii_md)

    # Copy source.md (keep it for reference)
    source_src = engine_result_root / "source.md"
    if source_src.exists():
        shutil.copy2(source_src, doc_dir / "source.md")

    # Copy structured needs-repair marker (v2: runner 判定依据；文本型 PDF 不产生或为 false)
    marker_src = engine_result_root / "needs-repair.json"
    if marker_src.exists():
        shutil.copy2(marker_src, doc_dir / "needs-repair.json")

    # Clean up evidence temp dir
    ev_temp = doc_dir / "_evidence"
    if ev_temp.exists():
        shutil.rmtree(ev_temp)

    # Clean up engine-results dir (keep only what we copied)
    if engine_out.exists():
        try:
            shutil.rmtree(engine_out)
        except OSError:
            pass  # Best-effort cleanup; output is already copied

    # Clean up logs
    if logs.exists():
        shutil.rmtree(logs)

    # Clean up empty engine-results parent
    engine_results_parent = doc_dir / "engine-results"
    if engine_results_parent.exists() and not any(engine_results_parent.iterdir()):
        engine_results_parent.rmdir()

    # ── Clean up sanitized temp copy (ONLY after engine has finished) ──
    # Bug fix: previously this was called too early, before the engine
    # could read the sanitized temp file, causing FileNotFoundError.
    try:
        if actual_source != source and tmp_dir.exists():
            shutil.rmtree(tmp_dir)
    except OSError:
        pass  # Best-effort cleanup

    return {
        "source_name": actual_source.name,
        "source_path": str(actual_source),
        "source_format": actual_source.suffix.lower().lstrip("."),
        "output_root": str(doc_dir),
        "final_path": str(doc_dir / "final.md"),
    }


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parent
    output_root = Path(args.output_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)

    # ── Check for existing state (Agent reads this to resume) ──
    existing_state = load_state(output_root)
    created_at = existing_state["created_at"] if existing_state else _now_iso()

    files = discover(args)

    # ── Run extraction for all files ──
    file_states: list[dict[str, Any]] = []
    for i, src in enumerate(files, 1):
        fid = doc_id(src)
        file_state: dict[str, Any] = {
            "index": i,
            "source_name": src.name,
            "source_path": str(src),
            "source_format": src.suffix.lower().lstrip("."),
            "doc_id": fid,
            "stage": "pending",
            "needs_repair": False,
            "tasks": _build_task_list(src, _file_needs_visual_repair(src)),
            "output_dir": "",
            "final_path": "",
            "error": "",
            "updated_at": _now_iso(),
        }

        try:
            result = process(src, output_root, args, root)
            print(f"OK: {src.name} -> {result['final_path']}")

            doc_dir = Path(result["output_root"])
            needs_repair = _is_visual_heavy_output(doc_dir)

            file_state.update({
                "stage": "repair_pending" if needs_repair else "extract_done",
                "needs_repair": needs_repair,
                "output_dir": result["output_root"],
                "final_path": result["final_path"],
            })
        except Exception as exc:
            msg = str(exc)
            print(f"ERROR: {src.name}: {msg}", file=sys.stderr)
            file_state.update({
                "stage": "failed",
                "error": msg,
            })

        file_states.append(file_state)

    # ── Write final state file (Agent reads this to determine next step) ──
    write_pipeline_state(output_root, file_states)

    # ── Summary ──
    total = len(file_states)
    done = sum(1 for f in file_states if f["stage"] != "failed")
    failed = total - done
    repair_needed = sum(1 for f in file_states if f.get("needs_repair"))

    print(f"\nProcessed {total} document(s): {done} succeeded, {failed} failed.")
    print(f"Output root: {output_root}")

    if repair_needed > 0:
        print(f"\n[state] ⚠ {repair_needed} file(s) need agent multimodal repair.", file=sys.stderr)
        print(f"[state] Read state file: {_state_path(output_root)}", file=sys.stderr)
        print(f"[state] Then run: py -3 {Path(__file__).resolve()} --check-repair --output-root {output_root}", file=sys.stderr)

    if failed > 0:
        sys.exit(1)


if __name__ == "__main__":
    args = parse_args()
    if args.check_repair:
        check_repair(Path(args.output_root).resolve())
    else:
        main()
