"""study_plan 단위테스트 — 목표일까지 모든 강의를 한 번은 보려면.

차질이 생기면 남은 강의를 남은 날로 다시 나누기만 하면 된다. 하루치가
늘어나는 것을 눈으로 보는 것이 이 화면의 전부다.
"""
from __future__ import annotations

import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import study_plan as sp  # noqa: E402

COURSES = [{"course": "자료구조", "total": 15},
           {"course": "C프로그래밍", "total": 15}]
TODAY = date(2026, 9, 29)
GOAL = "2026-11-16"


def _plan(**over):
    p = {"goal": GOAL, "start": "2026-09-07", "courses": COURSES,
         "watched": {"자료구조": {"1": "2026-09-07", "2": "2026-09-13"},
                     "C프로그래밍": {"1": "2026-09-08"}}}
    p.update(over)
    return p


# --- 무엇을 봤는가 ----------------------------------------------------------
def test_the_watched_numbers_come_back_in_order():
    assert sp.watched_nos(_plan(), "자료구조") == [1, 2]
    assert sp.watched_nos(_plan(), "없는과목") == []


def test_a_broken_record_does_not_break_the_screen():
    """계획 파일은 손으로 고칠 수 있다 — 엉뚱한 값이 들어와도 열려야 한다."""
    assert sp.watched_nos({"watched": {"자료구조": "1강"}}, "자료구조") == []
    assert sp.watched_nos({"watched": {"자료구조": {"첫째": 1}}}, "자료구조") == []
    assert sp.watched_nos(None, "자료구조") == []


def test_each_course_reports_what_is_left():
    rows = sp.course_rows(_plan())
    assert [r["course"] for r in rows] == ["자료구조", "C프로그래밍"]
    assert rows[0]["done"] == 2 and rows[0]["left"] == 13
    assert rows[1]["done"] == 1 and rows[1]["left"] == 14


def test_the_course_order_of_the_plan_is_kept():
    """화면이 흔들리지 않으려면 순서가 그대로여야 한다."""
    p = _plan(courses=[{"course": "C프로그래밍", "total": 15},
                       {"course": "자료구조", "total": 15}])
    assert [r["course"] for r in sp.course_rows(p)] == ["C프로그래밍", "자료구조"]


def test_a_number_past_the_last_lecture_is_not_counted():
    """15강짜리 과목에 20강 기록이 있으면 진도가 아니다."""
    p = _plan(watched={"자료구조": {"20": "2026-09-07"}})
    assert sp.course_rows(p)[0]["done"] == 0


def test_the_totals_add_the_courses_up():
    t = sp.totals(_plan())
    assert t == {"total": 30, "done": 3, "left": 27, "pct": 10}


def test_an_empty_plan_totals_to_nothing():
    assert sp.totals({})["total"] == 0
    assert sp.totals(None)["pct"] == 0


# --- 남은 날 ----------------------------------------------------------------
def test_today_counts_as_a_day_you_can_still_study():
    """오늘을 빼면 하루치가 부풀어 겁만 준다."""
    assert sp.days_left("2026-11-16", date(2026, 11, 16)) == 1
    assert sp.days_left("2026-11-16", date(2026, 11, 15)) == 2
    assert sp.days_left(GOAL, TODAY) == 49


def test_a_passed_deadline_leaves_no_days():
    assert sp.days_left("2026-11-16", date(2026, 11, 17)) == 0
    assert sp.days_left("엉뚱한날", TODAY) == 0


# --- 한 주에 몇 강 -----------------------------------------------------------
# 강의는 쪼갤 수 없다. '하루 0.3강' 은 현실에 없는 단위라 계획을 세울 수 없다.
def test_the_weekly_goal_is_a_whole_number():
    assert sp.weekly_goal(64, 49) == 10          # 9.14 → 모자라지 않게 올린다
    assert sp.weekly_goal(14, 49) == 2
    assert sp.weekly_goal(27, 49) == 4


