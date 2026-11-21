$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8010/health" -TimeoutSec 3
} catch {
    Write-Host "Backend is not running on 8010. Start it with: .\scripts\dev-backend.ps1" -ForegroundColor Red
    exit 1
}

Write-Host "Backend online: $($health.status) | components: $($health.components) | equipment: $($health.equipment) | vision: $($health.vision_provider)" -ForegroundColor Green
& "$root\.venv\Scripts\python.exe" "$root\scripts\smoke_api.py"
exit $LASTEXITCODE
