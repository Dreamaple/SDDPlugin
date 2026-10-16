param(
    [string]$InputPdf = '',

    [string]$InputPath = '',

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [ValidateSet('auto', 'pdf', 'doc', 'docx', 'ppt', 'pptx', 'xls', 'xlsx')]
    [string]$SourceFormat = 'auto',

    [ValidateSet('technical', 'narrative', 'audit-friendly')]
    [string]$MarkdownStyle = 'technical',

    [bool]$EnablePdfAgentValidation = $true,
    [bool]$IncludeAssetLinks = $true,
    [bool]$EnableOcr = $true,
    [bool]$Recurse = $true,
    [bool]$AutoInstallDeps = $true,
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'

function Resolve-PythonCommand {
    param([string]$PreferredPython)

    $scriptDir = if ($PSScriptRoot) {
        $PSScriptRoot
    }
    elseif ($PSCommandPath) {
        Split-Path -Parent $PSCommandPath
    }
    else {
        (Get-Location).Path
    }

    if ($PreferredPython -and (Test-Path $PreferredPython)) {
        return (Resolve-Path $PreferredPython).Path
    }

    $candidatePaths = @(
        (Join-Path (Get-Location) '.venv\Scripts\python.exe'),
        (Join-Path (Split-Path $scriptDir -Parent) '.venv\Scripts\python.exe'),
        (Join-Path $scriptDir '.venv\Scripts\python.exe')
    )

    foreach ($candidate in $candidatePaths) {
        if (Test-Path $candidate) {
            return (Resolve-Path $candidate).Path
        }
    }

    $pythonCommand = Get-Command python -ErrorAction SilentlyContinue
    if ($pythonCommand) {
        return $pythonCommand.Source
    }

    $pyCommand = Get-Command py -ErrorAction SilentlyContinue
    if ($pyCommand) {
        return "$($pyCommand.Source) -3"
    }

    throw 'No Python interpreter was found. Pass -PythonExe or provide python/py in PATH.'
}

function Invoke-PythonCommand {
    param(
        [string]$CommandSpec,
        [string[]]$Arguments
    )

    if ($CommandSpec.Contains(' -3')) {
        $parts = $CommandSpec.Split(' ', 2)
        & $parts[0] $parts[1] @Arguments
    }
    else {
        & $CommandSpec @Arguments
    }

    if ($LASTEXITCODE -ne 0) {
        throw "Python command failed with exit code $LASTEXITCODE"
    }
}

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonCmd = Resolve-PythonCommand -PreferredPython $PythonExe
$requirementsPath = Join-Path $scriptDir 'requirements.txt'
$runnerPath = Join-Path $scriptDir 'bundle_runner.py'

if (-not $InputPath -and $InputPdf) {
    $InputPath = $InputPdf
}

if (-not $InputPath) {
    throw 'Provide -InputPath (file or folder). -InputPdf is kept only for backward compatibility.'
}

if (-not (Test-Path $InputPath)) {
    throw "Input path not found: $InputPath"
}

if ($AutoInstallDeps) {
    $checkCode = "import importlib.util, sys; mods=['pdfplumber','pypdfium2','pypdf','PIL','rapidocr_onnxruntime','openpyxl','win32com']; sys.exit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)"
    try {
        Invoke-PythonCommand -CommandSpec $pythonCmd -Arguments @('-c', $checkCode)
    }
    catch {
        Invoke-PythonCommand -CommandSpec $pythonCmd -Arguments @('-m', 'pip', 'install', '-r', $requirementsPath)
    }
}

$pdfAgentMode = if ($EnablePdfAgentValidation) { 'on' } else { 'off' }
$assetLinksMode = if ($IncludeAssetLinks) { 'on' } else { 'off' }
$ocrMode = if ($EnableOcr) { 'on' } else { 'off' }
$recurseMode = if ($Recurse) { 'on' } else { 'off' }

Invoke-PythonCommand -CommandSpec $pythonCmd -Arguments @(
    $runnerPath,
    '--input-path', $InputPath,
    '--output-root', $OutputRoot,
    '--source-format', $SourceFormat,
    '--markdown-style', $MarkdownStyle,
    '--pdf-agent-validation', $pdfAgentMode,
    '--asset-links', $assetLinksMode,
    '--ocr', $ocrMode,
    '--recurse', $recurseMode
)
