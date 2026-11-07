param([ValidateSet('Install','Uninstall')][string]$Action = 'Install')
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$name = 'NorthstarVPNHelper'
$data = Join-Path $env:ProgramData 'NorthstarVPN'
$serviceExe = Join-Path $root 'helper\NorthstarHelper.exe'
$sc = Join-Path $env:SystemRoot 'System32\sc.exe'
$identity = [Security.Principal.WindowsIdentity]::GetCurrent()
if (-not ([Security.Principal.WindowsPrincipal]$identity).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
    throw 'Administrator authorization is required for service setup.'
}

function Invoke-Sc([string[]]$Arguments) {
    & $sc @Arguments | Out-Null
    if ($LASTEXITCODE -ne 0) { throw "Service setup failed: $($Arguments[0])" }
}

$existing = Get-Service -Name $name -ErrorAction SilentlyContinue
if ($existing) {
    if ($existing.Status -ne 'Stopped') { Stop-Service $name; $existing.WaitForStatus('Stopped', [TimeSpan]::FromSeconds(60)) }
    if ($Action -eq 'Uninstall') { Invoke-Sc -Arguments @('delete', $name) }
}

if ($Action -eq 'Uninstall') {
    # Preserve user credentials/preferences; do not uninstall shared OpenVPN.
    & (Join-Path $PSScriptRoot 'windows-ipv6-guard.ps1') -Action Disable | Out-Null
    exit 0
}

if (-not (Test-Path $serviceExe)) { throw 'Bundled helper is missing.' }
if (Get-NetTCPConnection -State Listen -LocalPort 8799 -ErrorAction SilentlyContinue) {
    throw 'Port 8799 is already used. Disconnect VPN and close the development helper before installing.'
}

# Refuse installation under a user-writable directory: privileged executable,
# scripts, Python DLLs and profiles must all have admin-owned ACLs.
$installDir = Split-Path $root -Parent
if (-not $installDir.StartsWith($env:ProgramFiles + '\', [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Northstar must be installed below Program Files.'
}
function Protect-AppTree([string]$Directory) {
    $acl = New-Object Security.AccessControl.DirectorySecurity
    $acl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;OICI;FA;;;SY)(A;OICI;FA;;;BA)(A;OICI;GRGX;;;BU)')
    Set-Acl -LiteralPath $Directory -AclObject $acl
    foreach ($item in Get-ChildItem -LiteralPath $Directory -Force) {
        if ($item.Attributes -band [IO.FileAttributes]::ReparsePoint) { throw 'Reparse points are not permitted in installed application files.' }
        if ($item.PSIsContainer) { Protect-AppTree $item.FullName } else {
            $fileAcl = New-Object Security.AccessControl.FileSecurity
            $fileAcl.SetSecurityDescriptorSddlForm('O:BAG:BAD:P(A;;FA;;;SY)(A;;FA;;;BA)(A;;GRGX;;;BU)')
            Set-Acl -LiteralPath $item.FullName -AclObject $fileAcl
        }
    }
}
Protect-AppTree $installDir

