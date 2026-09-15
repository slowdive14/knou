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


# --- 배속 수용 (오리엔테이션이 멈추던 원인) --------------------------------
# 실측: Kollus 는 영상에 따라 배속을 거부하고 1.0x 로 되돌린다. 그런데
# watch._play_until_end 는 배속이 낮으면 폴링마다 다시 건다 — 그 반복이 재생을
# 끊었다. 걸리는 배속을 받아들여야 끝까지 간다.
class _FakeFrames:
    """_clip_state 가 보는 프레임 대역."""

    def __init__(self, rate):
        self.rate = rate
        self.url = "https://v.kr.kollus.com/s?custom_key=x"

    def evaluate(self, js, *a):
        import json as _j
        return _j.dumps({"pos": 1.0, "dur": 400.0, "rate": self.rate,
                         "paused": False, "ended": False})


class _FakePage:
    def __init__(self, rate):
        self.frames = [_FakeFrames(rate)]

    def wait_for_timeout(self, ms):
        pass


def test_effective_speed_accepts_a_refused_rate(monkeypatch):
    import knouon
    monkeypatch.setattr(knouon.time, "sleep", lambda s: None)
    # 2배속을 요청했지만 플레이어가 끝내 1.0 으로 돌려놓는 상황
    assert knouon.effective_speed(_FakePage(1.0), 0, 2.0, checks=3) == 1.0


class _SlowPage:
    """배속이 **늦게** 걸리는 플레이어 — 처음 몇 번은 1.0 이다가 올라간다."""

    def __init__(self, late_after=2, rate=2.0):
        self.calls = 0
        self.late_after = late_after
        self.rate = rate
        page = self

        class _F:
            url = "https://v.kr.kollus.com/s?custom_key=x"

            def evaluate(self, js, *a):
                import json as _j
                page.calls += 1
                r = page.rate if page.calls > page.late_after else 1.0
                return _j.dumps({"pos": 1.0, "dur": 400.0, "rate": r,
                                 "paused": False, "ended": False})

        self.frames = [_F()]

    def wait_for_timeout(self, ms):
        pass


def test_effective_speed_waits_for_a_late_rate(monkeypatch):
    """배속은 재생 직후 잠깐 1.0 이다가 올라간다(실측: 29초 1.0 → 44초 2.0).

    짧게 보고 최솟값을 잡으면 2배속이 걸리는 영상을 1배속으로 낮춰 버린다.
    """
    import knouon
    monkeypatch.setattr(knouon.time, "sleep", lambda s: None)
    assert knouon.effective_speed(_SlowPage(), 0, 2.0, checks=8) == 2.0


def test_effective_speed_keeps_a_rate_that_stuck(monkeypatch):
    import knouon
    monkeypatch.setattr(knouon.time, "sleep", lambda s: None)
    assert knouon.effective_speed(_FakePage(2.0), 0, 2.0, checks=2) == 2.0


def test_effective_speed_never_exceeds_the_request(monkeypatch):
    """플레이어가 더 빠르게 잡아도 우리가 요청한 값을 넘기지 않는다."""
    import knouon
    monkeypatch.setattr(knouon.time, "sleep", lambda s: None)
    assert knouon.effective_speed(_FakePage(4.0), 0, 2.0, checks=1) == 2.0


def test_watch_week_does_not_reforce_playback():
    """폴링마다 재생을 강제하면 오히려 끊긴다 — 그 감시를 걸지 않는다."""
    import inspect

    import knouon
    src = inspect.getsource(knouon.watch_week)
    assert "solo_guard(" not in src
    assert "effective_speed(" in src


# --- 파이프라인 통합 (main.py) ---------------------------------------------
# 바이오통계학은 '나의 학습'에 뜨지만 차시 AJAX 가 빈 목록을 준다. 그럴 때
# knouon 주차로 채우고, 아직 손대지 않은 단계는 조용히 실패하지 않고 건너뛴다.
class _Logged:
    """_Ctx.logger 대역 — 남긴 말을 모아 둔다."""

    def __init__(self):
        self.said: list[str] = []

    def info(self, msg, *a):
        self.said.append(str(msg) % a if a else str(msg))

    warning = error = info


class _Ctx:
    def __init__(self):
        self.logger = _Logged()
        self.page = None
        self.cfg = None


def test_unsupported_stage_is_skipped_not_failed():
    """실패로 기록하면 의존하는 뒤 단계까지 막힌다 — 건너뜀으로 남긴다."""
    import main
    c = _Ctx()
    r = main._knouon_unsupported(c, "download", "바이오통계학")
    assert r["ok"] is True and r["skipped"] is True
    assert any("지원하지 않" in m for m in c.logger.said)


def test_knouon_stages_are_guarded():
    """아직 안 되는 단계는 knouon 과목에서 곧장 건너뛴다."""
    import inspect

    import main
    for fn in (main._stage_exam, main._stage_download,
               main._stage_capture, main._stage_extra):
        src = inspect.getsource(fn)
        assert "_knouon_unsupported" in src, fn.__name__


def test_watch_stage_routes_biostat_to_knouon():
    import inspect

    import main
    src = inspect.getsource(main._stage_watch)
    assert "knouon.is_knouon_course" in src and "knouon.watch_week" in src


def test_watch_stage_keeps_the_old_path_for_other_courses():
    import inspect

    import main
    assert "watch_lecture" in inspect.getsource(main._stage_watch)


def test_knouon_weeks_survives_a_failure():
    """주차 조회가 깨져도 실행 전체를 멈추지 않는다."""
    import main

    class _Boom:
        def goto(self, *a, **k):
            raise RuntimeError("끊김")

    log = _Logged()
    assert main._knouon_weeks(_Boom(), "바이오통계학", log) == []
    assert any("실패" in m for m in log.said)


def test_snapshot_fills_a_knouon_course():
    """앱 목록(lectures.json)에도 주차가 들어가야 고를 수 있다."""
    import inspect

    import snapshot
    src = inspect.getsource(snapshot.refresh_snapshot)
    assert "knouon.is_knouon_course" in src and "knouon.fetch_weeks" in src


def test_snapshot_entry_accepts_a_week():
    """Week 는 Lecture 자리에 그대로 들어간다(없는 필드는 기본값)."""
    from snapshot import lecture_entry
    e = lecture_entry(Week(seq=3, name="추정", percent=100.0,
                           content_id="WS_X", sbjct_id=SBJCT))
    assert e["seq"] == 3 and e["name"] == "추정"
    assert e["video_done"] is True          # percent 100 → 이수
    assert e["exam_done"] is False and e["total_min"] == 0
