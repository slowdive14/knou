"""예약 '한 번에 최대 N강' + '지금 멈추기' 단위테스트.

배경(실측): 컴퓨터구조 15강이 전부 미이수인 상태로 매일 02:00 '전체' 예약을 걸면
영상만 932분 → 한 번 시작하면 12시간 넘게 이어진다. 게다가 예전 VBS 런처가
`sh.Run(.., 0, False)` 로 **기다리지 않고** 끝나 버려서:
  - 작업은 1초 만에 '완료'가 되고 파이썬만 떨어져 나가 계속 돌고
  - '끄기'(/DISABLE)는 다음 실행만 막아 도는 것을 못 세우고
  - schtasks /End 도 멈출 대상을 못 찾았다
그래서 (1) 실행량을 미리 자르는 limit, (2) 진짜로 세우는 /End 를 넣었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schedule_win as sw  # noqa: E402
from schedule_win import (  # noqa: E402
    build_run_script,
    build_schtasks_end_args,
    create_task,
    parse_limit,
    valid_limit,
)


# --- 입력 검증(순수) --------------------------------------------------------
def test_valid_limit_accepts_positive_and_blank():
    assert valid_limit("3") and valid_limit("15")
    assert valid_limit("") and valid_limit(None)      # 비우면 '전부'


def test_valid_limit_rejects_zero_and_junk():
    assert not valid_limit("0")
    assert not valid_limit("-2")
    assert not valid_limit("세 개")
    assert not valid_limit("2.5")


def test_parse_limit_maps_blank_to_none():
    assert parse_limit("3") == 3
    assert parse_limit("") is None
    assert parse_limit("0") is None
    assert parse_limit("abc") is None


# --- .bat 에 --limit 이 실린다 ---------------------------------------------
def test_run_script_carries_limit():
    s = build_run_script("py.exe", r"C:\proj", "전체", course="컴퓨터구조",
                         unwatched=True, limit=3)
    assert "--limit 3" in s
    assert "--unwatched" in s


def test_run_script_without_limit_has_no_flag():
    s = build_run_script("py.exe", r"C:\proj", "전체", course="컴퓨터구조",
                         unwatched=True)
    assert "--limit" not in s


# --- create_task 가 limit 을 .bat 까지 전달한다 ------------------------------
class _FakeProc:
    returncode = 0
    stdout = ""
    stderr = ""


def _make(monkeypatch, tmp_path, **kwargs):
    monkeypatch.setattr(sw, "_run_schtasks", lambda argv: _FakeProc())
    create_task("py.exe", str(tmp_path), "전체", "02:00",
                course="컴퓨터구조", unwatched=True,
                scripts_dir=tmp_path, **kwargs)
    bats = list(Path(tmp_path).glob("*.bat"))
    assert len(bats) == 1
    return bats[0].read_text(encoding="utf-8")


def test_create_task_writes_limit_into_bat(monkeypatch, tmp_path):
    assert "--limit 3" in _make(monkeypatch, tmp_path, limit=3)


def test_create_task_default_has_no_limit(monkeypatch, tmp_path):
    assert "--limit" not in _make(monkeypatch, tmp_path)


def test_bat_still_has_no_secrets(monkeypatch, tmp_path):
    bat = _make(monkeypatch, tmp_path, limit=2)
    assert "KNOU_PW" not in bat and "GEMINI_API_KEY" not in bat


# --- 지금 멈추기(/End) ------------------------------------------------------
def test_end_args_use_end_not_disable():
    argv = build_schtasks_end_args("KNOU_전체")
    assert argv == ["schtasks", "/End", "/TN", "KNOU_전체"]
    # /DISABLE(끄기)과 절대 섞이면 안 된다 — 그건 다음 실행만 막는다
    assert "/DISABLE" not in argv and "/Change" not in argv


def test_end_task_reports_success(monkeypatch):
    monkeypatch.setattr(sw, "_run_schtasks", lambda argv: _FakeProc())
    assert sw.end_task("KNOU_전체")["ok"] is True


def test_end_task_reports_failure_when_not_running(monkeypatch):
    class _Bad(_FakeProc):
        returncode = 1
        stderr = "ERROR: 실행 중인 인스턴스가 없습니다."

    monkeypatch.setattr(sw, "_run_schtasks", lambda argv: _Bad())
    res = sw.end_task("KNOU_전체")
    assert res["ok"] is False and "인스턴스" in res["stderr"]


def test_disable_and_end_are_different_commands():
    from schedule_win import build_schtasks_change_args
    assert build_schtasks_end_args("T") != build_schtasks_change_args("T", False)
