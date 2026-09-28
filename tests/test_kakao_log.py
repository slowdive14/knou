"""kakao_log 단위테스트 — 단톡방 인증이 곧 실제로 본 강의다.

LMS 의 이수는 이 프로그램이 영상을 돌려 채운 것이라 다르다. '자료구조 1강
들었습니다' 하고 올린 기록만이 내가 진짜 본 강의를 말해 준다.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import kakao_log as kl  # noqa: E402

COURSES = [{"course": "자료구조", "total": 15},
           {"course": "C프로그래밍", "total": 15},
           {"course": "컴퓨터구조", "total": 15},
           {"course": "오픈소스기반데이터분석", "total": 15}]

LOG = """방송대 강의 매일 꾸준히 공부 및 인증하는 모임 님과 카카오톡 대화
저장한 날짜 : 2026-09-28 23:53:29

--------------- 2026년 9월 7일 월요일 ---------------
[잔향/복수전공/3학년] [오후 6:43] 사진
[잔향/복수전공/3학년] [오후 6:44] 자료구조 1강 들었습니다
[빵/컴퓨터과학과/3학년] [오후 11:30] 컴퓨터구조 3강 들었습니다
--------------- 2026년 9월 8일 화요일 ---------------
[잔향/복수전공/3학년] [오후 9:22] C프로그래밍 1강 들었습니다
--------------- 2026년 9월 19일 토요일 ---------------
[잔향/복수전공/3학년] [오전 12:18] 자료구조 3강 들었습니다
"""


# --- 시각 -------------------------------------------------------------------
def test_afternoon_becomes_the_24_hour_clock():
    assert kl.parse_time("오후", 6, 44) == (18, 44)
    assert kl.parse_time("오전", 9, 3) == (9, 3)


def test_noon_and_midnight_are_the_tricky_ones():
    assert kl.parse_time("오전", 12, 18) == (0, 18)     # 자정은 0시
    assert kl.parse_time("오후", 12, 5) == (12, 5)      # 정오는 12시


# --- 날짜 구분선 ------------------------------------------------------------
def test_the_day_divider_is_read():
    assert kl.parse_day(
        "--------------- 2026년 9월 7일 월요일 ---------------") == \
        date(2026, 9, 7)


def test_an_ordinary_line_is_not_a_divider():
    assert kl.parse_day("[잔향] [오후 6:44] 자료구조 1강") is None
    assert kl.parse_day("") is None


# --- 새벽에 올린 인증 --------------------------------------------------------
def test_a_late_night_post_counts_as_the_day_before():
    """단톡방도 '새벽 세 시 이전은 전날' 로 세고 있다."""
    assert kl.study_date(date(2026, 9, 19), 0) == date(2026, 9, 18)
    assert kl.study_date(date(2026, 9, 19), 2) == date(2026, 9, 18)


def test_a_morning_post_counts_as_that_day():
    assert kl.study_date(date(2026, 9, 19), 3) == date(2026, 9, 19)
    assert kl.study_date(date(2026, 9, 19), 9) == date(2026, 9, 19)


# --- 과목 가리기 ------------------------------------------------------------
def test_a_course_is_found_by_its_full_name():
    a = kl.course_alias(COURSES)
    assert kl.find_course("자료구조 1강 들었습니다", a) == "자료구조"
    assert kl.find_course("C프로그래밍 2강 들었어요", a) == "C프로그래밍"


def test_a_short_name_is_understood():
    """대화에서는 정식 이름을 다 적지 않는다."""
    a = kl.course_alias(COURSES)
    assert kl.find_course("오픈소스 2강 들었습니다", a) == \
        "오픈소스기반데이터분석"
    assert kl.find_course("컴구 들었었는데", a) == "컴퓨터구조"


def test_the_longer_name_wins():
    """'오픈소스' 와 '오픈소스기반데이터분석' 이 함께 있으면 긴 쪽이 맞다."""
    a = kl.course_alias(COURSES)
    assert kl.find_course("오픈소스기반데이터분석 1강", a) == \
        "오픈소스기반데이터분석"


def test_a_message_about_nothing_gives_nothing():
    a = kl.course_alias(COURSES)
    assert kl.find_course("오늘도 화이팅입니다", a) is None
    assert kl.find_course("", a) is None


# --- 강 번호 ----------------------------------------------------------------
def test_one_lecture_number():
    assert kl.find_lectures("자료구조 1강 들었습니다") == [1]


def test_two_lectures_in_one_message():
    assert kl.find_lectures("자료구조 5강 6강 들었어요") == [5, 6]


def test_numbers_joined_by_a_comma_are_both_counted():
    """'8,9강' 은 8강과 9강을 들었다는 말이다."""
    assert kl.find_lectures("머신러닝 8,9강이요") == [8, 9]
    assert kl.find_lectures("딥러닝 1,2강 들었어요") == [1, 2]
    assert kl.find_lectures("시뮬 9, 10 강") == [9, 10]


def test_up_to_means_all_of_them():
    """'4강까지' 는 거기까지 다 들었다는 뜻이다."""
    assert kl.find_lectures("머신러닝 4강까지요") == [1, 2, 3, 4]


def test_a_number_beyond_the_course_is_dropped():
    """15강짜리 과목에 '20강' 이 적혔다면 강의 번호가 아니다."""
    assert kl.find_lectures("20강", total=15) == []


def test_a_message_without_a_number_gives_nothing():
    assert kl.find_lectures("완강했어요") == []
    assert kl.find_lectures("") == []


# --- 내 글만 ----------------------------------------------------------------
def test_my_own_posts_are_picked_by_the_nickname_prefix():
    """카톡 이름은 '잔향/복수전공/3학년' 처럼 뒤에 학과가 붙는다."""
    assert kl.is_mine("잔향/복수전공/3학년", "잔향")
    assert not kl.is_mine("빵/컴퓨터과학과/3학년", "잔향")


# --- 대화 전체 --------------------------------------------------------------
def test_the_log_gives_my_lectures_with_their_dates():
    got = kl.parse_log(LOG, "잔향", COURSES)
    assert got["자료구조"] == {"1": "2026-09-07", "3": "2026-09-18"}
    assert got["C프로그래밍"] == {"1": "2026-09-08"}


def test_other_peoples_posts_are_left_out():
    """빵님의 컴퓨터구조 3강은 내 진도가 아니다."""
    assert "컴퓨터구조" not in kl.parse_log(LOG, "잔향", COURSES)


def test_the_first_day_wins_when_a_lecture_comes_up_twice():
    """다시 들었다고 올려도 처음 본 날짜를 잃지 않는다."""
    log = LOG + ("--------------- 2026년 9월 25일 금요일 ---------------\n"
                 "[잔향/복수전공/3학년] [오후 1:00] 자료구조 1강 다시 들었습니다\n")
    assert kl.parse_log(log, "잔향", COURSES)["자료구조"]["1"] == "2026-09-07"


def test_counting_what_was_found():
    got = kl.parse_log(LOG, "잔향", COURSES)
    assert kl.count(got) == 3
    assert kl.count({}) == 0


def test_the_first_certified_day_becomes_the_start():
    assert kl.first_day(kl.parse_log(LOG, "잔향", COURSES)) == "2026-09-07"
    assert kl.first_day({}) is None


def test_an_empty_log_is_not_an_error():
    assert kl.parse_log("", "잔향", COURSES) == {}
    assert kl.parse_log(None, "잔향", COURSES) == {}


def test_a_post_before_any_day_divider_is_skipped():
    """어느 날 올린 건지 모르면 셀 수 없다."""
    assert kl.parse_log("[잔향] [오후 1:00] 자료구조 1강", "잔향", COURSES) == {}
