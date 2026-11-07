param([switch]$BuildOnly)
$ErrorActionPreference = 'Stop'
$name = 'Northstar-VPN-0.2.1-Setup-x64.exe'
$expectedHash = '10FB2C046162656E1FAB12000B14DBAAE0167F9BA3910D920C823766AA6BADB5'
$destination = Join-Path $PSScriptRoot $name
$temporary = Join-Path $PSScriptRoot ($name + '.' + [Guid]::NewGuid().ToString('N') + '.tmp')
try {
    foreach ($number in @(1,2)) {
        if (-not (Test-Path -LiteralPath (Join-Path $PSScriptRoot "$name.part$number") -PathType Leaf)) {
            throw "Missing $name.part$number. Download both parts and keep them beside this script."
        }
    }
    Write-Host 'Assembling Northstar VPN installer...'
    $output = [IO.File]::Open($temporary, [IO.FileMode]::CreateNew, [IO.FileAccess]::Write, [IO.FileShare]::None)
    try {
        foreach ($number in @(1,2)) {
            $inputFile = [IO.File]::OpenRead((Join-Path $PSScriptRoot "$name.part$number"))
            try { $inputFile.CopyTo($output) } finally { $inputFile.Dispose() }
        }
    } finally { $output.Dispose() }
    if ((Get-FileHash -LiteralPath $temporary -Algorithm SHA256).Hash -cne $expectedHash) {
        throw 'Installer checksum mismatch. Nothing was installed. Download both parts again.'
    }
    Move-Item -LiteralPath $temporary -Destination $destination -Force
    Write-Host "Verified installer: $destination"
    if (-not $BuildOnly) {
        $process = Start-Process -FilePath $destination -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "Setup exited with code $($process.ExitCode)." }
    }
} catch {
    Write-Error $_
    exit 1
} finally {
    if (Test-Path -LiteralPath $temporary) { Remove-Item -LiteralPath $temporary -Force }
}
