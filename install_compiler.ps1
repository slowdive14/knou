# KNOU 강의 자동화 - C 컴파일러 설치 도우미
# (install_compiler.bat 이 이 파일을 실행합니다)
#
# 왜 필요한가: 기출 '변형 문제' 를 만들 때, AI 가 만든 C 코드를 **실제로 돌려 봐야**
# 정답을 확신할 수 있습니다. C 기출은 '이 코드의 출력은?' 이 태반인데 AI 는 실행
# 결과를 자주 틀리기 때문입니다. 컴파일러가 없으면 그런 문제는 아예 만들지 않습니다.
Set-Location -LiteralPath $PSScriptRoot

$PkgId = 'BrechtSanders.WinLibs.POSIX.UCRT'

Write-Host '============================================================'
Write-Host '  C 컴파일러 설치 도우미'
Write-Host '============================================================'
Write-Host ''
Write-Host '이 창을 닫지 말고 끝날 때까지 기다려 주세요.'
Write-Host '용량이 커서 (수백 MB) 몇 분 걸릴 수 있습니다.'
Write-Host ''

# 1) 이미 있으면 그냥 끝낸다
Write-Host '[1/3] 이미 설치돼 있는지 확인 중...'
$have = $null
foreach ($n in @('gcc', 'clang', 'cc')) {
    $c = Get-Command $n -ErrorAction SilentlyContinue
    if ($c) { $have = $c; break }
}
if ($have) {
    Write-Host ''
    Write-Host "이미 설치돼 있습니다: $($have.Source)" -ForegroundColor Green
    Write-Host '더 할 일이 없습니다. 이 창을 닫으셔도 됩니다.'
    exit 0
}
Write-Host '   아직 없습니다. 설치를 진행합니다.'
Write-Host ''

# 2) winget 확인 — 윈도우 10/11 에 기본으로 들어 있다
Write-Host '[2/3] 설치 도구(winget) 확인 중...'
if (-not (Get-Command winget -ErrorAction SilentlyContinue)) {
    Write-Host ''
    Write-Host '[멈춤] winget 을 찾지 못했습니다.' -ForegroundColor Red
    Write-Host '  윈도우 10 이상이면 보통 들어 있습니다.'
    Write-Host '  Microsoft Store 에서 "앱 설치 관리자" 를 설치한 뒤 다시 시도하세요.'
    exit 1
}
Write-Host '   winget 있음'
Write-Host ''

# 3) 설치
Write-Host '[3/3] C 컴파일러(MinGW-w64) 설치 중... 시간이 걸립니다.'
Write-Host ''
winget install -e --id $PkgId --accept-package-agreements --accept-source-agreements
$code = $LASTEXITCODE
Write-Host ''

if ($code -ne 0) {
    Write-Host '[멈춤] 설치가 끝나지 못했습니다.' -ForegroundColor Red
    Write-Host '  화면 위쪽 메시지를 확인해 주세요. 흔한 경우:'
    Write-Host '   · 인터넷 연결이 끊겼다'
    Write-Host '   · 관리자 권한이 필요하다 → 이 파일을 마우스 오른쪽 클릭 →'
    Write-Host '     [관리자 권한으로 실행]'
    exit 1
}

Write-Host '============================================================'
Write-Host '  설치 완료!' -ForegroundColor Green
Write-Host '============================================================'
Write-Host ''
Write-Host '이제 다음을 해 주세요:'
Write-Host '  1) 열려 있는 KNOU 앱 창을 닫았다가 다시 켜기'
Write-Host '  2) 이 창도 닫기'
Write-Host ''
Write-Host '(설치한 것이 인식되려면 창을 새로 열어야 합니다.)'
Write-Host ''
