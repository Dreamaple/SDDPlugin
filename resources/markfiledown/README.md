# markfiledown-0509

`markfiledown-0509` integrates the two source bundles in this workspace into a single portable skill.

It keeps the original engines vendored under `engines/` and adds one orchestration layer:

1. Run `doc-pre` per file for text-first extraction, block evidence, readback, and integrity reports.
2. Run `efm` per file as a best-effort structured/visual engine for batch-style output, OOXML tables, embedded media, OCR, and visual review.
3. Compare both engine outcomes per document.
4. Promote the stronger `final.md` and `source.md` to the integrated document root.
5. Write `index.md`, `comparison-matrix.md`, `batch-manifest.json`, and `report.html`.

The release unit is the whole `markfiledown-0509/` folder. The original source skill folders are vendored inside this folder under `engines/`, so downstream users do not need to copy sibling folders.

## Usage

```powershell
.\markfiledown-0509\run.ps1 -InputPath ".\docs" -OutputRoot ".\outputs\markfiledown-0509"
```

Explicit files are supported and recommended when the working directory also contains previous outputs:

```powershell
.\markfiledown-0509\run.ps1 `
  -InputFile ".\a.pdf" `
  -InputFile ".\b.docx" `
  -OutputRoot ".\outputs\markfiledown-0509"
```

## Parameters

| Parameter | Default | Notes |
| --- | --- | --- |
| `InputPath` | none | File or directory input. |
| `InputFile` | none | Repeatable explicit file input. |
| `OutputRoot` | required | Integrated output root. |
| `SourceFormat` | `auto` | Optional format filter. |
| `MarkdownStyle` | `technical` | Passed to both engines. |
| `EnableAgentReviewValidation` | `true` | Enables PDF/readback checks where supported. |
| `IncludeAssetLinks` | `true` | Preserves visual/media links. |
| `EnableOcr` | `true` | Enables EFM OCR fallback. |
| `Recurse` | `true` | Directory scan recursion. |
| `MaxEfmPdfSizeMb` | `80` | Large PDFs skip EFM best-effort rendering and use doc-pre. |
| `PythonExe` | auto | Optional Python executable. |

## Output

The integrated output root contains a batch index and a per-document folder. Raw engine outputs remain under each document's `engine-results/` folder for auditability.

`report.html` is the high-level report for stakeholders. `comparison-matrix.md` is the concise engineering matrix.

## Visual-heavy PDF Repair

Some PDFs have an embedded text layer but are still visual documents: UX specs, Figma/Sketch exports, annotated mockups, page-flow diagrams, screenshot-based design reviews, and slide-like canvases. For these files, raw text extraction is not a finished deliverable because the reading order is usually scrambled and the callouts lose their spatial context.

The expected workflow is:

1. Run the normal `markfiledown-0509` pipeline.
2. Check the promoted document folder for `multimodal-correction-request.json` or `.multimodal-repair-request.json`.
3. If a request file exists, the Agent must read it, compare screenshots/assets with `final.md`, repair the Markdown, mark repaired sections with `<!-- agent-corrected: ... -->`, and delete the request file.
4. If dependency gaps prevent the request file from containing page data, the Agent should still perform the same repair manually from available evidence.

Manual fallback for visual-heavy PDFs:

```powershell
# Example only: use any available local renderer.
pdftotext -layout -enc UTF-8 ".\source.pdf" ".\raw_pdftotext.txt"
pdftoppm -png -r 24 ".\source.pdf" ".\assets\page"
pdftoppm -png -r 48 -f 7 -l 9 ".\source.pdf" ".\assets-hi\page"
```

Then reconstruct `final.md` with this contract:

- Use extracted text as the wording baseline.
- Use screenshots as the authority for spatial structure and reading order.
- Keep full-page images as visual anchors.
- Crop or zoom dense regions before reconstructing small text, tables, flows, and numbered callouts.
- Rebuild complex pages by original layout: page title, UI/screenshot area, numbered annotations, configuration tables, state flows, and notes.
- Use Markdown tables for tabular data.
- Use ASCII diagrams for UI mockups, dialogs, state transitions, and flowcharts.
- Preserve deleted/new/change markers, toast text, button labels, configuration rules, and numbered annotations.
- Add an `OCR 与视觉识别对照备注` section when visual repair corrected OCR or read-order issues.

The final `final.md` should be readable on its own. Raw extraction logs and high-resolution crops can remain in side folders for auditability, but they should not replace the reconstructed narrative.

## Workspace Skill Discovery

For a native `.github/skills` entry in a new project, run:

```powershell
.\markfiledown-0509\install-workspace-skill.ps1
```

The installer writes `.github/skills/markfiledown-0509/SKILL.md` in the parent project and stays silent unless `-Verbose` is used. It does not open File Explorer.

## Link Safety

Promoted `final.md` and `source.md` rewrite relative image and asset links back to their real `engine-results/...` locations. Each per-document output also writes `link-check-report.json`; a release-quality run should have `broken_link_count` equal to `0`.

## Quiet Execution

The bundle does not call `explorer.exe`, `Start-Process`, `Invoke-Item`, or `os.startfile`. It only prints paths and writes reports. If a host opens folders after execution, that behavior is outside this bundle and can be replaced by opening `report.html` explicitly.
