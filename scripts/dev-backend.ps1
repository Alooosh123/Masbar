param([int]$Port = 0)

$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot

if ($Port -le 0) {
    $Port = 8010
    $envFile = Join-Path $root ".env"
    if (Test-Path $envFile) {
        $line = Get-Content $envFile | Where-Object { $_ -match '^\s*API_PORT\s*=' } | Select-Object -First 1
        if ($line) {
            $value = ($line -split '=', 2)[1].Trim()
            $parsed = 0
            if ([int]::TryParse($value, [ref]$parsed) -and $parsed -gt 0) { $Port = $parsed }
        }
    }
}

Set-Location "$root\backend"
& "$root\.venv\Scripts\python.exe" -m uvicorn app.main:app --reload --host 0.0.0.0 --port $Port
