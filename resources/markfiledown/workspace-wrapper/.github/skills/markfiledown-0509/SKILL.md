---
name: markfiledown-0509
description: "Workspace wrapper for the portable markfiledown-0509 bundle. Convert PDF, DOCX, PPTX, XLSX, or mixed folders to Markdown with text-first evidence, Mermaid/diagram reconstruction, presentation-page preservation, region-first visual review, batch fallback, asset-link validation, and HTML reporting. Use this skill whenever converting documents to markdown within a workspace context. Triggers include: 文档转markdown, PDF转换, convert documents, /markfiledown.pipeline, batch document processing. Do NOT use when the standalone markfiledown-0509 skill is already loaded at project root."
---

# MarkFileDown 0509 Workspace Wrapper

This wrapper exposes the portable `markfiledown-0509/` bundle as a native workspace skill.

Run the bundle from the project root:

```powershell
.\markfiledown-0509\run.ps1 -InputPath ".\docs" -OutputRoot ".\outputs\markfiledown-0509"
```

Contract highlights:

1. Text extraction is the main source for body content.
2. Screenshots, tiles, and regions are evidence for structure, diagrams, flowcharts, callouts, and reading order.
3. Stable macro diagrams may produce text backbone plus Mermaid reconstruction plus visual anchors.
4. Demo pages preserve page state, action clues, original note text, and visual anchors.
5. Promoted Markdown outputs must pass `link-check-report.json` with zero broken links.
6. The runner is quiet and does not open File Explorer or browser windows.