def test_the_weekly_goal_never_asks_for_more_than_is_left():
    """3강 남았는데 '주 7강' 이라고 하면 말이 안 된다."""
    assert sp.weekly_goal(3, 2) == 3


def test_nothing_left_asks_for_nothing():
    assert sp.weekly_goal(0, 49) == 0


def test_with_no_days_left_everything_is_due_now():
    assert sp.weekly_goal(5, 0) == 5


def test_the_day_text_gives_a_whole_range():
    """64강을 49일에 나누면 하루 1강 듣는 날과 2강 듣는 날이 섞인다."""
    assert sp.day_text(64, 49) == "하루 1~2강"
    assert sp.day_text(98, 49) == "하루 2강"      # 꼭 떨어지면 범위가 없다
    assert sp.day_text(49, 49) == "하루 1강"


# --- 계획보다 앞섰나 뒤처졌나 ------------------------------------------------
def test_the_expected_amount_grows_evenly():
    """시작일에는 첫날치만, 목표일에는 전부다."""
    p = _plan()
    assert sp.expected_done(p, date(2026, 11, 16)) == 30.0
    assert sp.expected_done(p, date(2026, 9, 6)) == 0.0       # 시작 전
    mid = sp.expected_done(p, TODAY)
    assert 0 < mid < 30


def test_being_behind_is_a_negative_drift():
    assert sp.drift(_plan(), TODAY) < 0
    assert "뒤처졌습니다" in sp.drift_text(_plan(), TODAY)


def test_being_ahead_is_said_so():
    p = _plan(watched={"자료구조": {str(n): "2026-09-07" for n in range(1, 16)},
                       "C프로그래밍": {str(n): "2026-09-08"
                                  for n in range(1, 11)}})
    assert sp.drift(p, TODAY) > 0
    assert "앞섰습니다" in sp.drift_text(p, TODAY)


def test_finishing_everything_stops_the_nagging():
    """다 본 사람에게 '뒤처졌다' 고 말하면 안 된다."""
    p = _plan(watched={c["course"]: {str(n): "2026-09-07"
                                     for n in range(1, 16)}
                       for c in COURSES})
    assert sp.drift_text(p, TODAY) == ""
    assert sp.pace_text(p, TODAY) == "모든 강의를 한 번씩 봤습니다"


# --- 머리말 -----------------------------------------------------------------
def test_the_status_line_says_the_days_the_count_and_the_pace():
    line = sp.status_line(_plan(), TODAY)
    assert "D-49" in line
    assert "3 / 30강(10%)" in line
    assert "주 4강" in line


def test_a_pace_under_one_a_day_is_told_by_the_week_only():
    """'하루 0~1강' 이라고 적으면 읽을 것이 없다."""
    assert sp.pace_text(_plan(), TODAY) == "주 4강"


def test_a_heavy_pace_names_both():
    """남은 강의가 남은 날보다 많아지면 하루치도 함께 말한다."""
    assert sp.pace_text(_plan(), date(2026, 11, 1)) == "하루 1~2강 · 주 12강"


def test_the_last_week_is_counted_in_days():
    """마지막 한 주가 남으면 주 단위가 뜻을 잃는다."""
    assert sp.pace_text(_plan(), date(2026, 11, 12)) == "남은 5일에 27강"


def test_a_lecture_count_is_always_a_whole_number():
    """0.3강짜리 강의는 없다."""
    assert sp.num_text(1.0) == "1"
    assert sp.num_text(13.3) == "13"
    assert sp.num_text(0) == "0"


def test_a_passed_deadline_is_said_plainly():
    assert "목표일이 지났습니다" in sp.status_line(_plan(), date(2026, 11, 20))


# --- 어디부터 손댈까 --------------------------------------------------------
def test_the_course_with_the_most_left_is_named():
    assert sp.worst_course(_plan(), TODAY) == "C프로그래밍"


def test_nothing_is_named_once_everything_is_done():
    p = _plan(watched={c["course"]: {str(n): "2026-09-07"
                                     for n in range(1, 16)}
                       for c in COURSES})
    assert sp.worst_course(p, TODAY) is None


