"""import_kakao 단위테스트 — 단톡방 인증을 진도 트래커에 심는다.

한 번 심고 나면 앱에서 강 번호를 눌러 가며 쓴다. 다시 심어도 이미 적혀 있는
날짜는 건드리지 않아야 한다(손으로 눌러 둔 것을 덮지 않게).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import import_kakao as ik  # noqa: E402
import study_plan as sp  # noqa: E402

LOG = """--------------- 2026년 9월 7일 월요일 ---------------
[잔향/복수전공/3학년] [오후 6:44] 자료구조 1강 들었습니다
--------------- 2026년 9월 8일 화요일 ---------------
[잔향/복수전공/3학년] [오후 9:22] C프로그래밍 1강 들었습니다
[빵/컴퓨터과학과/3학년] [오후 11:21] 컴퓨터구조 3강들었습니다
"""


def _files(tmp_path, log=LOG):
    """대화 파일 · 강의 목록 · 볼트를 한 벌 차려 놓는다."""
    chat = tmp_path / "대화.txt"
    chat.write_text(log, encoding="utf-8")
    snap = tmp_path / "lectures.json"
    snap.write_text(json.dumps({"courses": [
        {"name": "자료구조", "lectures": [{}] * 15},
        {"name": "C프로그래밍", "lectures": [{}] * 15},
        {"name": "AI네이티브가되기위한기초소양", "lectures": [{}] * 13}]},
        ensure_ascii=False), encoding="utf-8")
    return chat, snap


class _Cfg:
    def __init__(self, vault):
        self.summary_dir = Path(vault)


def _run(monkeypatch, tmp_path, chat, snap, *args):
    """명령을 돌리고 (돌아온 값, 저장된 계획) 을 준다."""
    vault = tmp_path / "볼트"
    monkeypatch.setattr(ik, "SNAPSHOT_PATH", snap)
    monkeypatch.setitem(sys.modules, "config", _FakeConfig(vault))
    code = ik.main(["--file", str(chat), "--nick", "잔향", *args])
    return code, sp.load_plan(vault / sp.PLAN_NAME)


class _FakeConfig:
    """config 모듈 흉내 — 볼트 경로만 돌려준다."""

    def __init__(self, vault):
        self._vault = vault

    def load_config(self):
        return _Cfg(self._vault)


# --- 대화 읽기 --------------------------------------------------------------
def test_a_utf8_log_is_read(tmp_path):
    f = tmp_path / "대화.txt"
    f.write_text("자료구조 1강", encoding="utf-8")
    assert "자료구조" in ik.read_log(f)


def test_a_cp949_log_is_read_too(tmp_path):
    """카톡이 내보낸 파일의 인코딩이 늘 같지는 않다."""
    f = tmp_path / "대화.txt"
    f.write_bytes("자료구조 1강".encode("cp949"))
    assert "자료구조" in ik.read_log(f)


# --- 심기 ------------------------------------------------------------------
def test_the_log_fills_the_plan(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    code, plan = _run(monkeypatch, tmp_path, chat, snap)
    assert code == 0
    assert sp.watched_nos(plan, "자료구조") == [1]
    assert sp.watched_nos(plan, "C프로그래밍") == [1]


def test_other_peoples_lectures_stay_out(tmp_path, monkeypatch):
    """빵님의 컴퓨터구조 3강은 내 진도가 아니다."""
    chat, snap = _files(tmp_path)
    _code, plan = _run(monkeypatch, tmp_path, chat, snap)
    assert not sp.watched_nos(plan, "컴퓨터구조")


def test_the_start_day_is_the_first_certification(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    _code, plan = _run(monkeypatch, tmp_path, chat, snap)
    assert plan["start"] == "2026-09-07"


def test_the_goal_can_be_given(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    _code, plan = _run(monkeypatch, tmp_path, chat, snap,
                       "--goal", "2026-12-20")
    assert plan["goal"] == "2026-12-20"


def test_the_courses_that_do_not_belong_are_left_out(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    _code, plan = _run(monkeypatch, tmp_path, chat, snap)
    names = [c["course"] for c in plan["courses"]]
    assert names == ["자료구조", "C프로그래밍"]


# --- 보기만 하기 ------------------------------------------------------------
def test_a_dry_run_writes_nothing(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    code, plan = _run(monkeypatch, tmp_path, chat, snap, "--dry")
    assert code == 0
    assert plan == {}


# --- 다시 심을 때 -----------------------------------------------------------
def test_running_it_twice_keeps_the_first_dates(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    _run(monkeypatch, tmp_path, chat, snap)
    _code, plan = _run(monkeypatch, tmp_path, chat, snap)
    assert sp.watched_on(plan, "자료구조", 1) == "2026-09-07"


def test_what_was_pressed_in_the_app_is_not_overwritten(tmp_path, monkeypatch):
    """앱에서 손으로 눌러 둔 강의를 카톡 기록이 지우면 안 된다."""
    chat, snap = _files(tmp_path)
    _run(monkeypatch, tmp_path, chat, snap)
    vault = tmp_path / "볼트"
    path = vault / sp.PLAN_NAME
    plan = sp.toggle(sp.load_plan(path), "자료구조", 9, "2026-09-25")
    sp.save_plan(path, plan)
    _code, got = _run(monkeypatch, tmp_path, chat, snap)
    assert sp.watched_nos(got, "자료구조") == [1, 9]


# --- 어긋난 입력 ------------------------------------------------------------
def test_a_wrong_nickname_is_told_apart(tmp_path, monkeypatch):
    chat, snap = _files(tmp_path)
    vault = tmp_path / "볼트"
    monkeypatch.setattr(ik, "SNAPSHOT_PATH", snap)
    monkeypatch.setitem(sys.modules, "config", _FakeConfig(vault))
    assert ik.main(["--file", str(chat), "--nick", "없는사람"]) == 1
    assert not (vault / sp.PLAN_NAME).exists()


def test_without_a_lecture_list_it_stops(tmp_path, monkeypatch):
    chat, _snap = _files(tmp_path)
    vault = tmp_path / "볼트"
    monkeypatch.setattr(ik, "SNAPSHOT_PATH", tmp_path / "없다.json")
    monkeypatch.setitem(sys.modules, "config", _FakeConfig(vault))
    assert ik.main(["--file", str(chat), "--nick", "잔향"]) == 1


# --- 보고문 ----------------------------------------------------------------
def test_the_report_says_what_came_in_and_what_did_not():
    plan = {"courses": [{"course": "자료구조", "total": 15},
                        {"course": "컴퓨터구조", "total": 15}],
            "watched": {"자료구조": {"1": "2026-09-07"}}}
    lines = ik.report({"자료구조": {"1": "2026-09-07"}}, plan, {})
    assert "자료구조 — 1/15강 (새로 1)" in lines[0]
    assert "대화에 없음" in lines[1]
