@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0tools\auto-lp\generate-and-publish.ps1"
if errorlevel 1 (
  echo.
  echo Auto LP process failed.
)
echo.
echo This window will now stay open (it will not close by itself).
echo You can safely type git commands here if needed, or just close the window.
echo.
cmd /k
