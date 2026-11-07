param(
    [string]$ProfileRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path,
    [int]$Port = 8799,
    [string]$Token = $env:VPN_WINDOWS_HELPER_TOKEN
)

$ErrorActionPreference = "Stop"
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
$principal = New-Object Security.Principal.WindowsPrincipal($identity)
if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw "Start the helper from an elevated PowerShell window. The desktop must remain unprivileged."
}

$root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$python = Join-Path $root "backend/.venv/Scripts/python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$openvpn = "C:\Program Files\OpenVPN\bin\openvpn.exe"
if (-not (Test-Path $openvpn)) {
    throw "OpenVPN was not found at $openvpn. Install OpenVPN Community first."
}

$tokenDir = Join-Path $env:LOCALAPPDATA "northstar-vpn"
$tokenFile = Join-Path $tokenDir "helper.token"
New-Item -ItemType Directory -Force -Path $tokenDir | Out-Null

if ([string]::IsNullOrWhiteSpace($Token)) {
    if ((Test-Path $tokenFile) -and ((Get-Content -Raw $tokenFile).Trim().Length -ge 32)) {
        $Token = (Get-Content -Raw $tokenFile).Trim()
    } else {
        $Token = (& $python -c "import secrets; print(secrets.token_urlsafe(48))").Trim()
        Set-Content -Path $tokenFile -Value $Token -NoNewline -Encoding ascii
        $sid = $identity.User.Value
        & icacls.exe $tokenFile /inheritance:r /grant:r "*${sid}:(R)" "*S-1-5-18:(F)" "*S-1-5-32-544:(F)" | Out-Null
    }
}

if ($Token.Length -lt 32 -or $Token -eq "northstar-dev-token") {
    throw "The helper token is too weak. Remove $tokenFile and rerun, or set a token of at least 32 characters."
}

$env:VPN_PROFILE_ROOT = $ProfileRoot
$env:VPN_WINDOWS_HELPER_PORT = "$Port"
$env:VPN_WINDOWS_HELPER_TOKEN = $Token

Write-Host "Starting Northstar helper on 127.0.0.1:$Port"
Write-Host "OpenVPN: $openvpn"
Write-Host "Profile root: $ProfileRoot"
Write-Host "Token file: $tokenFile"

& $python (Join-Path $root "system/windows_helper.py") --host 127.0.0.1 --port $Port --token $Token --profile-root $ProfileRoot
