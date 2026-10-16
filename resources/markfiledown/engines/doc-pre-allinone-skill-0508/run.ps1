param(
    [Parameter(Mandatory = $true)]
    [Alias('InputPdf')]
    [string]$InputFile,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot,

    [string]$SourceFormat = 'auto',

    [ValidateSet('technical', 'narrative', 'audit-friendly')]
    [string]$MarkdownStyle = 'technical',

    [Alias('EnablePdfAgentValidation')]
    [bool]$EnableAgentReviewValidation = $true,
    [bool]$IncludeAssetLinks = $true,

    [ValidateSet('builtin', 'external-command', 'disabled')]
    [string]$AgentExecMode = 'builtin',

    [string]$AgentCommand = '',
    [bool]$UsePlugins = $false,
    [bool]$AutoInstallDeps = $true,
    [string]$PythonExe = ''
)

$ErrorActionPreference = 'Stop'

$scriptDir = $PSScriptRoot
if (-not $scriptDir -and $PSCommandPath) {
    $scriptDir = Split-Path -Parent $PSCommandPath
}

function Resolve-PythonCommand {
    param([string]$PreferredPython)

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

$pythonCmd = Resolve-PythonCommand -PreferredPython $PythonExe
$requirementsPath = Join-Path $scriptDir 'requirements.txt'
$runnerPath = Join-Path $scriptDir 'pipeline_runner.py'

if (-not (Test-Path $InputFile)) {
    throw "Input file not found: $InputFile"
}

if ($AutoInstallDeps) {
    $checkCode = "import importlib.util, sys; mods=['pdfplumber','pypdfium2','pypdf','PIL','markitdown','mammoth','pptx','pandas','openpyxl','xlrd','lxml']; sys.exit(0 if all(importlib.util.find_spec(m) for m in mods) else 1)"
    try {
        Invoke-PythonCommand -CommandSpec $pythonCmd -Arguments @('-c', $checkCode)
    }
    catch {
        Invoke-PythonCommand -CommandSpec $pythonCmd -Arguments @('-m', 'pip', 'install', '-r', $requirementsPath)
    }
}

$agentReviewMode = if ($EnableAgentReviewValidation) { 'on' } else { 'off' }
$assetLinksMode = if ($IncludeAssetLinks) { 'on' } else { 'off' }
$pluginMode = if ($UsePlugins) { 'on' } else { 'off' }

Invoke-PythonCommand -CommandSpec $pythonCmd -Arguments @(
    $runnerPath,
    '--input-file', $InputFile,
    '--output-root', $OutputRoot,
    '--source-format', $SourceFormat,
    '--markdown-style', $MarkdownStyle,
    '--agent-review-validation', $agentReviewMode,
    '--asset-links', $assetLinksMode,
    '--agent-exec-mode', $AgentExecMode,
    '--agent-command', $AgentCommand,
    '--use-plugins', $pluginMode
)