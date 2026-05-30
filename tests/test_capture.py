"""capture 모듈 순수 로직 단위 테스트 (Phase 6).

캡처 파일명 / ffmpeg 명령 빌더 / 길이매칭 클립선택 / 캡처필요판정 /
요약 노트 인라인 이미지 임베드만 검증.
실제 ffmpeg 캡처·플레이어 조회는 수동 검증(capture_one.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture import (  # noqa: E402
    _plan_renormalize,
    build_ffmpeg_cmd,
    build_vision_prompt,
    candidate_seconds,
    capture_filename,
    clip_timeline,
    embed_captures,
    locate_clip,
    needs_capture,
    normalize_ts_seconds,
    orphan_captures,
    parse_vision_choice,
    pick_clip_by_duration,
)


# ---- capture_filename -----------------------------------------------------
def test_capture_filename():
    assert capture_filename("이산수학", 1, 290) == "이산수학_1강_00-04-50.jpg"


def test_capture_filename_hms():
    assert capture_filename("이산수학", 1, 3723) == "이산수학_1강_01-02-03.jpg"


def test_capture_filename_sanitizes():
    out = capture_filename("함수/관계", 7, 90)
    assert "/" not in out and ":" not in out
    assert out.endswith(".jpg")
    assert "00-01-30" in out


def test_capture_filename_ext():
    assert capture_filename("이산수학", 1, 0, ext="png").endswith("_00-00-00.png")


# ---- pick_clip_by_duration ------------------------------------------------
CLIPS = [
    {"title": "오리엔테이션", "duration": 2490.9, "hlsUrl": "u0"},
    {"title": "들어가기", "duration": 187.3, "hlsUrl": "u1"},
    {"title": "학습하기", "duration": 3299.7, "hlsUrl": "u2"},
    {"title": "정리하기", "duration": 298.8, "hlsUrl": "u3"},
]


def test_pick_clip_by_duration_closest():
    best = pick_clip_by_duration(CLIPS, 2490.97)
    assert best["title"] == "오리엔테이션"


def test_pick_clip_by_duration_other():
    best = pick_clip_by_duration(CLIPS, 300.0)
    assert best["title"] == "정리하기"


def test_pick_clip_by_duration_empty():
    assert pick_clip_by_duration([], 100.0) is None


def test_pick_clip_by_duration_no_durations():
    assert pick_clip_by_duration([{"title": "x", "hlsUrl": "u"}], 100.0) is None


# ---- build_ffmpeg_cmd -----------------------------------------------------
def test_build_ffmpeg_cmd_basic():
    cmd = build_ffmpeg_cmd("https://x/p.m3u8?token=abc", 290, "out.jpg")
    assert cmd[0] == "ffmpeg"
    assert cmd[-1] == "out.jpg"
    assert "-frames:v" in cmd
    # fast seek: -ss 가 -i 앞에 와야 함
    assert cmd.index("-ss") < cmd.index("-i")
    assert cmd[cmd.index("-ss") + 1] == "290"
    assert cmd[cmd.index("-i") + 1] == "https://x/p.m3u8?token=abc"


def test_build_ffmpeg_cmd_overwrites():
    # -y(덮어쓰기)로 재실행 안전
    assert "-y" in build_ffmpeg_cmd("u", 0, "o.jpg")


# ---- needs_capture --------------------------------------------------------
def test_needs_capture_missing(tmp_path):
    assert needs_capture(tmp_path / "x.jpg") is True


def test_needs_capture_empty(tmp_path):
    p = tmp_path / "e.jpg"
    p.write_bytes(b"")
    assert needs_capture(p) is True


def test_needs_capture_existing(tmp_path):
    p = tmp_path / "ok.jpg"
    p.write_bytes(b"\xff\xd8\xff\xe0jpeg-ish")
    assert needs_capture(p) is False


# ---- embed_captures -------------------------------------------------------
def test_embed_captures_inline_after_timestamp_line():
    md = "### 이산수학의 정의 🎬 [00:04:50] (교재 p.5)\n이산적인 구조.\n"
    out = embed_captures(md, {290: "이산수학_1강_00-04-50.jpg"})
    lines = out.splitlines()
    assert lines[0] == "### 이산수학의 정의 🎬 [00:04:50] (교재 p.5)"
    assert lines[1] == "![[이산수학_1강_00-04-50.jpg]]"
    assert "이산적인 구조." in out


def test_embed_captures_idempotent():
    md = ("### 정의 🎬 [00:04:50]\n"
          "![[이산수학_1강_00-04-50.jpg]]\n본문\n")
    out = embed_captures(md, {290: "이산수학_1강_00-04-50.jpg"})
    assert out.count("![[이산수학_1강_00-04-50.jpg]]") == 1


def test_embed_captures_replaces_existing():
    # 비전 검증으로 선택 프레임이 바뀌면 기존 임베드를 교체(중복 X)
    md = ("### 정의 🎬 [00:04:50]\n"
          "![[이산수학_1강_00-04-50.jpg]]\n본문\n")
    out = embed_captures(md, {290: "이산수학_1강_00-05-05.jpg"})
    assert "![[이산수학_1강_00-05-05.jpg]]" in out
    assert "![[이산수학_1강_00-04-50.jpg]]" not in out  # 옛 임베드 제거
    assert out.count("![[") == 1
    assert "본문" in out


def test_embed_captures_no_match_unchanged():
    md = "### 정의 🎬 [00:04:50]\n본문\n"
    out = embed_captures(md, {999: "x.jpg"})
    assert out == md


def test_embed_captures_multiple():
    md = ("### A 🎬 [00:04:50]\n본문A\n"
          "### B 🎬 [12:05]\n본문B\n")
    out = embed_captures(md, {290: "a.jpg", 725: "b.jpg"})
    assert "![[a.jpg]]" in out and "![[b.jpg]]" in out
    # 각각 해당 타임스탬프 줄 바로 다음에 위치
    lines = out.splitlines()
    assert lines[lines.index("![[a.jpg]]") - 1].startswith("### A")
    assert lines[lines.index("![[b.jpg]]") - 1].startswith("### B")


# ---- candidate_seconds (비전 검증 후보 시점) -------------------------------
def test_candidate_seconds_basic():
    # base 290, offsets -20/0/+15/+30 → 시간순 정렬·중복제거
    assert candidate_seconds(290, (-20, 0, 15, 30)) == [270, 290, 305, 320]


def test_candidate_seconds_clamps_negative():
    # base 가 작아 음수가 되는 후보는 버림(0 미만 제외)
    assert candidate_seconds(10, (-20, 0, 15, 30)) == [10, 25, 40]


def test_candidate_seconds_drops_over_duration():
    # 클립 길이를 넘는 후보는 버림(검은 끝프레임 방지)
    assert candidate_seconds(290, (-20, 0, 15, 30), clip_dur=300) == [270, 290]


def test_candidate_seconds_dedupe():
    # 같은 초로 겹치면 한 번만
    assert candidate_seconds(100, (0, 0, 10)) == [100, 110]


# ---- orphan_captures (참조 안 되는 캡처 정리) ------------------------------
def test_orphan_captures_unreferenced():
    existing = [
        "이산수학_1강_00-04-30.jpg",
        "이산수학_1강_00-04-50.jpg",   # 참조 안 됨 → orphan
        "이산수학_1강_00-08-50.jpg",   # 참조 안 됨 → orphan
    ]
    ref = {"이산수학_1강_00-04-30.jpg"}
    out = orphan_captures(existing, ref, "이산수학", 1)
    assert out == ["이산수학_1강_00-04-50.jpg", "이산수학_1강_00-08-50.jpg"]


def test_orphan_captures_skips_other_lectures():
    # 다른 차시/과목 파일은 접두사가 달라 절대 건드리지 않음
    existing = [
        "이산수학_1강_00-04-50.jpg",   # 이번 차시·미참조 → orphan
        "이산수학_2강_00-01-00.jpg",   # 다른 차시 → 보존
        "운영체제_1강_00-01-00.jpg",   # 다른 과목 → 보존
    ]
    out = orphan_captures(existing, set(), "이산수학", 1)
    assert out == ["이산수학_1강_00-04-50.jpg"]


def test_orphan_captures_all_referenced():
    existing = ["이산수학_1강_00-04-30.jpg"]
    out = orphan_captures(existing, {"이산수학_1강_00-04-30.jpg"}, "이산수학", 1)
    assert out == []


# ---- parse_vision_choice (비전 JSON 응답 파싱) -----------------------------
def test_parse_vision_choice_dict():
    assert parse_vision_choice('{"index": 2, "reason": "맞음"}', 4) == 2


def test_parse_vision_choice_none_when_minus_one():
    # -1 = 맞는 것 없음 → None(=fallback)
    assert parse_vision_choice('{"index": -1, "reason": "없음"}', 4) is None


def test_parse_vision_choice_out_of_range():
    assert parse_vision_choice('{"index": 9}', 4) is None


def test_parse_vision_choice_code_fence():
    assert parse_vision_choice('```json\n{"index": 1}\n```', 4) == 1


def test_parse_vision_choice_bare_number():
    assert parse_vision_choice("0", 4) == 0


def test_parse_vision_choice_broken_json():
    assert parse_vision_choice("내용 없음", 4) is None


def test_parse_vision_choice_empty():
    assert parse_vision_choice("", 4) is None
    assert parse_vision_choice(None, 4) is None


# ---- build_vision_prompt --------------------------------------------------
def test_build_vision_prompt_has_label_and_rules():
    p = build_vision_prompt("추상화", 4)
    assert "추상화" in p          # 개념 라벨 포함
    assert "JSON" in p            # 구조화 출력 지시
    assert "-1" in p              # 매칭 없음 규칙


# ---- normalize_ts_seconds (Gemini 'MM:SS:00' 오형식 교정) ------------------
# 2시간짜리 강의에서 1시간 미만 시점을 'MM:SS:00'으로 잘못 적어
# timestamp_to_seconds 가 MM시간 SS분으로 파싱 → 전체길이 초과.
# MP3 길이를 알면 '필드 시프트'(h→분, m→초)로 원래 시점 복원.
def test_normalize_ts_seconds_misformatted():
    # "09:21:00" → 9*3600+21*60 = 33660 → 실제 9분21초 = 561
    assert normalize_ts_seconds(33660, 7209) == 561


def test_normalize_ts_seconds_misformatted_large():
    # "57:59:00" → 57*3600+59*60 = 208740 → 57분59초 = 3479
    assert normalize_ts_seconds(208740, 7209) == 3479


def test_normalize_ts_seconds_valid_hour_unchanged():
    # "01:00:00" = 3600s 는 전체길이 이내 → 진짜 1시간 시점, 교정 안 함
    assert normalize_ts_seconds(3600, 7209) == 3600


def test_normalize_ts_seconds_small_excess_unchanged():
    # 전체길이를 60초 이내로 살짝 넘으면(끝자락 근사) 교정하지 않음
    assert normalize_ts_seconds(7260, 7209) == 7260


def test_normalize_ts_seconds_no_duration_unchanged():
    assert normalize_ts_seconds(33660, 0) == 33660
    assert normalize_ts_seconds(33660, None) == 33660


def test_normalize_ts_seconds_below_duration_unchanged():
    assert normalize_ts_seconds(290, 2490) == 290


# ---- clip_timeline (MP3=클립 연결 → 누적 타임라인) -------------------------
CLIPS13 = [
    {"idx": 0, "title": "들어가기", "duration": 536.0, "hlsUrl": "u0"},
    {"idx": 1, "title": "학습하기", "duration": 6322.0, "hlsUrl": "u1"},
    {"idx": 2, "title": "정리하기", "duration": 352.0, "hlsUrl": "u2"},
]


def test_clip_timeline_cumulative_bounds():
    tl = clip_timeline(CLIPS13)
    starts_ends = [(s, e) for s, e, _ in tl]
    assert starts_ends == [(0.0, 536.0), (536.0, 6858.0), (6858.0, 7210.0)]
    assert [c["title"] for _, _, c in tl] == ["들어가기", "학습하기", "정리하기"]


def test_clip_timeline_skips_invalid_duration():
    clips = [
        {"title": "a", "duration": 100.0},
        {"title": "b", "duration": None},      # 길이 측정 실패 → 제외
        {"title": "c", "duration": 0},         # 0 → 제외
        {"title": "d", "duration": 50.0},
    ]
    tl = clip_timeline(clips)
    assert [(s, e, c["title"]) for s, e, c in tl] == [
        (0.0, 100.0, "a"), (100.0, 150.0, "d")]


def test_clip_timeline_empty():
    assert clip_timeline([]) == []


# ---- locate_clip (MP3 절대초 → (클립, 클립내 오프셋)) ----------------------
def test_locate_clip_into_middle_clip():
    clip, off = locate_clip(CLIPS13, 3600)
    assert clip["title"] == "학습하기"
    assert off == 3600 - 536           # 3064


def test_locate_clip_first_clip():
    clip, off = locate_clip(CLIPS13, 100)
    assert clip["title"] == "들어가기" and off == 100


def test_locate_clip_boundary_start_of_clip():
    # 경계: 정확히 클립 시작초는 그 클립의 오프셋 0
    clip, off = locate_clip(CLIPS13, 536)
    assert clip["title"] == "학습하기" and off == 0


def test_locate_clip_last_clip():
    clip, off = locate_clip(CLIPS13, 7000)
    assert clip["title"] == "정리하기" and off == 7000 - 6858


def test_locate_clip_out_of_range_none():
    assert locate_clip(CLIPS13, 99999) is None


# ---- _plan_renormalize (기존 노트 오형식 마커/임베드/파일명 교정 계획) -----
def test_plan_renormalize_rewrites_marker_embed_and_rename():
    md = ("### 나눗셈 🎬 [09:21:00]\n"
          "![[이산수학_13강_09-21-00.jpg]]\n"
          "본문\n")
    new_md, renames = _plan_renormalize(md, "이산수학", 13, 7209)
    assert "[00:09:21]" in new_md and "[09:21:00]" not in new_md
    assert "![[이산수학_13강_00-09-21.jpg]]" in new_md
    assert "![[이산수학_13강_09-21-00.jpg]]" not in new_md
    assert renames == [("이산수학_13강_09-21-00.jpg", "이산수학_13강_00-09-21.jpg")]
    assert "본문" in new_md


def test_plan_renormalize_keeps_valid_unchanged():
    md = ("### 소수 🎬 [01:05:00]\n"
          "![[이산수학_13강_01-05-00.jpg]]\n")
    new_md, renames = _plan_renormalize(md, "이산수학", 13, 7209)
    assert new_md == md and renames == []


def test_plan_renormalize_marker_without_embed():
    # 임베드가 없으면(캡처 실패) 마커만 교정, rename 없음
    md = "### x 🎬 [11:15:00]\n다음 줄은 임베드가 아님\n"
    new_md, renames = _plan_renormalize(md, "이산수학", 13, 7209)
    assert "[00:11:15]" in new_md
    assert renames == []


def test_plan_renormalize_no_duration_noop():
    md = "### x 🎬 [09:21:00]\n![[이산수학_13강_09-21-00.jpg]]\n"
    new_md, renames = _plan_renormalize(md, "이산수학", 13, None)
    assert new_md == md and renames == []
