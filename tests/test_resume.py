"""실패 지점부터 이어서 하기 — '미이수만' 필터가 재시도를 막지 않는지.

실측 사건: AI네이티브 7강이 영상 이수·형성평가·다운로드까지 성공한 뒤
summarize 가 429(크레딧 소진)로 실패했다. 그런데 영상 이수가 끝났으니 LMS 는
video_done=True 를 주고, '미이수부터' 필터가 그 강의를 **통째로 걸러내** 다음
실행에서 대상에서 빠졌다 → 실패한 요약을 영영 이어서 할 수 없었다.
(같은 이유로 2강의 실패한 capture(503)도 빠져 있었다.)

단계 완료 기록 자체는 잘 남고 있었으므로, 필터만 고치면 이어서 하기가 된다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import (  # noqa: E402
    filter_unwatched,
    has_failed_stage,
    lecture_key,
    pending_lectures,
    should_run_stage,
    stages_for_mode,
)

FULL = stages_for_mode("전체")     # watch, exam, download, summarize, capture


def _lec(seq, watched):
    return {"seq": seq, "name": f"{seq}강", "video_done": watched}


def _state(seq, **stages):
    return {lecture_key("과목", seq): {
        k: {"ok": v} for k, v in stages.items()}}


PAIRS = [("과목", _lec(7, True)), ("과목", _lec(8, False))]


# --- 실패한 강의는 이수했어도 남는다 ----------------------------------------
def test_failed_lecture_survives_unwatched_filter():
    st = _state(7, watch=True, exam=True, download=True, summarize=False)
    got = [l["seq"] for _c, l in filter_unwatched(PAIRS, state=st, stages=FULL)]
    assert got == [7, 8]                 # 7강이 살아남아 이어서 할 수 있다


def test_without_state_old_behaviour_is_kept():
    # state 를 안 주면 예전처럼 순수 미시청 필터(다른 호출부 보호)
    got = [l["seq"] for _c, l in filter_unwatched(PAIRS)]
    assert got == [8]


def test_fully_done_watched_lecture_is_still_filtered_out():
    # 다 끝난 강의까지 끌고 오면 안 된다
    st = _state(7, watch=True, exam=True, download=True, summarize=True,
                capture=True)
    got = [l["seq"] for _c, l in filter_unwatched(PAIRS, state=st, stages=FULL)]
    assert got == [8]


def test_never_attempted_watched_lecture_is_not_pulled_in():
    # 시도한 적 없는(기록 없는) 이수 완료 강의는 '미이수부터' 의미대로 제외
    got = [l["seq"] for _c, l in filter_unwatched(PAIRS, state={}, stages=FULL)]
    assert got == [8]


# --- has_failed_stage --------------------------------------------------------
def test_has_failed_stage_detects_failure():
    st = _state(7, watch=True, summarize=False)
    assert has_failed_stage(st, lecture_key("과목", 7), FULL) is True


def test_has_failed_stage_false_when_all_ok():
    st = _state(7, watch=True, summarize=True)
    assert has_failed_stage(st, lecture_key("과목", 7), FULL) is False


def test_has_failed_stage_ignores_other_stages():
    # 이번 실행에 없는 단계의 실패는 무시한다(요약 모드에서 watch 실패 등)
    st = _state(7, watch=False, summarize=True)
    assert has_failed_stage(st, lecture_key("과목", 7), ["summarize"]) is False


def test_has_failed_stage_unknown_lecture():
    assert has_failed_stage({}, lecture_key("과목", 7), FULL) is False


# --- 이어서 할 때 성공한 단계는 다시 안 한다 --------------------------------
def test_resume_skips_finished_stages_and_redoes_failed():
    key = lecture_key("과목", 7)
    st = _state(7, watch=True, exam=True, download=True, summarize=False)
    # 영상 이수(가장 오래 걸리는 단계)는 다시 하지 않는다
    assert should_run_stage(st, key, "watch") is False
    assert should_run_stage(st, key, "exam") is False
    assert should_run_stage(st, key, "download") is False
    # 실패한 단계와, 실패로 건너뛰어 기록이 없는 단계는 다시 한다
    assert should_run_stage(st, key, "summarize") is True
    assert should_run_stage(st, key, "capture") is True


def test_resumable_lecture_reaches_the_todo_list():
    st = _state(7, watch=True, exam=True, download=True, summarize=False)
    pairs = filter_unwatched(PAIRS, state=st, stages=FULL)
    todo = [l["seq"] for _c, l in pending_lectures(st, pairs, FULL)]
    assert todo[0] == 7                  # 실패한 강의가 먼저 처리된다


def test_force_still_redoes_everything():
    st = _state(7, watch=True, summarize=False)
    key = lecture_key("과목", 7)
    assert should_run_stage(st, key, "watch", force=True) is True


# --- 이어서 할 때의 처리 순서 -----------------------------------------------
# 실측 불편: 2강(이미지만 없음)과 7강(노트부터 없음)이 함께 대기하는데 차시 순이라
# 2강이 먼저 잡혔다. 한 번에 1강만 도는 설정에서는 정작 급한 7강 노트가 밀린다.
from main import first_missing_stage, order_todo  # noqa: E402


def _pairs(*seqs):
    return [("과목", _lec(s, True)) for s in seqs]


def _mixed_state():
    st = {}
    st.update(_state(2, watch=True, exam=True, download=True, summarize=True,
                     capture=False))          # 이미지만 없음
    st.update(_state(7, watch=True, exam=True, download=True,
                     summarize=False))        # 노트부터 없음
    return st


def test_note_missing_lecture_comes_before_images_only():
    st = _mixed_state()
    got = [l["seq"] for _c, l in order_todo(st, _pairs(2, 7), FULL)]
    assert got == [7, 2]


def test_resume_lectures_come_before_fresh_ones():
    st = _mixed_state()
    pairs = _pairs(2, 7) + [("과목", _lec(8, False))]
    got = [l["seq"] for _c, l in order_todo(st, pairs, FULL)]
    assert got == [7, 2, 8]                    # 새 강의(8)는 뒤로


def test_fresh_course_keeps_lecture_order():
    # 실패 기록이 없으면 예전과 똑같이 차시 순(정상 실행 동작을 바꾸지 않는다)
    pairs = [("과목", _lec(s, False)) for s in (1, 2, 3, 4)]
    got = [l["seq"] for _c, l in order_todo({}, pairs, FULL)]
    assert got == [1, 2, 3, 4]


def test_same_gap_falls_back_to_lecture_order():
    st = {}
    st.update(_state(9, watch=True, exam=True, download=True, summarize=False))
    st.update(_state(4, watch=True, exam=True, download=True, summarize=False))
    got = [l["seq"] for _c, l in order_todo(st, _pairs(9, 4), FULL)]
    assert got == [4, 9]


def test_first_missing_stage_points_at_the_gap():
    st = _state(7, watch=True, exam=True, download=True, summarize=False)
    assert first_missing_stage(st, lecture_key("과목", 7), FULL) == 3  # summarize
    st2 = _state(2, watch=True, exam=True, download=True, summarize=True,
                 capture=False)
    assert first_missing_stage(st2, lecture_key("과목", 2), FULL) == 4  # capture


def test_first_missing_stage_all_done():
    st = _state(1, **{s: True for s in FULL})
    assert first_missing_stage(st, lecture_key("과목", 1), FULL) == len(FULL)
