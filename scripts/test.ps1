$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\backend"
& "$root\.venv\Scripts\python.exe" -m pytest -q
