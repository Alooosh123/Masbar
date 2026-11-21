$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location "$root\web"
if (-not (Test-Path "node_modules")) {
    npm.cmd install
}
npm.cmd run dev
