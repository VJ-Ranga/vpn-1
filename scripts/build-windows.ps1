param([switch]$SkipPythonBuild)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
Set-Location $root
$python = Join-Path $root 'backend\.venv\Scripts\python.exe'
if (-not (Test-Path $python)) { throw 'Create backend/.venv and install backend dependencies first.' }
$release = Join-Path $root 'release'
$vendor = Join-Path $release 'vendor'
New-Item -ItemType Directory -Force $vendor | Out-Null

function Download([string]$Url, [string]$Destination) {
    if (-not (Test-Path $Destination)) {
        & curl.exe --location --fail --retry 3 --connect-timeout 20 --max-time 300 --output $Destination $Url
        if ($LASTEXITCODE -ne 0) { throw "Download failed: $Url" }
    }
}

# Only official, freshly downloaded profiles are bundled. Never copy credentials,
# the working checkout's profiles, settings, logs or helper tokens into a build.
Download 'https://vpn.ncapi.io/groupedServerList.zip' (Join-Path $vendor 'profiles.zip')
Expand-Archive -Path (Join-Path $vendor 'profiles.zip') -DestinationPath (Join-Path $release 'profiles') -Force
if (@(Get-ChildItem (Join-Path $release 'profiles') -Recurse -Filter '*.ovpn').Count -lt 2) { throw 'Official profiles missing.' }
Get-ChildItem (Join-Path $release 'profiles') -Recurse -Filter '*.ovpn' | ForEach-Object {
    if ((Get-Content -Raw $_.FullName) -match '(?im)^\s*<(?:key|cert|auth-user-pass)>') { throw 'Refusing to bundle private profile material.' }
}
Download 'https://swupdate.openvpn.org/community/releases/OpenVPN-2.7.9-I001-amd64.msi' (Join-Path $vendor 'OpenVPN.msi')
$signature = Get-AuthenticodeSignature (Join-Path $vendor 'OpenVPN.msi')
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=OpenVPN (Inc\.|Technologies)') {
    throw 'The official OpenVPN prerequisite signature could not be verified.'
}

if (-not $SkipPythonBuild) {
    & $python -m PyInstaller --noconfirm --clean --onedir --name NorthstarBackend `
        --distpath release/python --workpath release/work/backend --specpath release/specs `
        --paths backend --hidden-import app.main --hidden-import keyring.backends.Windows `
        --collect-all uvicorn backend/windows_entry.py
    if ($LASTEXITCODE -ne 0) { throw 'Backend freeze failed.' }
    & $python -m PyInstaller --noconfirm --clean --onedir --name NorthstarHelper `
        --distpath release/python --workpath release/work/helper --specpath release/specs `
        --paths system --hidden-import win32timezone system/windows_service.py
    if ($LASTEXITCODE -ne 0) { throw 'Helper freeze failed.' }
}
npm run icons:windows
if ($LASTEXITCODE -ne 0) { throw 'Windows icon generation failed.' }
npm --prefix frontend run build
if ($LASTEXITCODE -ne 0) { throw 'Frontend build failed.' }
$env:CSC_IDENTITY_AUTO_DISCOVERY = 'false'
& (Join-Path $root 'node_modules\.bin\electron-builder.cmd') --win nsis --x64 --publish never
if ($LASTEXITCODE -ne 0) { throw 'Installer build failed.' }
Get-ChildItem (Join-Path $release '*Setup*.exe') | ForEach-Object { Get-FileHash $_.FullName -Algorithm SHA256 }
