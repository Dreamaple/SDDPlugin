param(
    [string]$ProjectRoot = '',
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

$bundleDir = $PSScriptRoot
if (-not $ProjectRoot) {
    $ProjectRoot = Split-Path -Parent $bundleDir
}

$resolvedProjectRoot = (Resolve-Path $ProjectRoot).Path
$targetDir = Join-Path $resolvedProjectRoot '.github\skills\markfiledown-0509'
$targetPath = Join-Path $targetDir 'SKILL.md'

if ((Test-Path $targetPath) -and (-not $Force)) {
    throw "Workspace skill wrapper already exists: $targetPath. Use -Force to overwrite."
}

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null

$content = @'
---
name: markfiledown-0509
description: "Use when converting PDF, DOCX, PPTX, XLSX, or mixed folders to Markdown with text-first evidence, Mermaid/diagram/flowchart reconstruction, 演示页原文说明 preservation, region-first visual review, batch fallback, asset-link validation, and HTML reporting."
---

# MarkFileDown 0509 Workspace Wrapper

Use the portable bundle at `markfiledown-0509/`.

Terminal fallback:

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
'@

Set-Content -LiteralPath $targetPath -Value $content -Encoding UTF8
Write-Host "Workspace skill wrapper installed: $targetPath"
