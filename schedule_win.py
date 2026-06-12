"""[schedule_win] 자동 예약 — Windows 작업 스케줄러(schtasks) 다리.

예약 화면에서 고른 모드·필터·시각을 Windows 작업 스케줄러에 등록한다. 앱·터미널이
꺼져 있어도 지정 시각에 `run_*.bat` 가 실행되어 기존 `main.py` 를 구동한다.
백엔드는 한 줄도 고치지 않는다(여기서도 `main.py` 를 하위 프로세스로 부를 뿐).

순수 로직(단위테스트):
  - valid_time(hhmm)                      → "HH:MM" 24시간 형식 검증
  - task_display_name(mode, course, seq)  → schtasks /TN 작업 이름(접두사 KNOU_)
  - script_filename(mode, course, seq)    → ASCII 안전 .bat 파일명
  - build_run_script(py, dir, mode, …)    → run_*.bat 내용(keep_awake.py 경유 main.py)
  - build_vbs_launcher(bat)               → .bat 을 창 없이 실행하는 VBS 내용
  - build_run_command(vbs)                → /TR 에 넣을 wscript 실행 명령
  - build_schtasks_create_args(…)         → schtasks /Create argv
  - build_schtasks_delete_args(name)      → schtasks /Delete argv
  - build_schtasks_change_args(name, on)  → schtasks /Change /ENABLE|/DISABLE argv
  - build_schtasks_query_args()           → schtasks /Query argv(CSV·헤더없음)
  - parse_schtasks_list(csv)              → [{name, next_run, status}] (우리 접두사만)
  - is_disabled_status(status)            → 상태가 '사용 안 함'(비활성)인지

IO(수동 검증):
  - write_run_script(...)                 → .bat·.vbs 파일 저장(UTF-8)
  - create_task / list_tasks / delete_task→ schtasks.exe 호출
  - set_task_enabled(name, enabled)       → 예약 사용/중지 전환

⚠️ .bat·argv 어디에도 비밀번호·GEMINI_API_KEY 평문이 흐르지 않는다
   (비밀값은 예약 실행 시 자식 main.py 가 .env 에서 직접 읽는다).
"""
from __future__ import annotations

import csv
import hashlib
import io
import re
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_PY = PROJECT_ROOT / "main.py"
# 예약 .bat 들을 모아두는 폴더(ASCII 경로 일부 — 파일명은 항상 ASCII).
SCRIPTS_DIR = PROJECT_ROOT / "schedule_scripts"

# 우리가 만든 작업만 구분하는 접두사(목록 필터·중복판정에 사용).
TASK_PREFIX = "KNOU_"

# 모드(한글) → .bat 파일명에 쓸 ASCII 토큰
_MODE_ASCII = {"요약": "summary", "이수": "watch", "전체": "full"}

# 콘솔 창 안 뜨게(Windows). 다른 OS/환경에선 0.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

_TIME_RE = re.compile(r"^([01]?\d|2[0-3]):([0-5]\d)$")


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def valid_time(hhmm: str) -> bool:
    """"HH:MM"(24시간) 형식이면 True. 'HH'는 한 자리도 허용(예: 9:05)."""
    return bool(_TIME_RE.match((hhmm or "").strip()))


def normalize_time(hhmm: str) -> str:
    """검증된 시각을 schtasks /ST 용 'HH:MM'(시 두 자리)로 0 패딩."""
    m = _TIME_RE.match((hhmm or "").strip())
    if not m:
        return hhmm
    return f"{int(m.group(1)):02d}:{m.group(2)}"


