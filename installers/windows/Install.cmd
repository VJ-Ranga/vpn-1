@echo off
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0Install.ps1"
if errorlevel 1 (
    echo Installer preparation failed. Keep both installer parts and Install.ps1 together.
    pause
    exit /b 1
)
