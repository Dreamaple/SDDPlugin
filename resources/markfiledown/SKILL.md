---
name: markfiledown-0509
description: "Convert PDF, DOCX, PPTX, XLSX, or mixed document folders to clean Markdown. PDFs are processed text-first (docx-origin text layers need no OCR); visual review is scoped to embedded illustrations only (needs-repair.json). Use for document-to-markdown conversion. Triggers: 文档转markdown, markfiledown, /markfiledown.pipeline, document to markdown, convert docs to md. Do NOT use for: reading a single small file; doing spec writing (use speckit-specify-skill after parsing)."
---

# MarkFileDown 0509

Converts office documents to clean Markdown. Routes by format:
- **PDF** → doc-pre engine (text-first, OCR fallback, multimodal repair for visual/UX PDFs)
- **DOCX/PPTX/XLSX** → EFM engine (OOXML extraction, visual-first for PPTX)

## State File (Agent Protocol)

The runner writes `<outputRoot>/_pipeline-state.json` after extraction. The Agent reads this file to determine what to do next. **The runner never controls flow — only the Agent does.**

### State File Structure

```jsonc
{
  "version": "1.0",
  "pipeline_stage": "extract_done",  // what the runner just finished
  "total_files": 2,
  "summary": { "done": 0, "repair_pending": 2, "failed": 0 },
  "files": [
    {
      "index": 1,
      "source_name": "设置UE.pdf",
      "doc_id": "设置UE-d0af8040",
      "stage": "repair_pending",     // current file status
      "needs_repair": true,          // flag: needs Agent visual repair
      "tasks": [                     // checklist — Agent marks done as it works
        { "name": "Engine extraction",      "status": "pending" },
        { "name": "Multimodal visual repair", "status": "pending" },
        { "name": "Quality verification",    "status": "pending" }
      ],
      "output_dir": "...",           // where the output lives
      "final_path": ".../final.md",  // path to the deliverable
      "error": ""                    // empty = no error
    }
  ]
}
```

### Pipeline Stage Map

```
Runner writes: extract_done  ←  extraction complete, here are the results
Agent drives:  extract_done → repair_pending → repair_done → verified → finalized
```

The runner only ever writes `extract_done`. The Agent advances the state by editing the JSON directly.

### Per-File Task Checklist

Each file gets 2–5 tasks:

| Task | Always? | When skipped |
|------|---------|--------------|
| Engine extraction | ✅ | — |
| Multimodal visual repair | UX/UE PDFs only | Non-visual documents |
| Quality verification | ✅ | — |
| ASCII cross-verification | PDF visual-heavy only | Non-PDF or non-visual documents |
| Quality gate verification | PDF only | Non-PDF documents |

**Task `status` values:** `pending` → `done` (Agent updates as it completes each task).

## Entry Command

```markdown
/markfiledown.pipeline
Input path: @docs
Output root: output/markfiledown-0509
```

Terminal fallback:

```powershell
.\markfiledown-0509\run.ps1 -InputPath ".\docs" -OutputRoot ".\output\markfiledown-0509"
```

## Output

Each input document produces:

```text
<outputRoot>/
  _pipeline-state.json   ← state checklist (Agent reads this to resume)
  <doc-id>/
    final.md             ← clean markdown, the primary deliverable
    source.md            ← raw extracted text (baseline reference)
    artifacts/           ← page screenshots, tiles, strips (visual anchors)
      pages/
        page-NNNN-full.png
        page-NNNN-tile-r*c*.png
        page-NNNN-strip-*.png
```

## Execution Steps

When the skill is invoked, the Agent MUST follow this sequence. **Before any step, read `_pipeline-state.json` to determine current progress.**

### Step 0: Resume Check

1. Read `<outputRoot>/_pipeline-state.json`.
2. If it does not exist → run Step 1 (extraction).
3. If it exists, check `pipeline_stage` and per-file `stage`:
   - `extract_done` + `needs_repair: true` → go to Step 2
   - `repair_pending` → go to Step 3 (resume repair)
   - `repair_done` → go to Step 4
   - `finalized` → already done, report results
4. **Update task `status` from `pending` to `done` as each task completes.**

