@echo off
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp010_Deployment\Scripts\start-local.ps1"
if errorlevel 1 (
  pause
  exit /b 1
)
start "" "http://127.0.0.1:3000"
