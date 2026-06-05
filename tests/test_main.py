"""main 모듈 순수 로직 단위 테스트 (Phase 7).

모드별 단계 매핑 / 상태 키 / 단계 완료판정 / 상태 기록 / 강의 필터 /
미완료 강의 선별만 검증. 실제 브라우저·AI·ffmpeg 오케스트레이션은
수동 스모크(main.py --mode 요약 --course 이산수학 --seq 1).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import (  # noqa: E402
    filter_unwatched,
    lecture_done,
    lecture_key,
    mark_stage,
    pending_lectures,
    select_lectures,
    should_run_stage,
    stage_done,
    stages_for_mode,
)


# ---- stages_for_mode ------------------------------------------------------
def test_stages_for_mode_watch_only():
    assert stages_for_mode("이수") == ["watch"]


def test_stages_for_mode_summary():
    assert stages_for_mode("요약") == ["download", "summarize", "capture"]


def test_stages_for_mode_all():
    assert stages_for_mode("전체") == [
        "watch", "download", "summarize", "capture"]


def test_stages_for_mode_invalid():
    import pytest
    with pytest.raises(ValueError):
        stages_for_mode("없는모드")


def test_stages_for_mode_returns_copy():
    # 반환 리스트를 변형해도 내부 정의가 오염되지 않아야 함
    a = stages_for_mode("이수")
    a.append("x")
    assert stages_for_mode("이수") == ["watch"]


# ---- lecture_key ----------------------------------------------------------
def test_lecture_key():
    assert lecture_key("이산수학", 1) == "이산수학|1"


def test_lecture_key_coerces_seq():
    assert lecture_key("운영체제", "3") == "운영체제|3"


# ---- stage_done / lecture_done -------------------------------------------
def test_stage_done_true():
    state = {"이산수학|1": {"download": {"ok": True}}}
    assert stage_done(state, "이산수학|1", "download") is True


def test_stage_done_false_when_missing():
    assert stage_done({}, "이산수학|1", "download") is False


def test_stage_done_false_when_not_ok():
    state = {"이산수학|1": {"download": {"ok": False, "error": "boom"}}}
    assert stage_done(state, "이산수학|1", "download") is False


def test_lecture_done_all_stages():
    state = {"이산수학|1": {
        "download": {"ok": True},
        "summarize": {"ok": True},
        "capture": {"ok": True}}}
    assert lecture_done(state, "이산수학|1", ["download", "summarize", "capture"])


def test_lecture_done_missing_one():
    state = {"이산수학|1": {
        "download": {"ok": True}, "summarize": {"ok": True}}}
    assert lecture_done(state, "이산수학|1",
                        ["download", "summarize", "capture"]) is False


def test_lecture_done_empty_stages_false():
    assert lecture_done({}, "이산수학|1", []) is False


# ---- mark_stage -----------------------------------------------------------
def test_mark_stage_ok():
    state = {}
    mark_stage(state, "이산수학|1", "download", ok=True)
    assert state["이산수학|1"]["download"]["ok"] is True


def test_mark_stage_records_error():
    state = {}
    mark_stage(state, "이산수학|1", "summarize", ok=False, error="timeout")
    rec = state["이산수학|1"]["summarize"]
    assert rec["ok"] is False and rec["error"] == "timeout"


def test_mark_stage_preserves_other_stages():
    state = {"이산수학|1": {"download": {"ok": True}}}
    mark_stage(state, "이산수학|1", "summarize", ok=True)
    assert state["이산수학|1"]["download"]["ok"] is True
    assert state["이산수학|1"]["summarize"]["ok"] is True


# ---- select_lectures (필터) ----------------------------------------------
PAIRS = [
    ("이산수학", {"seq": 1, "name": "개요"}),
    ("이산수학", {"seq": 2, "name": "집합"}),
    ("운영체제", {"seq": 1, "name": "OS개요"}),
]


def test_select_lectures_no_filter():
    assert select_lectures(PAIRS) == PAIRS


def test_select_lectures_by_course():
    out = select_lectures(PAIRS, course="이산수학")
    assert [c for c, _ in out] == ["이산수학", "이산수학"]


def test_select_lectures_course_substring():
    out = select_lectures(PAIRS, course="이산")
    assert len(out) == 2


def test_select_lectures_by_seq():
    out = select_lectures(PAIRS, seq=1)
    assert {c for c, _ in out} == {"이산수학", "운영체제"}
    assert all(l["seq"] == 1 for _, l in out)


def test_select_lectures_course_and_seq():
    out = select_lectures(PAIRS, course="이산수학", seq=2)
    assert len(out) == 1
    assert out[0][1]["name"] == "집합"


# ---- pending_lectures -----------------------------------------------------
def test_pending_lectures_excludes_done():
    state = {}
    mark_stage(state, "이산수학|1", "watch", ok=True)
    pending = pending_lectures(state, PAIRS, ["watch"])
    keys = [lecture_key(c, l["seq"]) for c, l in pending]
    assert "이산수학|1" not in keys          # 완료됨 → 제외
    assert "이산수학|2" in keys and "운영체제|1" in keys


def test_pending_lectures_force_includes_done():
    # force=True(다시 만들기/덮어쓰기) → 완료된 차시도 전부 포함
    state = {}
    mark_stage(state, "이산수학|1", "watch", ok=True)
    pending = pending_lectures(state, PAIRS, ["watch"], force=True)
    assert len(pending) == len(PAIRS)


# ---- should_run_stage (force/덮어쓰기) -----------------------------------
def test_should_run_stage_runs_when_not_done():
    assert should_run_stage({}, "이산수학|1", "download") is True


def test_should_run_stage_skips_done():
    state = {}
    mark_stage(state, "이산수학|1", "download", ok=True)
    assert should_run_stage(state, "이산수학|1", "download") is False


def test_should_run_stage_force_overrides_done():
    state = {}
    mark_stage(state, "이산수학|1", "download", ok=True)
    assert should_run_stage(state, "이산수학|1", "download", force=True) is True


# ---- filter_unwatched (미시청만) ------------------------------------------
WATCH_PAIRS = [
    ("이산수학", {"seq": 1, "name": "개요", "video_done": True}),
    ("이산수학", {"seq": 2, "name": "집합", "video_done": False}),
    ("운영체제", {"seq": 1, "name": "OS개요", "video_done": False}),
]


def test_filter_unwatched_excludes_watched():
    out = filter_unwatched(WATCH_PAIRS)
    keys = [lecture_key(c, l["seq"]) for c, l in out]
    assert "이산수학|1" not in keys          # video_done=True → 제외
    assert keys == ["이산수학|2", "운영체제|1"]


def test_filter_unwatched_missing_key_is_unwatched():
    # video_done 키가 없으면 보수적으로 '미시청' 취급(요약 대상 포함)
    out = filter_unwatched([("X", {"seq": 1, "name": "n"})])
    assert len(out) == 1


def test_filter_unwatched_all_done_empty():
    pairs = [("이산수학", {"seq": 1, "video_done": True})]
    assert filter_unwatched(pairs) == []
