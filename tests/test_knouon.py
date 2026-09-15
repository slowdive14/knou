"""knouon 순수 로직 단위테스트 — 바이오통계학(통합학습관리시스템) 경로.

실측 정찰(docs/lms-map.md §11)에서 확인한 값을 그대로 기대값으로 쓴다.
브라우저 연동(enter_classroom·watch_week)은 수동 검증이다.
"""
from __future__ import annotations

import base64
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from knouon import (  # noqa: E402
    COMPLETE_PERCENT,
    Week,
    clean_week_name,
    content_id,
    enc_params,
    is_knouon_course,
    lecture_url,
    parse_percent,
    parse_week,
    parse_weeks,
    sbjct_id_for,
    unwatched,
    week_is_complete,
)

SBJCT = "SBJCT_KNOU2092001"


# --- 과목 판별 -------------------------------------------------------------
def test_biostat_goes_through_knouon():
    assert sbjct_id_for("바이오통계학") == SBJCT
    assert is_knouon_course("바이오통계학") is True


def test_other_courses_stay_on_the_old_system():
    for c in ("컴퓨터구조", "자료구조", "오픈소스기반데이터분석", ""):
        assert is_knouon_course(c) is False
        assert sbjct_id_for(c) is None


def test_course_lookup_ignores_padding():
    assert sbjct_id_for("  바이오통계학  ") == SBJCT


# --- 콘텐츠 ID -------------------------------------------------------------
def test_content_id_matches_the_real_one():
    # 실측: 1주차 버튼이 openWknoLectureViewPopup('WS_KNOU209200101', …)
    assert content_id(SBJCT, 1) == "WS_KNOU209200101"
    assert content_id(SBJCT, 15) == "WS_KNOU209200115"


def test_content_id_pads_to_two_digits():
    assert content_id(SBJCT, 9).endswith("09")
    assert content_id(SBJCT, 10).endswith("10")


# --- encParams -------------------------------------------------------------
def test_enc_params_is_plain_base64_json():
    """ui-common.js 의 makeEncParams = btoa(UTF-8 JSON). URL 인코딩 없음."""
    enc = enc_params({"sbjctId": SBJCT})
    assert json.loads(base64.b64decode(enc).decode("utf-8")) == {"sbjctId": SBJCT}


def test_enc_params_matches_a_real_url_value():
    # 실제 URL 의 addParams 값과 한 글자도 다르면 안 된다
    assert enc_params({"sbjctId": SBJCT}) == \
        "eyJzYmpjdElkIjoiU0JKQ1RfS05PVTIwOTIwMDEifQ=="


def test_lecture_url_carries_both_ids():
    url = lecture_url("WS_KNOU209200101", SBJCT)
    assert url.startswith("https://knouon.knou.ac.kr/lctr/wknoLectureView.do?")
    enc = url.split("encParams=", 1)[1]
    got = json.loads(base64.b64decode(enc).decode("utf-8"))
    assert got == {"lctrWknoSchdlId": "WS_KNOU209200101", "sbjctId": SBJCT}


# --- 진도율·주차명 ---------------------------------------------------------
def test_parse_percent_reads_the_real_text():
    assert parse_percent("진도율 5.67%") == 5.67
    assert parse_percent("진도율\xa00%") == 0.0
    assert parse_percent("진도율 100%") == 100.0


def test_parse_percent_survives_junk():
    assert parse_percent("") == 0.0
    assert parse_percent(None) == 0.0
    assert parse_percent("진도율 미정") == 0.0


def test_clean_week_name_drops_the_number():
    assert clean_week_name("1주차 통계학의 기본 개념과 데이터 요약") == \
        "통계학의 기본 개념과 데이터 요약"
    assert clean_week_name("15주차 생존분석 2") == "생존분석 2"


def test_clean_week_name_keeps_a_number_inside_the_title():
    # '생존분석 2' 의 2 는 주차 번호가 아니다
    assert clean_week_name("14주차 생존분석 1").endswith("1")


# --- 주차 파싱 -------------------------------------------------------------
def _raw(week="1", title="1주차 통계학의 기본 개념과 데이터 요약",
         progress="진도율 5.67%", **over):
    row = {"week": week, "title": title, "progress": progress,
           "period": "2026-08-17 ~ 2027-02-13",
           "contentId": "WS_KNOU209200101", "sbjctId": SBJCT}
    row.update(over)
    return row


def test_parse_week_builds_a_week():
    w = parse_week(_raw(), course="바이오통계학")
    assert (w.seq, w.percent, w.course) == (1, 5.67, "바이오통계학")
    assert w.name == "통계학의 기본 개념과 데이터 요약"
    assert w.content_id == "WS_KNOU209200101" and w.sbjct_id == SBJCT


def test_parse_week_falls_back_to_the_id_rule():
    # onclick 을 못 읽었어도 규칙으로 콘텐츠ID 를 만들 수 있다
    w = parse_week(_raw(week="7", contentId=""), sbjct_id=SBJCT)
    assert w.content_id == "WS_KNOU209200107"


def test_parse_week_rejects_a_bad_row():
    assert parse_week(_raw(week="")) is None
    assert parse_week(_raw(week="0")) is None
    assert parse_week({}) is None


def test_parse_weeks_sorts_and_drops_junk():
    rows = [_raw(week="10"), _raw(week=""), _raw(week="2"), _raw(week="1")]
    got = parse_weeks(rows, SBJCT, "바이오통계학")
    assert [w.seq for w in got] == [1, 2, 10]


# --- 이수 판정 -------------------------------------------------------------
def _week(percent):
    return Week(seq=1, name="x", percent=percent, content_id="WS_X",
                sbjct_id=SBJCT)


def test_week_is_complete_at_the_threshold():
    assert week_is_complete(_week(100.0)) is True
    assert week_is_complete(_week(COMPLETE_PERCENT)) is True
    assert week_is_complete(_week(COMPLETE_PERCENT - 0.01)) is False


def test_a_barely_started_week_is_not_complete():
    # 실측 출발점: 1주차가 0.52% 였다
    assert week_is_complete(_week(0.52)) is False
    assert week_is_complete(_week(0.0)) is False


def test_week_exposes_video_done_like_a_lecture():
    """기존 파이프라인이 lec.video_done 으로 묻는다 — 이름을 맞춰 둔다."""
    assert _week(100.0).video_done is True
    assert _week(5.67).video_done is False


def test_unwatched_keeps_only_what_is_left():
    ws = [_week(100.0), _week(5.67), _week(0.0)]
    assert [w.percent for w in unwatched(ws)] == [5.67, 0.0]


def test_unwatched_handles_an_empty_list():
    assert unwatched([]) == [] and unwatched(None) == []


# --- 재생 프레임 인식(watch.py 와의 접점) ----------------------------------
def test_watch_recognises_a_kollus_frame():
    """watch.py 의 감시 로직을 그대로 쓰려면 프레임을 알아봐야 한다."""
    from watch import _PLAYER_FRAME_RE
    assert _PLAYER_FRAME_RE.search(
        "https://v.kr.kollus.com/s?custom_key=abc&uservalue0=SBCN_X")
    assert _PLAYER_FRAME_RE.search(     # 전자캠퍼스도 계속 인식해야 한다
        "https://ucampus.knou.ac.kr/.../ViewPlayer.jsp?x=1")
    assert not _PLAYER_FRAME_RE.search("https://knouon.knou.ac.kr/lctr/x.do")