# --- 눌러서 고치기 ----------------------------------------------------------
def test_pressing_an_unwatched_lecture_marks_it_with_today():
    p = sp.toggle(_plan(), "자료구조", 3, TODAY)
    assert sp.watched_nos(p, "자료구조") == [1, 2, 3]
    assert sp.watched_on(p, "자료구조", 3) == "2026-09-29"


def test_pressing_it_again_takes_it_back():
    """잘못 눌렀을 때 되돌릴 길이 있어야 한다."""
    p = sp.toggle(sp.toggle(_plan(), "자료구조", 3, TODAY),
                  "자료구조", 3, TODAY)
    assert sp.watched_nos(p, "자료구조") == [1, 2]


def test_toggling_does_not_touch_the_original():
    p = _plan()
    sp.toggle(p, "자료구조", 9, TODAY)
    assert sp.watched_nos(p, "자료구조") == [1, 2]


def test_a_course_with_nothing_left_drops_out_of_the_record():
    p = sp.toggle(_plan(), "C프로그래밍", 1, TODAY)
    assert "C프로그래밍" not in p["watched"]


# --- 밖에서 읽어 온 기록 합치기 ----------------------------------------------
def test_merging_fills_the_empty_places():
    p = sp.merge_watched(_plan(), {"컴퓨터구조": {"1": "2026-09-10"}})
    assert p["watched"]["컴퓨터구조"] == {"1": "2026-09-10"}
    assert sp.watched_nos(p, "자료구조") == [1, 2]      # 있던 것은 그대로


def test_merging_never_overwrites_what_is_already_there():
    """앱에서 손으로 눌러 둔 날짜를 카톡 기록이 덮으면 안 된다."""
    p = sp.merge_watched(_plan(), {"자료구조": {"1": "2026-01-01"}})
    assert sp.watched_on(p, "자료구조", 1) == "2026-09-07"


# --- 주별 -------------------------------------------------------------------
def test_the_weekly_bars_count_what_was_watched_each_week():
    # 9/13 은 일요일이라 9/7 주에 들어간다 — 주는 월요일에 시작한다.
    p = _plan(watched={"자료구조": {"1": "2026-09-07", "2": "2026-09-13",
                                "3": "2026-09-18"},
                       "C프로그래밍": {"1": "2026-09-28"}})
    got = sp.weekly(p, weeks=4, today=TODAY)
    assert [w["start"] for w in got] == ["2026-09-07", "2026-09-14",
                                         "2026-09-21", "2026-09-28"]
    assert [w["n"] for w in got] == [2, 1, 0, 1]


def test_a_quiet_week_shows_a_zero_rather_than_disappearing():
    """빈 주가 빠지면 쉬었다는 사실이 보이지 않는다."""
    got = sp.weekly(_plan(), 8, TODAY)
    assert all("n" in w for w in got)
    assert [w["start"] for w in got] == ["2026-09-07", "2026-09-14",
                                         "2026-09-21", "2026-09-28"]


def test_the_weeks_before_the_start_are_not_drawn():
    """학기 시작 전 빈 막대가 줄줄이 붙으면 최근 몇 주가 눈에 안 들어온다."""
    got = sp.weekly(_plan(), 8, TODAY)
    assert all(w["start"] >= "2026-09-07" for w in got)


def test_the_window_still_caps_at_the_asked_weeks():
    """학기가 길어져도 막대가 끝없이 늘어나지는 않는다."""
    p = _plan(start="2026-03-02")
    assert len(sp.weekly(p, 8, TODAY)) == 8


# --- 새 계획 세우기 ---------------------------------------------------------
def test_making_a_plan_from_course_names():
    p = sp.make_plan(["자료구조", "C프로그래밍"], GOAL, "2026-09-07")
    assert p["courses"] == COURSES
    assert p["goal"] == GOAL and p["start"] == "2026-09-07"
    assert p["watched"] == {}