### Step 1: Run Extraction Pipeline

**When:** no state file exists, or files have `stage: "pending"`.

1. Execute the runner:
   ```
   py -3 markfiledown_runner.py --input-path <path> --output-root <outputRoot> --recurse off
   ```
2. Runner exits → writes `_pipeline-state.json`.
3. Read the state file → go to Step 2.

### Step 2: Determine Repair Needs

**When:** `pipeline_stage` is `extract_done`.

1. Run: `py -3 markfiledown_runner.py --check-repair --output-root <outputRoot>`
2. Read `_pipeline-state.json`. For each file:
   - `stage: "repair_pending"` + `needs_repair: true` → requires repair (Step 3); read the file's `needs-repair.json` for the illustration scope
   - `stage: "extract_done"` + `needs_repair: false` → skip repair, go to Step 4
3. Update each file's extraction task `status` to `"done"`.
4. Write the updated state file.

### Step 3: Agent Illustration Repair (插图级修复，v2)

**When:** any file has `stage: "repair_pending"`.

Repair scope is driven by the structured marker `needs-repair.json` — NOT by scanning `final.md`.
A text-native PDF (no embedded images, e.g. docx-origin specs) carries `needs_repair: false`
and must skip this step entirely (zero vision tokens).

For each file needing repair:

1. **Read** `<output_dir>/needs-repair.json`. If missing or `needs_repair: false` → skip to Step 4.
2. For each entry in `pages[]`, **read only the listed illustration crops** (`illustrations[]`,
   e.g. `artifacts/pages/page-0012-img-01.png`) via multimodal vision;
   use `context_image` (full page) only when a crop alone is ambiguous.
   **Never read full-page screenshots for text-only pages.**
3. **For each illustration**, compare with how it is referenced/described in `final.md`:
   - Is the illustration correctly recognized (content, embedded labels, callout numbers, arrows/flow direction)?
   - Is its description in `final.md` accurate and complete?
   - Are adjacent tables/figures structurally correct?
4. **Repair `final.md` precisely**:
   - Fix only the sections related to wrong or missing illustration descriptions
   - Add `<!-- agent-corrected: <reason> -->` near repaired sections
   - Do NOT rewrite text-only pages; keep page structure and anchors intact
5. **Update state**: mark repair task `status: "done"`, set `stage: "repair_done"`.
6. Write the state file.

A PDF needs repair when it contains embedded illustrations that must be correctly recognized
and described (`reason: "illustration-review"`), or when it is image-only / OCR-heavy
(`reason: "image-only-pdf"`). Text-native documents (docx-origin specs, plain text conversions)
never enter this step.

### Step 4: Quality Verification

**When:** all files have `stage: "repair_done"` or `stage: "extract_done"` (no repair needed).

For each file:
1. `final.md` exists and is non-empty (>50 chars).
2. If visual-heavy, page screenshots are referenced in `final.md`.
3. No `[待补充]` placeholders remain (unless explicitly marked as known gaps).
4. Clean Markdown — no decision headers, engine comparison blocks, or raw JSON dumps.

Mark verification task `status: "done"`, set `stage: "done"`. Write state.

### Step 4.25: ASCII Reconstruction & Cross-Verification (PDF visual-heavy only)

**When:** the file is a PDF and `needs_repair` was `true` (visual/UX document).

This step creates an **independent ASCII reconstruction** from page screenshots, then cross-verifies it against `final.md` to catch gaps, garbled text, and structural errors.

#### 4.25.1 Generate ASCII reconstruction

For each page screenshot in `artifacts/pages/page-NNNN-full.png`:

1. **Read the page screenshot** via multimodal vision.
2. **Independently reconstruct** the page content as Markdown with ASCII art:
   - **UI 界面页** → ASCII box-drawing layout (`┌──┐`, `│`, `─▶`) showing buttons, lists, input fields, progress bars, tabs, DOCK bars, status bars
   - **流程图页** → ASCII flow diagrams (`┌──┐──▶┌──┐`) showing process steps and decision branches
   - **层级/结构页** → ASCII tree or layered boxes (`╔══╗`, `║`) showing hierarchy relationships
   - **表格页** → Markdown tables
   - **纯文本页** → Standard Markdown headings, lists, paragraphs