$openvpn = Join-Path $env:ProgramFiles 'OpenVPN\bin\openvpn.exe'
if (-not (Test-Path $openvpn)) {
    $msi = Join-Path $root 'vendor\OpenVPN.msi'
    $signature = Get-AuthenticodeSignature $msi
    if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=OpenVPN (Inc\.|Technologies)') {
        throw 'OpenVPN installer signature is invalid.'
    }
    $p = Start-Process -FilePath (Join-Path $env:SystemRoot 'System32\msiexec.exe') -ArgumentList @('/i', "`"$msi`"", '/qn', '/norestart') -Wait -PassThru
    if ($p.ExitCode -notin @(0,3010)) { throw 'Official OpenVPN prerequisite installation failed.' }
}
$signature = Get-AuthenticodeSignature $openvpn
if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'O=OpenVPN (Inc\.|Technologies)') {
    throw 'A trusted OpenVPN installation is required.'
}

# The installing account alone can read the bearer token; other normal users
# are not enrolled automatically. This is a personal-use installer.
$sid = $identity.User.Value
$tokenFile = Join-Path $data 'helper.token'
foreach ($path in @($data, $tokenFile)) {
    if (Test-Path -LiteralPath $path) {
        if ((Get-Item -LiteralPath $path -Force).Attributes -band [IO.FileAttributes]::ReparsePoint) {
            throw 'Refusing a reparse point in privileged service data.'
        }
        $acl = Get-Acl -LiteralPath $path
        $owner = $acl.GetOwner([Security.Principal.SecurityIdentifier]).Value
        if ($owner -notin @('S-1-5-18','S-1-5-32-544',$sid)) {
            throw 'An untrusted account owns existing Northstar service data. Resolve this before installing.'
        }
        $write = [Security.AccessControl.FileSystemRights]'Write,Delete,DeleteSubdirectoriesAndFiles,ChangePermissions,TakeOwnership'
        foreach ($rule in $acl.GetAccessRules($true, $true, [Security.Principal.SecurityIdentifier])) {
            if ($rule.AccessControlType -eq 'Allow' -and $rule.IdentityReference.Value -notin @('S-1-5-18','S-1-5-32-544',$sid) -and
                ($rule.FileSystemRights -band $write)) {
                throw 'Existing Northstar service data is writable by an untrusted account. Resolve this before installing.'
            }
        }
    }
}
New-Item -ItemType Directory -Force -Path $data | Out-Null
$directoryAcl = New-Object Security.AccessControl.DirectorySecurity
$directoryAcl.SetAccessRuleProtection($true, $false)
$directoryAcl.SetOwner([Security.Principal.SecurityIdentifier]'S-1-5-32-544')
foreach ($principal in @('S-1-5-18','S-1-5-32-544')) {
    $directoryAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
        [Security.Principal.SecurityIdentifier]$principal, 'FullControl', 'ContainerInherit,ObjectInherit', 'None', 'Allow'))
}
$directoryAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new(
    [Security.Principal.SecurityIdentifier]$sid, 'ReadAndExecute', 'None', 'None', 'Allow'))
Set-Acl -LiteralPath $data -AclObject $directoryAcl
# Rotate on every install/upgrade. Removing the old directory entry first avoids
# writing through an old hardlink; a locked hostile file makes setup fail safely.
if (Test-Path -LiteralPath $tokenFile) { Remove-Item -LiteralPath $tokenFile -Force }
$bytes = New-Object byte[] 48
$rng = [Security.Cryptography.RandomNumberGenerator]::Create()
try { $rng.GetBytes($bytes) } finally { $rng.Dispose() }
$stream = [IO.File]::Open($tokenFile, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
try {
    $encoded = [Text.Encoding]::ASCII.GetBytes([Convert]::ToBase64String($bytes))
    $stream.Write($encoded, 0, $encoded.Length)
} finally { $stream.Dispose() }
$fileAcl = New-Object Security.AccessControl.FileSecurity
$fileAcl.SetAccessRuleProtection($true, $false)
$fileAcl.SetOwner([Security.Principal.SecurityIdentifier]'S-1-5-32-544')
foreach ($principal in @('S-1-5-18','S-1-5-32-544')) {
    $fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$principal, 'FullControl', 'Allow'))
}
$fileAcl.AddAccessRule([Security.AccessControl.FileSystemAccessRule]::new([Security.Principal.SecurityIdentifier]$sid, 'Read', 'Allow'))
Set-Acl -LiteralPath $tokenFile -AclObject $fileAcl
$quotedServicePath = '"' + $serviceExe + '"'
if ($existing) {
    $result = Invoke-CimMethod -InputObject (Get-CimInstance Win32_Service -Filter "Name='$name'") -MethodName Change -Arguments @{ PathName = $quotedServicePath; StartMode = 'Automatic' }
} else {
    $result = Invoke-CimMethod -ClassName Win32_Service -MethodName Create -Arguments @{
        Name = $name; DisplayName = 'Northstar VPN Helper'; PathName = $quotedServicePath
        StartMode = 'Automatic'; StartName = 'LocalSystem'; ServiceType = [byte]16; ErrorControl = [byte]1
    }
}
if ($result.ReturnValue -ne 0) { throw "Service registration failed: $($result.ReturnValue)" }
if ((Get-CimInstance Win32_Service -Filter "Name='$name'").PathName -cne $quotedServicePath) {
    throw 'The service executable path was not stored with the required quotes.'
}
Invoke-Sc -Arguments @('description', $name, 'Northstar OpenVPN process and IPv6 firewall guard')
Invoke-Sc -Arguments @('failure', $name, 'reset=', '86400', 'actions=', 'restart/5000/restart/15000/restart/30000')
Start-Service $name
(Get-Service $name).WaitForStatus('Running', [TimeSpan]::FromSeconds(30))
$deadline = [DateTime]::UtcNow.AddSeconds(20)
do {
    $processId = (Get-CimInstance Win32_Service -Filter "Name='$name'").ProcessId
    $listener = Get-NetTCPConnection -State Listen -LocalPort 8799 -ErrorAction SilentlyContinue |
        Where-Object { $_.LocalAddress -eq '127.0.0.1' -and $_.OwningProcess -eq $processId -and $processId -ne 0 }
    if ($listener) { exit 0 }
    Start-Sleep -Milliseconds 250
} while ([DateTime]::UtcNow -lt $deadline)
throw 'The installed helper did not bind its loopback endpoint. Check Windows Event Viewer.'
