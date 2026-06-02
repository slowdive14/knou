"""keep_awake.py 순수 로직 단위테스트 (예약 실행 중 절전 억제 런처).

실제 절전 억제(SetThreadExecutionState)는 OS·전원 정책에 따라 달라 수동 검증.
여기서는 자식 명령 빌더 · 빈 인자 처리 · begin/end 가 어떤 환경에서도 예외 없이
호출되는지(비 Windows 포함)만 테스트한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from keep_awake import (  # noqa: E402
    ES_CONTINUOUS,
    ES_SYSTEM_REQUIRED,
    begin_keep_awake,
    build_child_command,
    end_keep_awake,
    run,
)


# --- 플래그 상수 -----------------------------------------------------------
def test_flags_have_expected_values():
    # Win32 문서값과 일치해야 시스템 절전 억제가 동작한다.
    assert ES_CONTINUOUS == 0x80000000
    assert ES_SYSTEM_REQUIRED == 0x00000001


# --- build_child_command ---------------------------------------------------
def test_build_child_command_uses_dash_u_and_default_python():
    cmd = build_child_command(["main.py", "--mode", "요약"])
    assert cmd[0] == sys.executable      # 같은 venv python 으로 자식 실행
    assert cmd[1] == "-u"                # 버퍼링 없이 즉시 로그
    assert cmd[2] == "main.py"
    assert cmd[-2:] == ["--mode", "요약"]


def test_build_child_command_respects_explicit_python():
    cmd = build_child_command(["main.py"], python="C:/venv/python.exe")
    assert cmd[0] == "C:/venv/python.exe"


def test_build_child_command_preorder_script_then_args():
    cmd = build_child_command(["main.py", "--seq", "13"])
    assert cmd.index("main.py") < cmd.index("--seq")


# --- begin/end (어떤 환경에서도 예외 없이) ---------------------------------
def test_begin_and_end_keep_awake_never_raise():
    # Windows 면 실제 API 호출(즉시 end 로 해제), 그 외엔 조용히 False.
    result = begin_keep_awake()
    assert isinstance(result, bool)
    end_keep_awake()                     # 예외 없으면 통과


# --- run 인자 검증 ---------------------------------------------------------
def test_run_with_empty_args_returns_error_code():
    # 실행할 스크립트가 없으면 자식을 띄우지 않고 오류 코드 반환.
    assert run([]) == 2
