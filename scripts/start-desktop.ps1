$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if ($principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Run the desktop from a normal (non-elevated) PowerShell window."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$env:VPN_PROFILE_ROOT = $root

$tokenFile = Join-Path $env:LOCALAPPDATA "northstar-vpn/helper.token"
if ([string]::IsNullOrWhiteSpace($env:VPN_WINDOWS_HELPER_TOKEN) -and (Test-Path $tokenFile)) {
    $env:VPN_WINDOWS_HELPER_TOKEN = (Get-Content -Raw $tokenFile).Trim()
}
if ([string]::IsNullOrWhiteSpace($env:VPN_WINDOWS_HELPER_TOKEN)) {
    Write-Warning "No helper token found. Start scripts/start-windows-helper.ps1 from an elevated window first."
}

if (Test-Path (Join-Path $root "backend/.venv/Scripts/python.exe")) {
    $env:VPN_PYTHON = Join-Path $root "backend/.venv/Scripts/python.exe"
}
if (-not (Test-Path (Join-Path $root "frontend/dist/index.html"))) {
    npm --prefix $root run build
}
Remove-Item Env:ELECTRON_RUN_AS_NODE -ErrorAction SilentlyContinue
& (Join-Path $root "node_modules/.bin/electron.cmd") $root @args
