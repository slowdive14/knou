"""extra_video 순수 로직 단위테스트 — 한 회차에 영상이 2개일 때.

클립 선별(본강의 제외·짧은 안내영상 제외)·파일명·ffmpeg 인자·state 판정·
확인 문구를 검증한다. 실제 HLS 추출/요약은 수동 검증(프로젝트 철학).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from extra_video import (  # noqa: E402
    MIN_EXTRA_SEC,
    STAGE,
    STATE_FIELD,
    build_audio_cmd,
    clip_brief,
    extra_audio_filename,
    extra_note_name,
    extra_prompt_text,
    pending_extras,
    pick_extra_clips,
    read_state,
)


def _clip(idx=0, title="본강의", duration=2800.0, hls="https://x/y.m3u8?token=SECRET"):
    return {"idx": idx, "title": title, "duration": duration, "hlsUrl": hls}


# --- pick_extra_clips ------------------------------------------------------
def test_single_clip_has_no_extra():
    assert pick_extra_clips([_clip()]) == []


def test_two_real_videos_returns_second():
    clips = [_clip(0, "1부", 1500.0), _clip(1, "2부", 1400.0)]
    extras = pick_extra_clips(clips)
    assert [c["idx"] for c in extras] == [1]      # 더 긴 0번이 본강의


def test_longest_clip_is_excluded_even_if_not_first():
    clips = [_clip(0, "2부", 1400.0), _clip(1, "1부", 2000.0)]
    extras = pick_extra_clips(clips)
    assert [c["title"] for c in extras] == ["2부"]


def test_short_intro_clip_is_dropped():
    # 실측 15강: 138초짜리 안내 영상은 노트 대상이 아니다
    clips = [_clip(0, "본강의", 6883.0), _clip(1, "안내", 138.0)]
    assert pick_extra_clips(clips) == []


def test_clips_without_duration_are_ignored():
    clips = [_clip(0, "본강의", 2800.0), _clip(1, "미측정", None)]
    assert pick_extra_clips(clips) == []


def test_three_clips_returns_two_extras_in_idx_order():
    clips = [_clip(2, "3부", 900.0), _clip(0, "1부", 2000.0),
             _clip(1, "2부", 1200.0)]
    assert [c["idx"] for c in pick_extra_clips(clips)] == [1, 2]


def test_min_seconds_is_configurable():
    clips = [_clip(0, "본강의", 2800.0), _clip(1, "짧은2부", 200.0)]
    assert pick_extra_clips(clips) == []
    assert len(pick_extra_clips(clips, min_seconds=100)) == 1


def test_min_extra_sec_default_is_five_minutes():
    assert MIN_EXTRA_SEC == 300


# --- clip_brief : 토큰 유출 방지 -------------------------------------------
def test_clip_brief_drops_hls_token():
    b = clip_brief(_clip(1, "2부", 1400.0))
    assert b == {"idx": 1, "title": "2부", "duration": 1400.0}
    assert "SECRET" not in str(b) and "hlsUrl" not in b


# --- 이름/경로 -------------------------------------------------------------
def test_extra_note_name_appends_part():
    assert extra_note_name("배열", 2) == "배열 (2)"
    assert extra_note_name(" 배열 ", 3) == "배열 (3)"


def test_extra_audio_filename_does_not_collide_with_base_mp3():
    from download import build_filename
    assert extra_audio_filename("자료구조", 1, 2) == "자료구조_1강_2.mp3"
    assert extra_audio_filename("자료구조", 1, 2) != build_filename("자료구조", 1, "mp3")


def test_extra_audio_filename_sanitizes_course():
    assert "/" not in extra_audio_filename("자료/구조", 1, 2)


# --- ffmpeg 인자 -----------------------------------------------------------
def test_build_audio_cmd_extracts_audio_only():
    cmd = build_audio_cmd("https://h/p.m3u8?token=T", "out.mp3")
    assert "-vn" in cmd                       # 영상 제외
    assert cmd[-1] == "out.mp3"
    assert "https://h/p.m3u8?token=T" in cmd
    assert "libmp3lame" in cmd


# --- state 판정 ------------------------------------------------------------
def _state(extras=None, extra_ok=None):
    rec = {}
    if extras is not None:
        rec[STATE_FIELD] = extras
    if extra_ok is not None:
        rec[STAGE] = {"ok": extra_ok}
    return {"자료구조|1": rec}


def test_pending_extras_returns_detected_clips():
    st = _state(extras=[{"idx": 1, "title": "2부", "duration": 1400.0}])
    assert len(pending_extras(st, "자료구조", 1)) == 1


def test_pending_extras_empty_when_note_already_made():
    st = _state(extras=[{"idx": 1, "title": "2부", "duration": 1400.0}],
                extra_ok=True)
    assert pending_extras(st, "자료구조", 1) == []


def test_pending_extras_asks_again_after_failure():
    st = _state(extras=[{"idx": 1, "title": "2부", "duration": 1400.0}],
                extra_ok=False)
    assert len(pending_extras(st, "자료구조", 1)) == 1


def test_pending_extras_unknown_lecture_is_empty():
    assert pending_extras({}, "자료구조", 9) == []


def test_pending_extras_key_matches_main_lecture_key():
    from main import lecture_key
    st = {lecture_key("자료구조", 2): {STATE_FIELD: [{"idx": 1, "duration": 900}]}}
    assert len(pending_extras(st, "자료구조", 2)) == 1


# --- read_state ------------------------------------------------------------
def test_read_state_missing_file_is_empty(tmp_path):
    assert read_state(tmp_path / "none.json") == {}


def test_read_state_broken_json_is_empty(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{not json", encoding="utf-8")
    assert read_state(p) == {}


def test_read_state_loads_dict(tmp_path):
    p = tmp_path / "state.json"
    p.write_text('{"자료구조|1": {"extra_videos": []}}', encoding="utf-8")
    assert "자료구조|1" in read_state(p)


# --- 확인 문구 -------------------------------------------------------------
def test_prompt_text_mentions_count_and_minutes():
    body = extra_prompt_text([{"idx": 1, "title": "2부", "duration": 1380.0}],
                             "자료구조", 1)
    assert "자료구조 1강" in body
    assert "영상이 2개" in body
    assert "23분" in body            # 1380초 → 23분
    assert "2부" in body


def test_prompt_text_without_course_is_safe():
    assert "이 회차에 영상이 2개" in extra_prompt_text([{"duration": 600}])
