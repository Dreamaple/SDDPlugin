param(
    [string]$InputPath = '',
    [string[]]$InputFile = @(),
    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,
    [switch]$Recurse,
    [switch]$AutoDiscover
)

$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path

# ── Filename sanitizer: fix Unicode chars that break terminal encoding ──
# E.g. U+2024 ONE DOT LEADER (․) → normal dot (.), invisible chars → _
function Sanitize-FileName {
    param([string]$FilePath)
    $name = [System.IO.Path]::GetFileName($FilePath)
    $dir  = [System.IO.Path]::GetDirectoryName($FilePath)
    # Replace problematic Unicode dots/dashes
    $name = $name -replace '[․‥…‐‑‒–—]', '.'
    # Remove zero-width / invisible chars
    $name = $name -replace '[​-‏﻿]', ''
    # Replace remaining non-ASCII punctuation with _
    $name = $name -replace '[^\p{L}\p{N}._\-()]', '_'
    $name = $name -replace '_+', '_'
    $name = $name.TrimStart('_.-')
    if (-not $name) { $name = 'document' }
    $sanitized = [System.IO.Path]::Combine($dir, $name)
    if ($sanitized -ne $FilePath -and (Test-Path -LiteralPath $FilePath -PathType Leaf)) {
        $dst = [System.IO.Path]::Combine($dir, "___sanitize___$name")
        Copy-Item -LiteralPath $FilePath -Destination $dst -Force
        return $dst
    }
    return $FilePath
}

# ── Auto-discover: when InputPath is a directory, find supported files ──
$supportedExts = @('.pdf','.doc','.docx','.ppt','.pptx','.xls','.xlsx','.csv',
    '.png','.jpg','.jpeg','.bmp','.gif','.tif','.tiff','.webp','.svg',
    '.html','.htm','.md','.mdx','.markdown','.txt','.rst','.log',
    '.tsv','.json','.yaml','.yml','.xml','.toml','.ini',
    '.py','.java','.kt','.go','.rs','.c','.cpp','.h','.hpp','.cs',
    '.rb','.php','.sh','.bat','.ps1','.sql','.js','.ts','.tsx',
    '.jsx','.vue','.svelte','.css')

if ($AutoDiscover.IsPresent -and (Test-Path -LiteralPath $InputPath -PathType Container)) {
    $discoverPath = $InputPath
    $doRecurse = $Recurse.IsPresent
    $allFiles = Get-ChildItem -LiteralPath $discoverPath -Recurse:$doRecurse -File -ErrorAction SilentlyContinue
    $InputFile = @($allFiles | Where-Object { $supportedExts -contains $_.Extension.ToLower() } | ForEach-Object { $_.FullName })
    $InputPath = ''
    Write-Host "[auto-discover] Found $($InputFile.Count) supported file(s) in $discoverPath" -ForegroundColor Cyan
}

if (-not $InputPath -and (-not $InputFile -or $InputFile.Count -eq 0)) {
    throw 'Provide -InputPath or at least one -InputFile.'
}

# Resolve Python
$pythonCmd = $null
$candidates = @(
    (Join-Path $scriptDir '.venv\Scripts\python.exe'),
    (Join-Path (Split-Path $scriptDir -Parent) '.venv\Scripts\python.exe'),
    'python',
    'py -3'
)
foreach ($c in $candidates) {
    if ($c -match '^py ') {
        try { $null = & py -3 --version 2>&1; $pythonCmd = $c; break } catch {}
    }
    elseif (Get-Command $c -ErrorAction SilentlyContinue) {
        $pythonCmd = (Get-Command $c).Source; break
    }
    elseif (Test-Path $c) {
        $pythonCmd = (Resolve-Path $c).Path; break
    }
}
if (-not $pythonCmd) {
    throw 'No Python found. Install deps: pip install -r requirements.txt'
}

$runnerArgs = @(
    (Join-Path $scriptDir 'markfiledown_runner.py'),
    '--output-root', $OutputRoot,
    '--recurse', $(if ($Recurse.IsPresent) { 'on' } else { 'off' })
)

if ($InputPath) {
    # Sanitize the input path itself (for directory paths with problematic chars)
    $resolved = (Resolve-Path $InputPath).Path
    if (Test-Path -LiteralPath $resolved -PathType Leaf) {
        $InputPath = Sanitize-FileName $resolved
    }
    $runnerArgs += @('--input-path', $InputPath)
}

$sanitizedFiles = @()
foreach ($item in $InputFile) {
    # Try LiteralPath first (avoids encoding interpretation), fall back to normal
    try {
        $resolved = (Resolve-Path -LiteralPath $item).Path
    } catch {
        $resolved = (Resolve-Path $item).Path
    }
    if (Test-Path -LiteralPath $resolved -PathType Leaf) {
        $sanitized = Sanitize-FileName $resolved
        $sanitizedFiles += $sanitized
    } else {
        # File not found — try glob discovery in the same directory
        $dir = [System.IO.Path]::GetDirectoryName($resolved)
        $pattern = '*' + [System.IO.Path]::GetExtension($resolved)
        if (Test-Path -LiteralPath $dir) {
            $matches = Get-ChildItem -LiteralPath $dir -Filter $pattern -File -ErrorAction SilentlyContinue
            if ($matches.Count -gt 0) {
                $sanitized = Sanitize-FileName $matches[0].FullName
                $sanitizedFiles += $sanitized
                Write-Host "  [auto-recover] Resolved via glob: $($matches[0].Name) -> $($sanitized)" -ForegroundColor DarkGray
            }
        }
    }
}
if ($sanitizedFiles.Count -gt 0) {
    foreach ($f in $sanitizedFiles) { $runnerArgs += @('--input-file', $f) }
}

Write-Host "[markfiledown] Running pipeline..." -ForegroundColor Cyan
if ($pythonCmd -match '^py ') {
    $parts = $pythonCmd.Split(' ', 2)
    & $parts[0] $parts[1] @runnerArgs
} else {
    & $pythonCmd @runnerArgs
}

# ── Cleanup sanitized temp copies ─
foreach ($f in $sanitizedFiles) {
    if ($f -like '*___sanitize___*' -and (Test-Path -LiteralPath $f -PathType Leaf)) {
        Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue
    }
}
# Clean up .sanitize-tmp dir created by Python runner
$sanitizeTmp = [System.IO.Path]::Combine($OutputRoot, '.sanitize-tmp')
if (Test-Path -LiteralPath $sanitizeTmp) {
    Remove-Item -LiteralPath $sanitizeTmp -Recurse -Force -ErrorAction SilentlyContinue
}

if ($LASTEXITCODE -ne 0) {
    throw "Runner failed with exit code $LASTEXITCODE"
}
