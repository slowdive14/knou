"""강의 목록 스냅샷 단위테스트 — 실행이 끝나면 목록이 저절로 최신이 되는가.

실측 불편: 이수를 다 끝냈는데도 차시 목록에 ✅ 가 안 붙어, 사람이 [목록
새로고침]을 눌러야 했다. main.run() 은 이미 매 실행마다 LMS 에서 전 과목 차시를
받아오므로, 끝날 때 한 번 더 받아 저장하면 새 로그인 없이 목록이 최신이 된다.

`runner.parse_lectures_snapshot` 이 읽는 형식과 어긋나면 앱이 목록을 못 읽으므로
왕복(저장 → 다시 읽기)으로 검증한다.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import parse_lectures_snapshot  # noqa: E402
from snapshot import (  # noqa: E402
    build_snapshot,
    lecture_entry,
    refresh_snapshot,
    save_snapshot,
    snapshot_counts,
)


class _Lec:
    def __init__(self, seq, name, video_done=False, exam_done=False,
                 watched_min=0, total_min=50):
        self.seq, self.name = seq, name
        self.video_done, self.exam_done = video_done, exam_done
        self.has_video = True
        self.watched_min, self.total_min = watched_min, total_min


class _Course:
    def __init__(self, name, sbjt_id="S1"):
        self.name, self.sbjt_id = name, sbjt_id


PAIRS = [(_Course("컴퓨터구조"),
          [_Lec(1, "개요", video_done=True, watched_min=50),
           _Lec(2, "논리회로")])]


# --- 형식(순수) ------------------------------------------------------------
def test_lecture_entry_carries_completion():
    e = lecture_entry(_Lec(3, "명령어", video_done=True, exam_done=True))
    assert e["seq"] == 3 and e["name"] == "명령어"
    assert e["video_done"] is True and e["exam_done"] is True


def test_lecture_entry_defaults_are_safe():
    class _Bare:
        seq, name = 1, "x"

    e = lecture_entry(_Bare())
    assert e["video_done"] is False and e["total_min"] == 0


def test_build_snapshot_keeps_course_order_and_stamp():
    snap = build_snapshot(PAIRS, now=datetime(2026, 8, 27, 9, 30, 0))
    assert snap["generated_at"] == "2026-08-27T09:30:00"
    assert [c["name"] for c in snap["courses"]] == ["컴퓨터구조"]
    assert len(snap["courses"][0]["lectures"]) == 2


def test_snapshot_counts():
    assert snapshot_counts(build_snapshot(PAIRS)) == (1, 2)


def test_snapshot_counts_empty():
    assert snapshot_counts({}) == (0, 0)


# --- 앱이 읽는 형식과 맞는가(왕복) -------------------------------------------
def test_saved_snapshot_is_readable_by_the_app(tmp_path):
    p = save_snapshot(build_snapshot(PAIRS), tmp_path / "lectures.json")
    rows = parse_lectures_snapshot(p.read_text(encoding="utf-8"))
    assert [(r.course, r.seq, r.video_done) for r in rows] == [
        ("컴퓨터구조", 1, True), ("컴퓨터구조", 2, False)]


def test_saved_snapshot_keeps_korean_readable(tmp_path):
    p = save_snapshot(build_snapshot(PAIRS), tmp_path / "l.json")
    assert "컴퓨터구조" in p.read_text(encoding="utf-8")   # \uXXXX 로 깨지지 않게


def test_saved_snapshot_has_no_secrets(tmp_path):
    p = save_snapshot(build_snapshot(PAIRS), tmp_path / "l.json")
    text = p.read_text(encoding="utf-8")
    assert "KNOU_PW" not in text and "GEMINI_API_KEY" not in text
    assert "hlsUrl" not in text and "token" not in text


# --- refresh_snapshot(열린 세션으로 갱신) -------------------------------------
class _Page:
    """goto 만 받아 적는 가짜 page — 어디로 되돌아갔는지 확인하기 위함."""

    def __init__(self):
        self.visited = []

    def goto(self, url, **kw):
        self.visited.append(url)


def _patch_discover(monkeypatch, courses, fetch):
    import discover
    monkeypatch.setattr(discover, "list_courses", lambda page: courses)
    monkeypatch.setattr(discover, "fetch_lectures", fetch)


def test_refresh_writes_current_state(monkeypatch, tmp_path):
    # 이수를 마친 뒤 다시 받은 목록 = video_done True 가 저장돼야 한다
    _patch_discover(monkeypatch, [_Course("컴퓨터구조")],
                    lambda page, c: [_Lec(1, "개요", video_done=True)])
    out = tmp_path / "lectures.json"
    snap = refresh_snapshot(_Page(), out)
    assert snap is not None
    saved = json.loads(out.read_text(encoding="utf-8"))
    assert saved["courses"][0]["lectures"][0]["video_done"] is True


def test_refresh_isolates_one_bad_course(monkeypatch, tmp_path):
    ok, bad = _Course("좋은과목"), _Course("깨진과목")

    def _fetch(page, c):
        if c is bad:
            raise RuntimeError("조회 실패")
        return [_Lec(1, "개요")]

    _patch_discover(monkeypatch, [ok, bad], _fetch)
    out = tmp_path / "l.json"
    snap = refresh_snapshot(_Page(), out)
    assert [c["name"] for c in snap["courses"]] == ["좋은과목"]


def test_refresh_never_raises(monkeypatch, tmp_path):
    # 갱신 실패가 이미 끝난 실행을 망치면 안 된다
    import discover

    def _boom(page):
        raise RuntimeError("세션 끊김")

    monkeypatch.setattr(discover, "list_courses", _boom)
    assert refresh_snapshot(_Page(), tmp_path / "l.json") is None


def test_refresh_does_not_write_empty_snapshot(monkeypatch, tmp_path):
    # 아무 과목도 못 받았으면 멀쩡한 기존 목록을 빈 것으로 덮지 않는다
    _patch_discover(monkeypatch, [], lambda page, c: [])
    out = tmp_path / "l.json"
    out.write_text('{"courses":[{"name":"기존","lectures":[]}]}',
                   encoding="utf-8")
    assert refresh_snapshot(_Page(), out) is None
    assert "기존" in out.read_text(encoding="utf-8")


def test_refresh_without_cfg_only_navigates(monkeypatch, tmp_path):
    """cfg 가 없으면 이동만 시도한다(하위 호환)."""
    from auth import MY_STUDY_URL

    _patch_discover(monkeypatch, [_Course("컴퓨터구조")],
                    lambda page, c: [_Lec(1, "개요")])
    page = _Page()
    refresh_snapshot(page, tmp_path / "l.json")
    assert page.visited == [MY_STUDY_URL]


def test_refresh_restores_the_login_when_cfg_given(monkeypatch, tmp_path):
    """세션을 다시 확보해야 목록을 읽을 수 있다.

    실측: 주소만 '나의 학습'으로 되돌리면 URL 은 맞는데 화면은 통합로그인이었다.
    방송대는 단일 세션이라 자료실을 다녀오는 사이 세션이 끊기기 때문이다.
    """
    import auth
    seen = []
    monkeypatch.setattr(auth, "ensure_logged_in",
                        lambda page, cfg, **kw: seen.append("login") or True)
    _patch_discover(monkeypatch, [_Course("컴퓨터구조")],
                    lambda page, c: [_Lec(1, "개요")])
    page = _Page()
    snap = refresh_snapshot(page, tmp_path / "l.json", cfg=object())
    assert seen == ["login"]
    assert page.visited == []              # 이동은 ensure_logged_in 이 맡는다
    assert snap is not None


def test_refresh_survives_a_failed_login(monkeypatch, tmp_path):
    import auth

    def _boom(page, cfg, **kw):
        raise RuntimeError("로그인 실패")

    monkeypatch.setattr(auth, "ensure_logged_in", _boom)
    _patch_discover(monkeypatch, [_Course("컴퓨터구조")],
                    lambda page, c: [_Lec(1, "개요")])
    assert refresh_snapshot(_Page(), tmp_path / "l.json", cfg=object()) is None


def test_refresh_survives_a_failed_navigation(monkeypatch, tmp_path):
    class _DeadPage:
        def goto(self, url, **kw):
            raise RuntimeError("세션 끊김")

    _patch_discover(monkeypatch, [_Course("컴퓨터구조")],
                    lambda page, c: [_Lec(1, "개요")])
    assert refresh_snapshot(_DeadPage(), tmp_path / "l.json") is None
