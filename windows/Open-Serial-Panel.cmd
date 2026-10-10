@echo off
where pwsh.exe >nul 2>nul
if errorlevel 1 (
  powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Serial.ps1" -PanelOnly
) else (
  pwsh.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0Start-Serial.ps1" -PanelOnly
)
pause
