@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\auto-lp\generate-and-publish.ps1"
if errorlevel 1 (
  echo.
  echo Auto LP process failed.
)
pause
