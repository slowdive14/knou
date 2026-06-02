@echo off
REM KNOU install helper. Double-click this file.
REM Korean messages and the real work live in install.ps1 (PowerShell handles
REM Unicode reliably; .bat cannot show Korean without breaking).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install.ps1"
echo.
pause
