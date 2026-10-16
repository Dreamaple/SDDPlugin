# Multimodal Repair Post-Processor
# Called by run.ps1 after Python pipeline completes.
# Detects multimodal-repair-brief.json and performs Agent-based format repair.

param(
    [Parameter(Mandatory = $true)]
    [string]$BriefPath,

    [Parameter(Mandatory = $true)]
    [string]$OutputRoot
)

$ErrorActionPreference = 'Stop'

$briefPath = [System.IO.Path]::GetFullPath($BriefPath)
$outputRoot = [System.IO.Path]::GetFullPath($OutputRoot)

if (-not (Test-Path $briefPath)) {
    Write-Output "[multimodal-repair] No brief found at $briefPath, skipping."
    exit 0
}

$brief = Get-Content $briefPath -Raw | ConvertFrom-Json

Write-Output "[multimodal-repair] Detected image-only PDF: $($brief.pdf_name)"
Write-Output "[multimodal-repair] Pages: $($brief.page_count)"
Write-Output "[multimodal-repair] Source MD: $($brief.source_md_path)"
Write-Output "[multimodal-repair] Page images: $($brief.page_images.Count) screenshots"
Write-Output "[multimodal-repair] Starting Agent-based multimodal format repair..."

# The multimodal repair is performed by the Claude Code Agent.
# This script signals the Agent to take over by writing a repair request file
# that the Agent reads and acts upon.
$requestPath = [System.IO.Path]::Combine($outputRoot, '.multimodal-repair-request.json')

$request = @{
    status = 'pending'
    source_md = $brief.source_md_path
    pages_dir = $brief.pages_dir
    page_images = @($brief.page_images | ForEach-Object {
        @{ page_number = $_.page_number; path = $_.path }
    })
    repair_prompt = $brief.repair_prompt
    output_md = [System.IO.Path]::Combine($outputRoot, 'final.md')
}

$request | ConvertTo-Json -Depth 5 | Out-File -FilePath $requestPath -Encoding utf8

Write-Output "[multimodal-repair] Repair request written to $requestPath"
Write-Output "[multimodal-repair] Awaiting Agent to process multimodal repair..."
