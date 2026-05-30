@echo off
cd /d "%~dp0"
echo ============================================
echo   KNOU LMS recon
echo ============================================
echo.
".venv\Scripts\python.exe" recon.py
echo.
echo --------------------------------------------
echo   Done. You can close this window.
echo --------------------------------------------
pause
