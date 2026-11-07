!macro customInstall
  nsExec::ExecToStack '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\scripts\install-windows-service.ps1" -Action Install'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Northstar helper installation failed. Disconnect VPN and close the development helper, then retry.$\r$\n$1"
    Abort
  ${EndIf}
!macroend

!macro customUnInstall
  nsExec::ExecToStack '"$WINDIR\Sysnative\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -NonInteractive -ExecutionPolicy Bypass -File "$INSTDIR\resources\scripts\install-windows-service.ps1" -Action Uninstall'
  Pop $0
  Pop $1
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Could not stop/remove the VPN helper safely. Files have not been removed.$\r$\n$1"
    Abort
  ${EndIf}
!macroend