def next_occurrence(hhmm: str, now: datetime | None = None) -> str:
    """다음 실행 시각 ISO('YYYY-MM-DDTHH:MM:SS'). 오늘 그 시각이 지났으면 내일.

    StartBoundary 를 **미래**로 둬, StartWhenAvailable(놓친 예약 보충)이 켜져 있어도
    등록 직후 '과거에 놓친 실행'으로 오해해 곧바로 실행되는 일을 막는다.
    """
    m = _TIME_RE.match((hhmm or "").strip())
    if not m:
        raise ValueError(f"잘못된 시각: {hhmm!r}")
    now = now or datetime.now()
    target = now.replace(hour=int(m.group(1)), minute=int(m.group(2)),
                         second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return target.strftime("%Y-%m-%dT%H:%M:%S")


def _filter_token(mode, course, seq) -> str:
    """필터(mode|course|seq)를 식별하는 짧은 8자리 해시(파일명·이름 구분용)."""
    raw = f"{mode}|{course or ''}|{seq if seq is not None else ''}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:8]


def task_display_name(mode: str, course=None, seq=None) -> str:
    """schtasks 작업 이름. 접두사 + 모드 + (선택)과목 + (선택)차시.

    예: 'KNOU_요약', 'KNOU_이수_데이터베이스시스템_13강'.
    """
    parts = [mode]
    if course:
        parts.append(str(course))
    if seq is not None:
        parts.append(f"{int(seq)}강")
    # 작업 이름에 경로 구분자(\,/)가 들어가면 하위 폴더로 오해되므로 치환.
    name = TASK_PREFIX + "_".join(parts)
    return name.replace("\\", "_").replace("/", "_")


def script_filename(mode: str, course=None, seq=None) -> str:
    """ASCII 안전한 .bat 파일명. 필터가 있으면 짧은 해시로 구분.

    과목명이 한글이라 파일명엔 넣지 않고(=ASCII 보장), 해시로 유일성만 준다.
    """
    base = _MODE_ASCII.get(mode, "run")
    if course or seq is not None:
        return f"run_{base}_{_filter_token(mode, course, seq)}.bat"
    return f"run_{base}.bat"


def _quote(v) -> str:
    """배치 인자용 큰따옴표 감싸기(공백 안전). 내부 따옴표는 제거."""
    return '"' + str(v).replace('"', "") + '"'


def build_run_script(py, project_dir, mode, course=None, seq=None,
                     unwatched: bool = False, limit=None,
                     main_py="main.py", keep_awake_py="keep_awake.py") -> str:
    """예약 실행용 `run_*.bat` 내용을 만든다(순수).

    `chcp 65001`(UTF-8)로 한글 인자(--mode/--course)를 보존하고, 프로젝트
    폴더로 이동해 venv python 으로 main.py 를 구동한다. 단, main.py 를 직접
    부르지 않고 `keep_awake.py` 를 통해 부른다 — 실행 동안 PC가 절전에 들지 않게
    막아 야간 무인 이수가 중간에 멈추지 않도록 한다(끝나면 자동 해제). 비밀값은
    인자에 없다(자식이 .env 에서 읽음).
    """
    line = [_quote(py), "-u", keep_awake_py, main_py, "--mode", _quote(mode)]
    if course:
        line += ["--course", _quote(course)]
    if seq is not None:
        line += ["--seq", str(int(seq))]
    if unwatched:
        line += ["--unwatched"]
    if limit is not None:
        line += ["--limit", str(int(limit))]
    cmd = " ".join(line)
    return (
        "@echo off\r\n"
        "chcp 65001 >nul\r\n"
        "set PYTHONUTF8=1\r\n"
        "set PYTHONIOENCODING=utf-8\r\n"
        f'cd /d "{project_dir}"\r\n'
        f"{cmd}\r\n"
    )


def build_vbs_launcher(bat_path) -> str:
    """예약 .bat 를 **창 없이(hidden)** 실행하는 VBScript 내용(순수).

    작업 스케줄러가 .bat 를 /TR 로 직접 돌리면 콘솔 창이 잠깐 떴다 사라진다.
    wscript 로 이 VBS 를 돌리면 `Run(.., 0, False)` 의 0(=SW_HIDE) 덕분에 창이
    전혀 보이지 않는다. 실행 결과(로그)는 main.py 가 logs/run_*.log 에 남기므로
    앱 '실행' 탭의 '최근 실행 로그 보기'로 확인한다.
    """
    p = str(bat_path).replace('"', "")
    return (
        'Set sh = CreateObject("WScript.Shell")\r\n'
        f'sh.Run Chr(34) & "{p}" & Chr(34), 0, False\r\n'
    )


def build_run_command(vbs_path) -> str:
    """예약 /TR 에 넣을 실행 명령: wscript 로 VBS 를 **창 없이** 실행한다.

    //B(배치모드: 오류 팝업 억제) //Nologo(배너 숨김). 경로에 공백이 있어도
    안전하도록 큰따옴표로 감싼다.
    """
    return f'wscript.exe //B //Nologo "{str(vbs_path)}"'


def build_run_exec(vbs_path) -> tuple[str, str]:
    """XML Exec 액션용 (Command, Arguments). 콘솔 숨김 wscript 로 VBS 실행."""
    return "wscript.exe", f'//B //Nologo "{str(vbs_path)}"'


def _xml_escape(s) -> str:
    """XML 텍스트 이스케이프(경로·인자 안전)."""
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;").replace("'", "&apos;"))


def build_task_xml(command, arguments, start_boundary, freq: str = "DAILY",
                   highest: bool = False, *,
                   start_when_available: bool = True,
                   allow_on_batteries: bool = True, wake: bool = False,
                   execution_time_limit: str = "PT72H") -> str:
    """작업 스케줄러 등록용 XML(스키마 1.2) 생성(순수).

    기본 `schtasks /Create` 플래그로는 못 바꾸는 안정성 설정을 켜기 위해 XML 로
    등록한다(`schtasks /Create /XML`):
      - start_when_available: 지정 시각에 PC가 꺼/자고 있어 놓쳤으면, 다음에 켤 때 실행.
      - allow_on_batteries: 노트북이 배터리여도 실행(중간에 충전 빠져도 중단 안 함).
      - wake: True 면 자는 PC를 깨워 실행(노트북은 보통 False 권장).
    freq: 'DAILY'(매일) | 'ONCE'(한 번). start_boundary: 'YYYY-MM-DDTHH:MM:SS'.
    """
    sb = _xml_escape(start_boundary)
    if str(freq).upper() == "ONCE":
        trigger = (f"    <TimeTrigger>\n"
                   f"      <StartBoundary>{sb}</StartBoundary>\n"
                   f"      <Enabled>true</Enabled>\n"
                   f"    </TimeTrigger>")
    else:
        trigger = (f"    <CalendarTrigger>\n"
                   f"      <StartBoundary>{sb}</StartBoundary>\n"
                   f"      <Enabled>true</Enabled>\n"
                   f"      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>\n"
                   f"    </CalendarTrigger>")
    run_level = "HighestAvailable" if highest else "LeastPrivilege"
    no_batt = "false" if allow_on_batteries else "true"
    swa = "true" if start_when_available else "false"
    wk = "true" if wake else "false"
    return (
        '<?xml version="1.0" encoding="UTF-16"?>\n'
        '<Task version="1.2" '
        'xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">\n'
        '  <RegistrationInfo>\n'
        '    <Author>KNOU</Author>\n'
        '    <Description>KNOU 강의 자동 예약</Description>\n'
        '  </RegistrationInfo>\n'
        '  <Triggers>\n'
        f'{trigger}\n'
        '  </Triggers>\n'
        '  <Principals>\n'
        '    <Principal id="Author">\n'
        '      <LogonType>InteractiveToken</LogonType>\n'
        f'      <RunLevel>{run_level}</RunLevel>\n'
        '    </Principal>\n'
        '  </Principals>\n'
        '  <Settings>\n'
        '    <AllowStartOnDemand>true</AllowStartOnDemand>\n'
        '    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>\n'
        f'    <DisallowStartIfOnBatteries>{no_batt}</DisallowStartIfOnBatteries>\n'
        f'    <StopIfGoingOnBatteries>{no_batt}</StopIfGoingOnBatteries>\n'
        '    <AllowHardTerminate>true</AllowHardTerminate>\n'
        f'    <StartWhenAvailable>{swa}</StartWhenAvailable>\n'
        '    <RunOnlyIfNetworkAvailable>false</RunOnlyIfNetworkAvailable>\n'
        '    <IdleSettings>\n'
        '      <StopOnIdleEnd>false</StopOnIdleEnd>\n'
        '      <RestartOnIdle>false</RestartOnIdle>\n'
        '    </IdleSettings>\n'
        '    <Enabled>true</Enabled>\n'
        '    <Hidden>false</Hidden>\n'
        '    <RunOnlyIfIdle>false</RunOnlyIfIdle>\n'
        f'    <WakeToRun>{wk}</WakeToRun>\n'
        f'    <ExecutionTimeLimit>{execution_time_limit}</ExecutionTimeLimit>\n'
        '    <Priority>7</Priority>\n'
        '  </Settings>\n'
        '  <Actions Context="Author">\n'
        '    <Exec>\n'
        f'      <Command>{_xml_escape(command)}</Command>\n'
        f'      <Arguments>{_xml_escape(arguments)}</Arguments>\n'
        '    </Exec>\n'
        '  </Actions>\n'
        '</Task>\n'
    )


def build_schtasks_create_xml_args(task_name, xml_path) -> list[str]:
    """`schtasks /Create /TN <name> /XML <file> /F` argv(XML 정의로 등록·덮어쓰기)."""
    return ["schtasks", "/Create", "/TN", str(task_name),
            "/XML", str(xml_path), "/F"]


def build_schtasks_create_args(task_name, time_hhmm, run_command,
                               freq: str = "DAILY",
                               highest: bool = False) -> list[str]:
    """`schtasks /Create …` argv. freq 는 'DAILY' | 'ONCE'.

    run_command 는 /TR 에 **그대로** 들어갈 실행 명령(콘솔 창을 숨기려고 wscript
    로 VBS 를 부르는 명령 전체). subprocess 에 argv 리스트로 넘기므로 한 원소로
    전달되어 schtasks 가 통째로 저장한다(추가 따옴표 가공 없음).
    highest=True 면 최고권한(/RL HIGHEST). /F 로 동명 작업 덮어쓰기.
    """
    argv = [
        "schtasks", "/Create",
        "/TN", str(task_name),
        "/TR", str(run_command),
        "/SC", str(freq).upper(),
        "/ST", str(time_hhmm),
        "/F",
    ]
    if highest:
        argv += ["/RL", "HIGHEST"]
    return argv


def build_schtasks_change_args(task_name, enabled: bool) -> list[str]:
    """`schtasks /Change /TN <name> /ENABLE|/DISABLE` argv(예약 사용/중지)."""
    flag = "/ENABLE" if enabled else "/DISABLE"
    return ["schtasks", "/Change", "/TN", str(task_name), flag]


def is_disabled_status(status: str) -> bool:
    """schtasks 상태 문자열이 '사용 안 함'(비활성)인지 판단(영문 Disabled 도 인식)."""
    s = (status or "")
    return ("사용 안" in s) or ("disabl" in s.lower())


def build_schtasks_delete_args(task_name) -> list[str]:
    """`schtasks /Delete /TN <name> /F` argv."""
    return ["schtasks", "/Delete", "/TN", str(task_name), "/F"]


def build_schtasks_query_args() -> list[str]:
    """`schtasks /Query /FO CSV /NH` argv(헤더 없는 CSV: 이름,다음실행,상태)."""
    return ["schtasks", "/Query", "/FO", "CSV", "/NH"]


def parse_schtasks_list(csv_output: str, prefix: str = TASK_PREFIX) -> list[dict]:
    """schtasks CSV(헤더없음) → [{name, next_run, status}] (우리 접두사만).

    schtasks 는 작업 이름을 '\\KNOU_요약' 처럼 선행 백슬래시와 함께 준다 →
    한 칸 제거 후 접두사로 필터. 정보줄(INFO:)·빈 줄은 무시.
    """
    out: list[dict] = []
    if not csv_output:
        return out
    reader = csv.reader(io.StringIO(csv_output))
    for row in reader:
        if len(row) < 3:
            continue
        name = row[0].strip()
        if name.startswith("\\"):
            name = name[1:]
        if not name.startswith(prefix):
            continue
        out.append({"name": name,
                    "next_run": row[1].strip(),
                    "status": row[2].strip()})
    return out


# ---------------------------------------------------------------------------
# IO (수동 검증) — .bat 저장 + schtasks 호출
# ---------------------------------------------------------------------------
def write_run_script(content: str, filename: str, scripts_dir=SCRIPTS_DIR) -> Path:
    """예약 .bat 를 scripts_dir 에 UTF-8 로 저장하고 경로 반환.

    `chcp 65001` 과 짝이 되도록 UTF-8(BOM 없음)로 기록한다.
    """
    d = Path(scripts_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_text(content, encoding="utf-8")
    return path


def write_task_xml(content: str, filename: str, scripts_dir=SCRIPTS_DIR) -> Path:
    """작업 정의 XML 을 UTF-16 으로 저장(헤더의 encoding='UTF-16' 과 일치)."""
    d = Path(scripts_dir)
    d.mkdir(parents=True, exist_ok=True)
    path = d / filename
    path.write_text(content, encoding="utf-16")
    return path


def _console_encoding() -> str:
    """schtasks 출력 디코딩용 OEM 콘솔 코드페이지(한국어 Windows=cp949).

    schtasks 는 UTF-8 이 아니라 OEM 콘솔 코드페이지로 출력한다 → 작업 이름의
    한글(과목명·차시)과 상태('준비'/'사용 안 함')가 깨져 화면에 �로 뜬다.
    GetOEMCP 로 정확히 맞춘다(실패 시 locale → utf-8 폴백). 접두사는 영문
    'KNOU_' 라 인코딩이 틀려도 목록 필터 자체는 안전하다.
    """
    try:
        import ctypes
        cp = ctypes.windll.kernel32.GetOEMCP()  # type: ignore[attr-defined]
        if cp:
            return f"cp{cp}"
    except Exception:
        pass
    try:
        import locale
        return locale.getpreferredencoding(False) or "utf-8"
    except Exception:
        return "utf-8"


def _run_schtasks(argv: list[str]) -> subprocess.CompletedProcess:
    """schtasks.exe 호출(콘솔창 숨김). 출력은 OEM 코드페이지로 디코딩(한글 보존)."""
    return subprocess.run(
        argv, capture_output=True, text=True,
        encoding=_console_encoding(), errors="replace",
        creationflags=_NO_WINDOW,
    )


def create_task(py, project_dir, mode, time_hhmm, course=None, seq=None,
                unwatched: bool = False, freq: str = "DAILY",
                highest: bool = False, scripts_dir=SCRIPTS_DIR) -> dict:
    """예약 1건 등록: .bat 생성 → schtasks /Create. 결과 dict 반환.

    최고권한(/RL HIGHEST)은 schtasks 가 **관리자 권한**으로 실행돼야만 등록되어,
    일반 사용자에선 '액세스 거부'가 난다. 이 경우 자동으로 **일반 권한으로 재시도**
    해 등록을 성사시키고(downgraded=True), 호출 측이 안내할 수 있게 한다.

    반환: {ok, name, script, returncode, stdout, stderr, downgraded}.
    """
    name = task_display_name(mode, course, seq)
    fname = script_filename(mode, course, seq)
    content = build_run_script(py, project_dir, mode, course=course,
                               seq=seq, unwatched=unwatched)
    script_path = write_run_script(content, fname, scripts_dir)
    # 콘솔 창이 뜨지 않도록 .bat 을 감싸는 VBS 런처(같은 폴더, ASCII 파일명).
    vbs_name = Path(fname).with_suffix(".vbs").name
    vbs_path = write_run_script(build_vbs_launcher(script_path),
                                vbs_name, scripts_dir)
    command, arguments = build_run_exec(vbs_path)
    start_boundary = next_occurrence(time_hhmm)
    xml_name = Path(fname).with_suffix(".xml").name

    # XML 정의로 등록 → 기본 schtasks 플래그로 못 켜는 안정성 설정(놓친 예약 보충·
    # 배터리에서도 실행)을 적용한다. 노트북이 지정 시각에 자고 있어도 다음에 켤 때
    # 실행된다.
    def _create(use_highest):
        xml = build_task_xml(command, arguments, start_boundary,
                             freq=freq, highest=use_highest)
        xml_path = write_task_xml(xml, xml_name, scripts_dir)
        return _run_schtasks(build_schtasks_create_xml_args(name, xml_path))

    proc = _create(highest)
    downgraded = False
    if proc.returncode != 0 and highest:
        # 최고권한 등록 실패(주로 비관리자 액세스 거부) → 일반 권한으로 자동 재시도
        retry = _create(False)
        if retry.returncode == 0:
            proc, downgraded = retry, True

    return {"ok": proc.returncode == 0, "name": name,
            "script": str(script_path), "vbs": str(vbs_path),
            "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr,
            "downgraded": downgraded}


def list_tasks() -> list[dict]:
    """등록된 우리 예약 목록(없거나 조회 실패 시 [])."""
    proc = _run_schtasks(build_schtasks_query_args())
    if proc.returncode != 0:
        return []
    return parse_schtasks_list(proc.stdout or "")


def delete_task(name: str, scripts_dir=SCRIPTS_DIR) -> dict:
    """예약 삭제: schtasks /Delete. (생성한 .bat 은 남겨둬도 무해하므로 유지)"""
    proc = _run_schtasks(build_schtasks_delete_args(name))
    return {"ok": proc.returncode == 0, "name": name,
            "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr}


def set_task_enabled(name: str, enabled: bool) -> dict:
    """예약 사용/중지 전환: schtasks /Change /ENABLE|/DISABLE.

    삭제하지 않고 잠시 꺼두고 싶을 때 사용(다시 켜면 같은 시각에 재개).
    """
    proc = _run_schtasks(build_schtasks_change_args(name, enabled))
    return {"ok": proc.returncode == 0, "name": name, "enabled": enabled,
            "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr}
