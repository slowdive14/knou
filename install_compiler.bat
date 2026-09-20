@echo off
REM C compiler install helper. Double-click this file.
REM Korean messages and the real work live in install_compiler.ps1 (PowerShell
REM handles Unicode reliably; .bat cannot show Korean without breaking).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install_compiler.ps1"
echo.
pause
