"""진도 트래커 화면 — 목표일까지 남은 강의를 눈으로 본다.

LMS 의 이수는 프로그램이 영상을 돌려 채운 것이라, 실제로 본 강의는 따로
세야 한다. 강 번호를 눌러 표시하고, 차질이 생기면 하루치가 다시 나뉜다.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

import study_plan as sp  # noqa: E402
from app.views.plan_view import (  # noqa: E402
    CELL, bar_height, build_plan_view, course_line, drift_tone, idle_tone,
    last_line, next_badge, short_date, week_label)

TODAY = date(2026, 9, 29)
GOAL = "2026-11-16"
COURSES = [{"course": "자료구조", "total": 15},
           {"course": "C프로그래밍", "total": 15}]


def _plan_file(tmp_path, **over):
    p = {"goal": GOAL, "start": "2026-09-07", "courses": COURSES,
         "watched": {"자료구조": {"1": "2026-09-07", "2": "2026-09-13"}}}
    p.update(over)
    f = tmp_path / "진도계획.json"
    f.write_text(json.dumps(p, ensure_ascii=False), encoding="utf-8")
    return f


def _snapshot(tmp_path):
    f = tmp_path / "lectures.json"
    f.write_text(json.dumps({"courses": [
        {"name": "자료구조", "lectures": [{}] * 15},
        {"name": "C프로그래밍", "lectures": [{}] * 15},
        {"name": "AI네이티브가되기위한기초소양", "lectures": [{}] * 13},
        {"name": "성폭력·가정폭력예방교육(학생용)", "lectures": []}]},
        ensure_ascii=False), encoding="utf-8")
    return f


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _texts(view) -> list:
    return [str(t.value or "") for t in _walk(view) if isinstance(t, ft.Text)]


def _cells(view) -> list:
    """강 번호 칸들 — 누를 수 있는 작은 네모."""
    return [c for c in _walk(view) if isinstance(c, ft.Container)
            and c.width == CELL and getattr(c, "on_click", None)]


def _cards(view) -> list:
    """과목 카드들의 과목 이름 — 화면에 늘어선 순서대로."""
    names = [c["course"] for c in COURSES]
    out = []
    for c in _walk(view):
        if isinstance(c, ft.Container) and isinstance(c.content, ft.Column) \
                and _cells(c.content):
            got = [t for t in _texts(c) if t in names]
            if got:
                out.append((got[0], c))
    return out


def _card(view, course):
    for name, c in _cards(view):
        if name == course:
            return c
    raise AssertionError(f"'{course}' 카드가 없습니다")


def _cells_of(view, course) -> list:
    """그 과목 카드의 강 번호 칸 — 1강부터."""
    return _cells(_card(view, course))


def _filled(view) -> list:
    """채워진 칸(=본 강의)의 번호."""
    return [str(c.content.value) for c in _cells(view) if c.bgcolor]


def _button(view, label):
    for b in _walk(view):
        if isinstance(b, ft.TextButton) and str(b.content) == label:
            return b
    raise AssertionError(f"[{label}] 단추가 없습니다")


def _field(view, label):
    for f in _walk(view):
        if isinstance(f, ft.TextField) and f.label == label:
            return f
    raise AssertionError(f"'{label}' 입력창이 없습니다")


def _head(view) -> str:
    return next(t for t in _texts(view) if t.startswith("D-")
                or "목표일이 지났습니다" in t)


# --- 아직 과목이 없을 때 ----------------------------------------------------
def test_an_empty_tracker_says_how_to_start(tmp_path):
    v = build_plan_view(plan_path=tmp_path / "없다.json", today=TODAY)
    assert any("과목 불러오기" in t for t in _texts(v))


def test_loading_courses_takes_them_from_the_lecture_list(tmp_path):
    f = tmp_path / "진도계획.json"
    v = build_plan_view(plan_path=f, today=TODAY,
                        snapshot_path=_snapshot(tmp_path))
    _button(v, "과목 불러오기").on_click(None)
    got = [c["course"] for c in sp.load_plan(f)["courses"]]
    assert got == ["자료구조", "C프로그래밍"]


def test_the_courses_that_do_not_belong_are_left_out(tmp_path):
    """필수 교육과 이미 다 이수한 AI네이티브는 '한 번은 본다' 의 대상이 아니다."""
    f = tmp_path / "진도계획.json"
    v = build_plan_view(plan_path=f, today=TODAY,
                        snapshot_path=_snapshot(tmp_path))
    _button(v, "과목 불러오기").on_click(None)
    names = [c["course"] for c in sp.load_plan(f)["courses"]]
    assert "AI네이티브가되기위한기초소양" not in names
    assert "성폭력·가정폭력예방교육(학생용)" not in names


def test_loading_without_a_lecture_list_says_so(tmp_path):
    v = build_plan_view(plan_path=tmp_path / "진도계획.json", today=TODAY,
                        snapshot_path=tmp_path / "없다.json")
    _button(v, "과목 불러오기").on_click(None)
    assert any("lectures.json" in t for t in _texts(v))


# --- 강 번호 칸 -------------------------------------------------------------
def test_every_lecture_gets_a_cell(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert len(_cells(v)) == 30              # 15강짜리 두 과목


def test_the_watched_lectures_are_filled_in(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert _filled(v) == ["1", "2"]


def test_pressing_a_cell_marks_it_and_saves(tmp_path):
    f = _plan_file(tmp_path)
    v = build_plan_view(plan_path=f, today=TODAY)
    _cells_of(v, "자료구조")[2].on_click(None)  # 3강
    assert _filled(v) == ["1", "2", "3"]
    assert sp.watched_on(sp.load_plan(f), "자료구조", 3) == "2026-09-29"


def test_pressing_it_again_takes_it_back(tmp_path):
    """잘못 눌렀을 때 되돌릴 길이 있어야 한다."""
    f = _plan_file(tmp_path)
    v = build_plan_view(plan_path=f, today=TODAY)
    _cells_of(v, "자료구조")[2].on_click(None)  # 3강을 표시했다가
    _cells_of(v, "자료구조")[2].on_click(None)  # 다시 눌러 뺀다
    assert _filled(v) == ["1", "2"]
    assert sp.watched_nos(sp.load_plan(f), "자료구조") == [1, 2]


def test_a_lecture_marked_by_mistake_can_be_unmarked(tmp_path):
    """이미 본 것으로 돼 있는 강도 눌러서 뺄 수 있어야 한다."""
    f = _plan_file(tmp_path)
    v = build_plan_view(plan_path=f, today=TODAY)
    _cells_of(v, "자료구조")[0].on_click(None)  # 1강
    assert _filled(v) == ["2"]
    assert sp.watched_nos(sp.load_plan(f), "자료구조") == [2]


def test_a_cell_says_when_it_was_watched(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert "2026-09-07" in str(_cells_of(v, "자료구조")[0].tooltip)
    assert "아직 안 봤습니다" in str(_cells_of(v, "자료구조")[5].tooltip)


# --- 머리말 -----------------------------------------------------------------
def test_the_headline_says_the_days_and_the_weekly_share(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    head = _head(v)
    assert "D-49" in head
    assert "2 / 30강" in head
    assert "주 4강" in head


def test_the_headline_moves_when_a_lecture_is_marked(tmp_path):
    """한 강 볼 때마다 하루치가 줄어드는 것이 보여야 한다."""
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    before = _head(v)
    _cells_of(v, "자료구조")[2].on_click(None)
    assert _head(v) != before
    assert "3 / 30강" in _head(v)


def test_the_screen_says_todays_share(tmp_path):
    """트래커를 여는 이유가 이 한 줄이다."""
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert any(t.startswith("오늘 0강 · 이번 주") for t in _texts(v))


def test_todays_share_moves_when_a_lecture_is_marked(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    _cells_of(v, "자료구조")[2].on_click(None)
    assert any(t.startswith("오늘 1강 · 이번 주 1 /") for t in _texts(v))


def test_being_behind_names_the_course_to_start_with(tmp_path):
    """뒤처졌다고만 하면 막막하다 — 어디부터 손댈지 함께 말한다."""
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    said = " ".join(_texts(v))
    assert "뒤처졌습니다" in said
    assert "C프로그래밍부터 손대세요" in said


# --- 오래 손 놓은 과목부터 --------------------------------------------------
def _order(view) -> list:
    return [name for name, _c in _cards(view)]


def test_the_course_left_alone_longest_comes_first(tmp_path):
    """계획에 적힌 순서가 아니라 마지막으로 본 날이 오래된 과목이 위로 온다."""
    f = _plan_file(tmp_path, watched={
        "자료구조": {"1": "2026-09-07", "2": "2026-09-25"},
        "C프로그래밍": {"1": "2026-09-10"}})
    v = build_plan_view(plan_path=f, today=TODAY)
    assert _order(v) == ["C프로그래밍", "자료구조"]


def test_a_course_never_watched_comes_first(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert _order(v) == ["C프로그래밍", "자료구조"]


def test_each_card_says_when_it_was_last_certified(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert "최근 인증 9/13(일) · 16일 전" in _texts(_card(v, "자료구조"))
    assert "아직 인증이 없습니다" in _texts(_card(v, "C프로그래밍"))


def test_the_first_card_is_marked_as_next(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert "다음 차례 · 1강" in _texts(_card(v, "C프로그래밍"))
    assert not any(t.startswith("다음 차례") for t in
                   _texts(_card(v, "자료구조")))


def test_marking_a_lecture_does_not_move_the_cards(tmp_path):
    """누르자마자 카드가 맨 아래로 달아나면 잘못 누른 것을 되돌리기 어렵다."""
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    _cells_of(v, "C프로그래밍")[0].on_click(None)
    assert _order(v) == ["C프로그래밍", "자료구조"]
    assert "최근 인증 9/29(화) · 오늘" in _texts(_card(v, "C프로그래밍"))
    # '다음 차례' 표는 이제 자료구조로 옮겨 간다
    assert "다음 차례 · 3강" in _texts(_card(v, "자료구조"))


def test_reopening_the_screen_lines_the_cards_up_again(tmp_path):
    f = _plan_file(tmp_path)
    v = build_plan_view(plan_path=f, today=TODAY)
    _cells_of(v, "C프로그래밍")[0].on_click(None)
    again = build_plan_view(plan_path=f, today=TODAY)
    assert _order(again) == ["자료구조", "C프로그래밍"]


def test_a_finished_course_goes_last_without_a_date(tmp_path):
    """다 본 과목은 손을 놓아도 괜찮다 — 재촉하지 않는다."""
    f = _plan_file(tmp_path, watched={
        "자료구조": {str(n): "2026-09-07" for n in range(1, 16)},
        "C프로그래밍": {"1": "2026-09-28"}})
    v = build_plan_view(plan_path=f, today=TODAY)
    assert _order(v) == ["C프로그래밍", "자료구조"]
    assert not any(t.startswith("최근 인증") for t in
                   _texts(_card(v, "자료구조")))


def test_finishing_everything_stops_the_warning(tmp_path):
    done = {c["course"]: {str(n): "2026-09-07" for n in range(1, 16)}
            for c in COURSES}
    v = build_plan_view(plan_path=_plan_file(tmp_path, watched=done),
                        today=TODAY)
    said = " ".join(_texts(v))
    assert "뒤처졌습니다" not in said
    assert "모든 강의를 한 번씩 봤습니다" in said


# --- 목표일 -----------------------------------------------------------------
def test_the_goal_can_be_moved_and_the_share_is_shared_again(tmp_path):
    """일정이 밀리면 목표일을 미룬다 — 하루치가 저절로 다시 나뉜다."""
    f = _plan_file(tmp_path)
    v = build_plan_view(plan_path=f, today=TODAY)
    assert "주 4강" in _head(v)
    _field(v, "목표일").value = "2026-12-16"
    _button(v, "적용").on_click(None)
    assert sp.load_plan(f)["goal"] == "2026-12-16"
    assert "D-79" in _head(v)
    assert "주 3강" in _head(v)


def test_a_goal_that_is_not_a_date_is_refused(tmp_path):
    f = _plan_file(tmp_path)
    v = build_plan_view(plan_path=f, today=TODAY)
    _field(v, "목표일").value = "내년 봄쯤"
    _button(v, "적용").on_click(None)
    assert sp.load_plan(f)["goal"] == GOAL          # 그대로다
    assert any("적어 주세요" in t for t in _texts(v))


# --- 주별 막대 --------------------------------------------------------------
def test_the_weekly_bars_are_drawn(tmp_path):
    v = build_plan_view(plan_path=_plan_file(tmp_path), today=TODAY)
    assert any("주마다 몇 강" in t for t in _texts(v))
    assert any(week_label("2026-09-07") == t for t in _texts(v))


def test_a_week_with_one_lecture_is_still_visible():
    """0 과 1 이 똑같이 납작하면 쉰 주와 구분되지 않는다."""
    assert bar_height(0, 5) < bar_height(1, 5)
    assert bar_height(5, 5) > bar_height(1, 5)


def test_the_week_label_is_short():
    assert week_label("2026-09-07") == "9/7"
    assert week_label("2026-11-16") == "11/16"


# --- 조각들 -----------------------------------------------------------------
def test_the_course_line_names_what_is_left():
    """한 과목의 하루치는 늘 1강이 안 된다 — 주 단위로 말한다."""
    row = {"course": "자료구조", "total": 15, "done": 3, "left": 12}
    assert course_line(row, 49) == "3 / 15강 · 남은 12 · 주 2강"


def test_the_course_line_drops_the_week_in_the_last_days():
    row = {"course": "자료구조", "total": 15, "done": 3, "left": 12}
    assert course_line(row, 5) == "3 / 15강 · 남은 12"


def test_a_finished_course_is_congratulated():
    row = {"course": "자료구조", "total": 15, "done": 15, "left": 0}
    assert "다 봤습니다" in course_line(row, 49)


def test_the_tone_follows_how_far_off_the_plan_is():
    behind = {"goal": GOAL, "start": "2026-09-07", "courses": COURSES,
              "watched": {}}
    assert drift_tone(behind, TODAY) == "behind"
    done = {"goal": GOAL, "start": "2026-09-07", "courses": COURSES,
            "watched": {c["course"]: {str(n): "2026-09-07"
                                      for n in range(1, 16)}
                        for c in COURSES}}
    assert drift_tone(done, TODAY) == "done"


def test_a_date_carries_its_weekday():
    assert short_date("2026-09-13") == "9/13(일)"
    assert short_date("2026-09-28") == "9/28(월)"
    assert short_date("엉뚱한날") == ""


def test_the_last_line_says_how_long_ago():
    """날짜만 보면 오늘이 며칠인지 따져 봐야 한다."""
    assert last_line("2026-09-29", TODAY) == "최근 인증 9/29(화) · 오늘"
    assert last_line("2026-09-28", TODAY) == "최근 인증 9/28(월) · 어제"
    assert last_line("2026-09-13", TODAY) == "최근 인증 9/13(일) · 16일 전"
    assert last_line("", TODAY) == "아직 인증이 없습니다"


def test_the_longer_it_is_left_the_louder_the_color():
    assert idle_tone("2026-09-29", TODAY) == "fresh"
    assert idle_tone("2026-09-25", TODAY) == "ok"            # 4일
    assert idle_tone("2026-09-22", TODAY) == "warn"          # 7일
    assert idle_tone("2026-09-15", TODAY) == "alarm"         # 14일
    assert idle_tone("", TODAY) == "alarm"                   # 본 적이 없다


def test_the_badge_names_the_next_lecture():
    assert next_badge({"next": 4}) == "다음 차례 · 4강"
    assert next_badge({"next": None}) == "다음 차례"
