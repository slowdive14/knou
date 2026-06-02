@echo off
REM KNOU Helper - launch the Flet desktop app from source.
REM Double-click this file. Requires the project venv (.venv).
cd /d "%~dp0"
".venv\Scripts\python.exe" -m app.main_app
if errorlevel 1 (
  echo.
  echo [!] App exited with an error. See the message above.
  pause
)
