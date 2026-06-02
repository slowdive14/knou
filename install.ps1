# KNOU 강의 자동화 - 설치 도우미 (install.bat 이 이 파일을 실행합니다)
# PowerShell 은 유니코드를 제대로 처리하므로 한글이 깨지지 않습니다.
Set-Location -LiteralPath $PSScriptRoot

function Show-Fail($msg) {
    Write-Host ''
    Write-Host "[멈춤] $msg" -ForegroundColor Red
    exit 1
}

Write-Host '============================================================'
Write-Host '  KNOU 강의 자동화 - 설치 도우미'
Write-Host '============================================================'
Write-Host ''
Write-Host '이 창을 닫지 말고 끝날 때까지 기다려 주세요.'
Write-Host '인터넷 속도에 따라 몇 분 정도 걸릴 수 있습니다.'
Write-Host ''

# 1) 파이썬 확인
Write-Host '[1/4] 파이썬(Python) 확인 중...'
$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) {
    Write-Host ''
    Write-Host '[멈춤] 파이썬을 찾지 못했습니다. 먼저 파이썬을 설치하세요.' -ForegroundColor Red
    Write-Host '  1) https://www.python.org/downloads/ 에서 [Download] 클릭'
    Write-Host '  2) 설치 첫 화면에서 "Add Python to PATH" 를 꼭 체크'
    Write-Host '  3) 설치가 끝나면 install.bat 을 다시 더블클릭'
    exit 1
}
python --version
Write-Host ''

# 2) 전용 환경(.venv) 만들기
Write-Host '[2/4] 전용 파이썬 환경 만드는 중... (.venv 폴더)'
if (Test-Path '.venv\Scripts\python.exe') {
    Write-Host '  이미 있어서 건너뜁니다.'
} else {
    python -m venv .venv
    if ($LASTEXITCODE -ne 0) { Show-Fail '.venv 생성에 실패했습니다.' }
}
Write-Host ''

$venvPy = '.venv\Scripts\python.exe'

# 3) 라이브러리 설치
Write-Host '[3/4] 필요한 프로그램 설치 중... (시간이 좀 걸립니다)'
& $venvPy -m pip install --upgrade pip 2>&1 | Out-Null
& $venvPy -m pip install -r requirements.txt
if ($LASTEXITCODE -ne 0) { Show-Fail '라이브러리 설치에 실패했습니다. 인터넷 연결을 확인하세요.' }
Write-Host ''

# 4) 영상 시청용 브라우저 설치
Write-Host '[4/4] 영상 시청용 브라우저(크로미움) 설치 중...'
& $venvPy -m playwright install chromium
if ($LASTEXITCODE -ne 0) { Show-Fail '브라우저 설치에 실패했습니다. 인터넷 연결을 확인하세요.' }
Write-Host ''

Write-Host '============================================================' -ForegroundColor Green
Write-Host '  설치 완료! 이제 run_app.bat 을 더블클릭해 앱을 켜세요.' -ForegroundColor Green
Write-Host '============================================================' -ForegroundColor Green
Write-Host ''
Write-Host '(선택) 노트에 강의 슬라이드 이미지를 넣으려면 ffmpeg 가 필요합니다.'
Write-Host '       없어도 텍스트 노트는 만들어집니다. 자세한 건 README 를 보세요.'