def test_making_a_plan_keeps_a_given_lecture_count():
    p = sp.make_plan([{"course": "AI기초", "total": 13}], GOAL)
    assert p["courses"] == [{"course": "AI기초", "total": 13}]


# --- 저장 -------------------------------------------------------------------
def test_a_saved_plan_comes_back(tmp_path):
    f = tmp_path / "진도계획.json"
    sp.save_plan(f, _plan())
    assert sp.load_plan(f)["goal"] == GOAL


def test_a_missing_or_broken_file_is_an_empty_plan(tmp_path):
    assert sp.load_plan(tmp_path / "없다.json") == {}
    bad = tmp_path / "깨졌다.json"
    bad.write_text("{{{", encoding="utf-8")
    assert sp.load_plan(bad) == {}


def test_saving_leaves_no_half_written_file(tmp_path):
    f = tmp_path / "진도계획.json"
    sp.save_plan(f, _plan())
    assert not list(tmp_path.glob("*.tmp"))


# --- 과목 목록 가져오기 ------------------------------------------------------
def test_courses_come_from_the_lecture_list(tmp_path):
    f = tmp_path / "lectures.json"
    f.write_text(json.dumps({"courses": [
        {"name": "자료구조", "lectures": [{}] * 15},
        {"name": "AI기초", "lectures": [{}] * 13},
        {"name": "성폭력·가정폭력예방교육(학생용)", "lectures": []}]},
        ensure_ascii=False), encoding="utf-8")
    got = sp.courses_from_lectures(f)
    assert got == [{"course": "자료구조", "total": 15},
                   {"course": "AI기초", "total": 13}]


def test_a_course_can_be_left_out(tmp_path):
    f = tmp_path / "lectures.json"
    f.write_text(json.dumps({"courses": [
        {"name": "자료구조", "lectures": [{}] * 15},
        {"name": "AI기초", "lectures": [{}] * 13}]}, ensure_ascii=False),
        encoding="utf-8")
    got = sp.courses_from_lectures(f, skip=("AI기초",))
    assert [c["course"] for c in got] == ["자료구조"]


def test_a_missing_lecture_list_is_not_an_error(tmp_path):
    assert sp.courses_from_lectures(tmp_path / "없다.json") == []


# --- 오늘 몫 ----------------------------------------------------------------
# 트래커를 여는 이유가 이 한 줄이다 — 오늘 몇 강을 들어야 하는가.
def test_today_counts_only_what_was_watched_today():
    p = _plan(watched={"자료구조": {"1": "2026-09-29", "2": "2026-09-28"}})
    assert sp.today_done(p, TODAY) == 1


def test_nothing_watched_today_is_zero():
    assert sp.today_done(_plan(), TODAY) == 0


def test_this_week_counts_from_monday():
    """9/29 는 화요일이라 이번 주는 9/28 부터다."""
    p = _plan(watched={"자료구조": {"1": "2026-09-28", "2": "2026-09-29",
                                "3": "2026-09-27"}})
    assert sp.week_done(p, TODAY) == 2


def test_the_today_line_says_what_is_left_for_today():
    p = _plan(watched={"자료구조": {"1": "2026-09-29"}})
    assert sp.today_line(p, TODAY) == "오늘 1강 · 이번 주 1 / 5강"


def test_todays_count_carries_no_target():
    """하루치가 1.3강이면 오늘 목표가 1강인지 2강인지 말할 수 없다."""
    assert "오늘 0 /" not in sp.today_line(_plan(), TODAY)


def test_the_today_line_is_quiet_once_everything_is_done():
    p = _plan(watched={c["course"]: {str(n): "2026-09-07"
                                     for n in range(1, 16)}
                       for c in COURSES})
    assert sp.today_line(p, TODAY) == ""


def test_the_today_line_is_quiet_after_the_deadline():
    """목표일이 지나면 '오늘 몫' 이라는 말이 뜻을 잃는다."""
    assert sp.today_line(_plan(), date(2026, 11, 20)) == ""
