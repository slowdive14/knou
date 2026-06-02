@echo off
chcp 65001 >nul
cd /d "%~dp0"
title KNOU 설치 도우미

echo ============================================================
echo   KNOU 강의 자동화 - 설치 도우미
echo ============================================================
echo.
echo 이 창을 닫지 말고 끝날 때까지 기다려 주세요.
echo 인터넷 속도에 따라 몇 분 정도 걸릴 수 있습니다.
echo.

REM --- 1) 파이썬 확인 ---
echo [1/4] 파이썬(Python) 확인 중...
python --version >nul 2>&1
if errorlevel 1 (
  echo.
  echo [멈춤] 파이썬을 찾지 못했습니다. 먼저 파이썬을 설치하세요.
  echo   1^) https://www.python.org/downloads/ 접속 후 [Download] 클릭
  echo   2^) 설치 첫 화면에서 "Add Python to PATH" 를 꼭 체크
  echo   3^) 설치가 끝나면 이 파일 install.bat 을 다시 더블클릭
  echo.
  pause
  exit /b 1
)
python --version
echo.

REM --- 2) 전용 환경(.venv) 만들기 ---
echo [2/4] 전용 파이썬 환경 만드는 중... (.venv 폴더)
if exist ".venv\Scripts\python.exe" (
  echo   이미 있어서 건너뜁니다.
) else (
  python -m venv .venv
  if errorlevel 1 goto :fail
)
echo.

REM --- 3) 라이브러리 설치 ---
echo [3/4] 필요한 프로그램 설치 중... (시간이 좀 걸립니다)
".venv\Scripts\python.exe" -m pip install --upgrade pip >nul 2>&1
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto :fail
echo.

REM --- 4) 영상 시청용 브라우저 설치 ---
echo [4/4] 영상 시청용 브라우저(크로미움) 설치 중...
".venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 goto :fail
echo.

echo ============================================================
echo   설치 완료! 이제 'run_app.bat' 을 더블클릭해 앱을 켜세요.
echo ============================================================
echo.
echo (참고) 영상에서 소리를 뽑아내려면 ffmpeg 도 필요합니다.
echo        설치 방법은 README 의 'ffmpeg' 안내를 보세요.
echo.
pause
exit /b 0

:fail
echo.
echo [멈춤] 설치 중 문제가 생겼습니다. 위에 나온 영문 메시지를 확인하세요.
echo        인터넷 연결을 확인한 뒤 이 파일을 다시 더블클릭해 보세요.
echo.
pause
exit /b 1
