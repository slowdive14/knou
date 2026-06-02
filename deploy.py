"""[deploy] 비개발자 배포 도우미 — 창 없이 실행 + 바탕화면 바로가기.

권장 배포 경로는 '소스 + venv' 다. exe 로 묶지 않고도 비개발자가 더블클릭으로
앱을 켤 수 있도록:
  - pythonw.exe 로 **콘솔 창 없이** Flet 창만 띄우는 실행 명령을 만든다.
  - 그 명령을 가리키는 **바탕화면 바로가기(.lnk)** 를 PowerShell(WScript.Shell)로
    만든다(아이콘·작업폴더 지정).

순수 로직(단위테스트):
  - pythonw_path(python_exe)            → 같은 폴더의 pythonw.exe 경로
  - build_launch_command(py, module)    → [pythonw, '-m', 'app.main_app'] argv
  - build_shortcut_ps(lnk, target, …)   → .lnk 생성 PowerShell 스크립트
  - desktop_dir()                       → 바탕화면 경로(OneDrive 폴백 포함)

IO(수동 검증):
  - create_desktop_shortcut(...)        → PowerShell 로 .lnk 실제 생성

⚠️ 바로가기·명령 어디에도 비밀번호·GEMINI_API_KEY 가 들어가지 않는다
   (비밀값은 앱이 .env 에서 읽는다).
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
# 바탕화면 바로가기 표시 이름(짧게 — APP_TITLE 전체는 너무 길다).
SHORTCUT_NAME = "KNOU 강의 자동화"
APP_MODULE = "app.main_app"

# 콘솔 창 안 뜨게(Windows). 다른 OS/환경에선 0.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def pythonw_path(python_exe) -> str:
    """python.exe 와 같은 폴더의 `pythonw.exe`(콘솔 없는 파이썬) 경로.

    이미 pythonw 면 그대로. Flet 창은 보이되 검은 콘솔 창은 안 뜨게 한다.
    """
    p = Path(python_exe)
    name = p.name.lower()
    if name.startswith("pythonw"):
        return str(p)
    if name.startswith("python"):
        # python.exe → pythonw.exe (python3.exe → pythonw3.exe)
        return str(p.with_name(p.name.replace("python", "pythonw", 1)))
    # 이름을 못 알아보면 같은 폴더의 pythonw.exe 로 가정
    return str(p.with_name("pythonw.exe"))


def build_launch_command(python_exe, module: str = APP_MODULE) -> list[str]:
    """앱을 **콘솔 없이** 띄우는 실행 argv: [pythonw, '-m', 'app.main_app']."""
    return [pythonw_path(python_exe), "-m", module]


def _ps_quote(v) -> str:
    """PowerShell 작은따옴표 리터럴용 이스케이프(내부 ' 는 '' 로)."""
    return "'" + str(v).replace("'", "''") + "'"


def build_shortcut_ps(lnk_path, target, arguments: str = "",
                      workdir=None, icon=None) -> str:
    """바탕화면 .lnk 를 만드는 PowerShell 스크립트(WScript.Shell COM).

    target=실행 파일(pythonw.exe), arguments='-m app.main_app',
    workdir=프로젝트 폴더(상대 경로 모듈/.env 를 찾도록), icon=선택.
    """
    parts = [
        "$s = (New-Object -ComObject WScript.Shell)"
        f".CreateShortcut({_ps_quote(lnk_path)})",
        f"$s.TargetPath = {_ps_quote(target)}",
    ]
    if arguments:
        parts.append(f"$s.Arguments = {_ps_quote(arguments)}")
    if workdir:
        parts.append(f"$s.WorkingDirectory = {_ps_quote(workdir)}")
    if icon:
        parts.append(f"$s.IconLocation = {_ps_quote(icon)}")
    parts.append("$s.Save()")
    return "; ".join(parts)


def desktop_dir() -> Path:
    """현재 사용자 바탕화면 경로. OneDrive 백업 환경이면 그쪽을 우선."""
    home = Path.home()
    onedrive = home / "OneDrive" / "Desktop"
    if onedrive.exists():
        return onedrive
    return home / "Desktop"


# ---------------------------------------------------------------------------
# IO (수동 검증)
# ---------------------------------------------------------------------------
def create_desktop_shortcut(python_exe=None, project_dir=PROJECT_ROOT,
                            name: str = SHORTCUT_NAME, icon=None) -> dict:
    """바탕화면에 앱 바로가기(.lnk)를 만든다. 결과 dict 반환.

    target=pythonw, arguments='-m app.main_app', 작업폴더=프로젝트 루트 →
    더블클릭하면 콘솔 없이 Flet 창이 뜬다. (실패해도 앱 사용엔 지장 없음.)
    """
    py = python_exe or sys.executable
    cmd = build_launch_command(py)            # [pythonw, '-m', module]
    target, arguments = cmd[0], " ".join(cmd[1:])
    lnk = desktop_dir() / f"{name}.lnk"
    script = build_shortcut_ps(lnk, target, arguments,
                               workdir=str(project_dir), icon=icon)
    proc = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True, text=True, creationflags=_NO_WINDOW,
    )
    return {"ok": proc.returncode == 0, "path": str(lnk),
            "returncode": proc.returncode,
            "stdout": proc.stdout, "stderr": proc.stderr}
