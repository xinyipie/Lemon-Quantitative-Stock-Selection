$ErrorActionPreference = "Stop"

$ProjectDir = "E:\代码项目\stock"
$HostName = "127.0.0.1"
$Port = 8000

Write-Host "========================================"
Write-Host "  Stock Web Service Restart"
Write-Host "========================================"
Write-Host "Project: $ProjectDir"
Write-Host "URL:     http://$HostName`:$Port"
Write-Host ""

if (-not (Test-Path -LiteralPath $ProjectDir)) {
    Write-Host "[ERROR] Cannot enter project directory."
    Write-Host "Please check ProjectDir in this script."
    Read-Host "Press Enter to exit"
    exit 1
}

Set-Location -LiteralPath $ProjectDir

Write-Host "[1/2] Stopping old service on port $Port ..."
$ids = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue |
    Select-Object -ExpandProperty OwningProcess -Unique

if (-not $ids) {
    Write-Host "No existing service found."
} else {
    foreach ($procId in $ids) {
        try {
            Stop-Process -Id $procId -Force -ErrorAction Stop
            Write-Host "Stopped PID $procId"
        } catch {
            Write-Host "Failed to stop PID $procId`: $($_.Exception.Message)"
        }
    }
}

Write-Host ""
Write-Host "[2/2] Starting Web service ..."
Write-Host "Open: http://$HostName`:$Port"
Write-Host "Close this window to stop the service."
Write-Host ""

python -m uvicorn web_app.app:app --host $HostName --port $Port --reload

$exitCode = $LASTEXITCODE
Write-Host ""
Write-Host "Service exited with code $exitCode."
if ($exitCode -ne 0) {
    Write-Host "If this is unexpected, send the error text above to Codex."
}
Read-Host "Press Enter to exit"
exit $exitCode
