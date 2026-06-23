$ErrorActionPreference = "Continue"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$Until = if ($env:NIGHTLY_RESEARCH_UNTIL) { $env:NIGHTLY_RESEARCH_UNTIL } else { "08:00" }
$LogDir = Join-Path $ProjectDir "reports\research\nightly\logs"
$Stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$LogFile = Join-Path $LogDir "nightly_strategy_research_$Stamp.log"

function Write-Log {
    param([string]$Message)
    $line = "$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss') $Message"
    Write-Host $line
    Add-Content -LiteralPath $LogFile -Encoding UTF8 -Value $line
}

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

Write-Log "=== Stock nightly strategy research started ==="
Write-Log "ProjectDir=$ProjectDir"
Write-Log "Until=$Until"
Write-Log "LogFile=$LogFile"

if (-not (Test-Path -LiteralPath $ProjectDir)) {
    Write-Log "[ERROR] Project directory does not exist."
    exit 2
}

Set-Location -LiteralPath $ProjectDir

$branch = (& git branch --show-current 2>&1)
Write-Log "CurrentBranch=$branch"
if ($LASTEXITCODE -ne 0) {
    Write-Log "[WARN] Cannot read git branch. Continue and let runner report branch status."
} elseif ($branch -ne "codex/strategy-research") {
    Write-Log "Switching to codex/strategy-research ..."
    (& git switch codex/strategy-research 2>&1) | ForEach-Object { Write-Log $_ }
}

Write-Log "Pulling latest research branch if possible ..."
(& git pull --ff-only 2>&1) | ForEach-Object { Write-Log $_ }
if ($LASTEXITCODE -ne 0) {
    Write-Log "[WARN] git pull failed. Continue with local files."
}

Write-Log "Running nightly strategy runner ..."
(& python research\nightly_strategy_runner.py --until $Until 2>&1) | ForEach-Object { Write-Log $_ }
$exitCode = $LASTEXITCODE

Write-Log "RunnerExitCode=$exitCode"
Write-Log "=== Stock nightly strategy research finished ==="
exit $exitCode
