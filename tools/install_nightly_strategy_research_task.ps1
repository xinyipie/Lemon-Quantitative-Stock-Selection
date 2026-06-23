param(
    [string]$TaskName = "Stock Nightly Strategy Research",
    [string]$StartTime = "20:00"
)

$ErrorActionPreference = "Stop"

$ProjectDir = Split-Path -Parent $PSScriptRoot
$ScriptPath = Join-Path $ProjectDir "tools\run_nightly_strategy_research.ps1"

Write-Host "========================================"
Write-Host "  Install Stock Nightly Research Task"
Write-Host "========================================"
Write-Host "TaskName:  $TaskName"
Write-Host "StartTime: $StartTime"
Write-Host "Script:    $ScriptPath"
Write-Host ""

if (-not (Test-Path -LiteralPath $ScriptPath)) {
    Write-Host "[ERROR] Script not found: $ScriptPath"
    exit 1
}

$action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$ScriptPath`""

$trigger = New-ScheduledTaskTrigger -Daily -At $StartTime
$settings = New-ScheduledTaskSettingsSet `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries `
    -StartWhenAvailable `
    -WakeToRun `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12)

$CurrentUser = [System.Security.Principal.WindowsIdentity]::GetCurrent().Name
$principal = New-ScheduledTaskPrincipal `
    -UserId $CurrentUser `
    -LogonType Interactive `
    -RunLevel Limited

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Description "Run stock strategy research diagnostics every night." `
    -Force | Out-Null

Write-Host "Installed scheduled task successfully."
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Get-ScheduledTask -TaskName `"$TaskName`""
Write-Host "  Start-ScheduledTask -TaskName `"$TaskName`""
Write-Host "  Unregister-ScheduledTask -TaskName `"$TaskName`" -Confirm:`$false"
