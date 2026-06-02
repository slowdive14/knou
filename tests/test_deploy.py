"""deploy.py 순수 로직 단위테스트 (Phase 5 — 비개발자 배포: 창 없는 실행·바로가기).

실제 .lnk 생성(PowerShell)은 수동 검증. 여기서는 pythonw 경로·실행 명령·
바로가기 PowerShell 스크립트 빌더·바탕화면 경로만 테스트한다.

⚠️ 어떤 빌더 결과에도 비밀번호·GEMINI_API_KEY 가 들어가지 않는지 확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from deploy import (  # noqa: E402
    APP_MODULE,
    build_launch_command,
    build_shortcut_ps,
    desktop_dir,
    pythonw_path,
)


# --- pythonw_path ----------------------------------------------------------
def test_pythonw_path_from_python_exe():
    out = pythonw_path(r"C:\proj\.venv\Scripts\python.exe")
    assert out.endswith("pythonw.exe")
    assert "Scripts" in out                # 같은 폴더 유지


def test_pythonw_path_idempotent_when_already_pythonw():
    out = pythonw_path(r"C:\proj\.venv\Scripts\pythonw.exe")
    assert out.endswith("pythonw.exe")
    assert "pythonww" not in out           # 두 번 붙지 않음


# --- build_launch_command --------------------------------------------------
def test_build_launch_command_uses_pythonw_and_module():
    cmd = build_launch_command(r"C:\proj\.venv\Scripts\python.exe")
    assert cmd[0].endswith("pythonw.exe")  # 콘솔 없는 실행
    assert cmd[1] == "-m"
    assert cmd[2] == APP_MODULE == "app.main_app"


# --- build_shortcut_ps -----------------------------------------------------
def test_build_shortcut_ps_has_target_args_workdir():
    ps = build_shortcut_ps(r"C:\Users\u\Desktop\KNOU.lnk",
                           r"C:\proj\.venv\Scripts\pythonw.exe",
                           arguments="-m app.main_app",
                           workdir=r"C:\proj")
    assert "WScript.Shell" in ps
    assert "CreateShortcut" in ps
    assert ".Save()" in ps
    assert "KNOU.lnk" in ps
    assert "pythonw.exe" in ps
    assert "-m app.main_app" in ps
    assert "$s.WorkingDirectory" in ps


def test_build_shortcut_ps_escapes_single_quotes():
    # 경로에 작은따옴표가 있어도 PowerShell 리터럴이 깨지지 않게 '' 로 이스케이프.
    ps = build_shortcut_ps(r"C:\it's\KNOU.lnk", r"C:\py\pythonw.exe")
    assert "it''s" in ps


def test_build_shortcut_ps_optional_parts_omitted():
    ps = build_shortcut_ps(r"C:\x\KNOU.lnk", r"C:\py\pythonw.exe")
    assert "$s.Arguments" not in ps        # arguments 비면 생략
    assert "$s.IconLocation" not in ps     # icon 없으면 생략


def test_build_shortcut_ps_never_contains_secrets():
    ps = build_shortcut_ps(r"C:\x\KNOU.lnk", r"C:\py\pythonw.exe",
                           arguments="-m app.main_app", workdir=r"C:\proj")
    assert "KNOU_PW" not in ps
    assert "GEMINI_API_KEY" not in ps
    assert "--password" not in ps


# --- desktop_dir -----------------------------------------------------------
def test_desktop_dir_is_under_home():
    d = desktop_dir()
    assert isinstance(d, Path)
    assert "Desktop" in str(d)
    assert str(Path.home()) in str(d)