3. **Write** the reconstruction to `<output_dir>/ascii-reconstruction.md` (one file per document, all pages appended).

#### 4.25.2 Cross-verify against final.md

1. **Read** `ascii-reconstruction.md` and `final.md` side by side.
2. **For each page**, compare:
   - **Section coverage**: Does `final.md` have every section that appears in the screenshot? (count `##` / `###` headers)
   - **Text completeness**: Is any text from the screenshot missing in `final.md`? (especially numbered annotations, footnotes, toast messages)
   - **ASCII diagram presence**: If the page contains a UI mockup or flowchart, does `final.md` include an ASCII representation?
   - **Number-to-label mapping**: If the screenshot has numbered callouts (①②③ or 1·2·3), does `final.md` map each number to its corresponding label and description?
   - **Flow direction**: For process pages, are arrows/steps in the correct direction?
3. **Record findings** in a cross-verification checklist (internal notes or temporary file):
   ```
   Page N: [PASS/FAIL] — issues: <list>
   ```
4. **If issues found**: do targeted repair on `final.md` using the ASCII reconstruction as the ground truth:
   - Add missing sections
   - Fix garbled text (CID codes, mojibake)
   - Insert ASCII diagrams where screenshots show UI/flowcharts
   - Add/fix numbered annotation mappings
5. **Delete** `ascii-reconstruction.md` after verification (it served its purpose as an intermediate artifact).

#### 4.25.3 Update state

Mark this sub-step complete (no state file change needed — it is part of the quality verification phase).

### Step 4.5: Multimodal Quality Gate (PDF only)

**When:** all files have `stage: "done"` or `stage: "extract_done"`, and the file is a PDF.

For each PDF file:

1. **The pipeline writes** `quality-gate-request.json` in the doc directory (automatic, part of Stage 5 in the doc-pre engine).
2. **Agent reads** the request, page screenshots (`artifacts/pages/page-NNNN-full.png`), and `final.md`.
3. **Agent verifies** per the structured checklist:
   - **通用**：完整性（截图文字全覆盖）、阅读顺序、无编造
   - **设置树页**：父子层级嵌套正确，子项未提升为顶级
   - **标注 UI 页**：每个标号都有"标号 → 控件 → 说明"映射
   - **流程页**：流程方向正确，状态迁移链完整
   - **配置矩阵页**：维度识别正确，显隐关系准确
   - **布局页**：空间分区正确，模块归属正确
4. **Agent writes** `quality-gate-report.json` with:
   - `overall_verdict`: `pass` / `fail` / `pass-with-notes`
   - Per-page `checks[]` with `category`, `status` (pass/fail/skip), `detail`
   - `fix_suggestion` for each fail item
5. If `overall_verdict` is `fail` (and repair rounds < 2):
   - Use the `fix_suggestion` fields to do **targeted repair** on `final.md`
   - The pipeline re-runs the quality gate
6. If verdict is `pass` or `pass-with-notes`: mark quality gate task `status: "done"`, proceed to finalize.

### Step 5: Finalize

1. Set `pipeline_stage: "finalized"`.
2. Write the state file.
3. Report summary: total files, per-file status, output root, any remaining issues.

## Completion Standard

1. Every input has a `final.md` in its output folder.
2. `final.md` contains clean Markdown without decision headers or engine comparison.
3. For image-only PDFs and visual-heavy PDFs, page structure is expressed via Markdown tables, lists, and ASCII diagrams.
4. Complex pages are organized by the original PDF spatial structure: page title, UI/screenshot region, numbered callouts, tables, flows, and notes.
5. Important UI labels, toast text, deleted/new/change markers, configuration tables, and numbered annotations are preserved.
6. The document includes an `OCR 与视觉识别对照备注` section when visual repair corrected OCR/read-order issues.
7. **ASCII cross-verification**: every visual page's screenshot has been independently reconstructed as ASCII/Markdown and cross-verified against `final.md`; all missing sections, garbled text, and structural errors have been repaired.
8. The final deliverable is readable without opening raw extraction logs, while page images remain linked as visual anchors.
