"""summarize 모듈 순수 로직 단위 테스트 (Phase 5).

타임스탬프 변환 / 노트 파일명 / 요약 필요판정 / 타임스탬프 추출 / 프롬프트 빌더만 검증.
실제 Gemini 호출(업로드·생성)은 수동 검증(summarize_one.py).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from summarize import (  # noqa: E402
    _block_reason,
    _finish_reason,
    _resp_text,
    _strip_code_fence,
    build_prompt,
    extract_timestamps,
    needs_summary,
    normalize_markdown_timestamps,
    normalize_ts_seconds,
    note_filename,
    save_summary,
    seconds_to_timestamp,
    timestamp_to_seconds,
)
from types import SimpleNamespace  # noqa: E402


# ---- Gemini 응답 파싱 헬퍼(빈 응답 견고화) --------------------------------
def test_strip_code_fence():
    assert _strip_code_fence("```markdown\n# 제목\n```") == "# 제목"
    assert _strip_code_fence("# 제목") == "# 제목"
    assert _strip_code_fence("") == ""


def test_resp_text_prefers_text_attr():
    resp = SimpleNamespace(text="```\n본문\n```")
    assert _resp_text(resp) == "본문"


def test_resp_text_falls_back_to_parts():
    # resp.text 가 비어도 candidates parts 에서 본문을 모은다
    part = SimpleNamespace(text="조각본문")
    content = SimpleNamespace(parts=[part])
    cand = SimpleNamespace(content=content)
    resp = SimpleNamespace(text="", candidates=[cand])
    assert _resp_text(resp) == "조각본문"


def test_resp_text_empty_when_nothing():
    resp = SimpleNamespace(text=None, candidates=[])
    assert _resp_text(resp) == ""


def test_finish_reason_and_block_reason():
    cand = SimpleNamespace(finish_reason="MAX_TOKENS")
    resp = SimpleNamespace(candidates=[cand],
                           prompt_feedback=SimpleNamespace(block_reason=None))
    assert _finish_reason(resp) == "MAX_TOKENS"
    assert _block_reason(resp) is None
    assert _finish_reason(SimpleNamespace()) == "?"


# ---- timestamp 변환 -------------------------------------------------------
def test_timestamp_to_seconds_hms():
    assert timestamp_to_seconds("01:23:45") == 5025
    assert timestamp_to_seconds("00:01:30") == 90


def test_timestamp_to_seconds_ms():
    assert timestamp_to_seconds("12:05") == 725
    assert timestamp_to_seconds("1:02:03") == 3723


def test_timestamp_to_seconds_invalid():
    assert timestamp_to_seconds("") == 0
    assert timestamp_to_seconds("abc") == 0


def test_seconds_to_timestamp():
    assert seconds_to_timestamp(5025) == "01:23:45"
    assert seconds_to_timestamp(90) == "00:01:30"
    assert seconds_to_timestamp(0) == "00:00:00"


# ---- note_filename --------------------------------------------------------
def test_note_filename():
    assert note_filename("이산수학", 1, "이산수학의 개요") == "이산수학 1강 - 이산수학의 개요.md"


def test_note_filename_sanitizes():
    # 제목에 금지문자가 있어도 안전한 파일명
    out = note_filename("이산수학", 7, "함수/관계: 정리")
    assert "/" not in out and ":" not in out
    assert out.startswith("이산수학 7강 - ")
    assert out.endswith(".md")


# ---- needs_summary --------------------------------------------------------
def test_needs_summary_missing(tmp_path):
    assert needs_summary(tmp_path / "x.md") is True


def test_needs_summary_empty(tmp_path):
    p = tmp_path / "e.md"
    p.write_text("", encoding="utf-8")
    assert needs_summary(p) is True


def test_needs_summary_existing(tmp_path):
    p = tmp_path / "ok.md"
    p.write_text("# 요약\n내용", encoding="utf-8")
    assert needs_summary(p) is False


# ---- extract_timestamps ---------------------------------------------------
MD = """# 이산수학 1강 - 이산수학의 개요

## 개요
### 이산수학의 정의 🎬 [00:01:30] (교재 p.3)
이산적인 구조를 다루는 수학.

### 집합의 개념 🎬 [12:05]
원소의 모임.

- 명제와 논리 🎬 [1:02:03] 설명
- 타임스탬프 없는 항목
"""


def test_extract_timestamps_finds_all():
    ts = extract_timestamps(MD)
    secs = [t["seconds"] for t in ts]
    assert secs == [90, 725, 3723]


def test_extract_timestamps_has_label_and_ts():
    ts = extract_timestamps(MD)
    first = ts[0]
    assert first["timestamp"] == "00:01:30"
    assert "이산수학의 정의" in first["label"]
    # 마크다운 마커(#, 🎬, [ ])는 라벨에서 제거
    assert "🎬" not in first["label"]
    assert "[" not in first["label"]


def test_extract_timestamps_dedups_by_seconds():
    md = "a 🎬 [00:10]\nb 🎬 [00:10]\n"
    ts = extract_timestamps(md)
    assert len(ts) == 1


def test_extract_timestamps_empty():
    assert extract_timestamps("타임스탬프 없음") == []


# ---- build_prompt ---------------------------------------------------------
def test_build_prompt_mentions_key_requirements():
    p = build_prompt("이산수학", 1, "이산수학의 개요")
    assert "이산수학" in p and "1강" in p
    # 핵심 요구: 타임스탬프(HH:MM:SS), 음성 기준 근사치, 마크다운
    assert "[HH:MM:SS]" in p or "HH:MM:SS" in p
    assert "근사" in p or "근사치" in p


# ---- normalize_ts_seconds (Gemini 'MM:SS:00' 오형식 교정) ------------------
def test_normalize_ts_seconds_misformatted():
    assert normalize_ts_seconds(33660, 7209) == 561      # 09:21:00 → 9분21초
    assert normalize_ts_seconds(208740, 7209) == 3479    # 57:59:00 → 57분59초


def test_normalize_ts_seconds_valid_unchanged():
    assert normalize_ts_seconds(3600, 7209) == 3600      # 진짜 1시간
    assert normalize_ts_seconds(7260, 7209) == 7260      # 60s 이내 초과 → 보존


def test_normalize_ts_seconds_no_duration_unchanged():
    assert normalize_ts_seconds(33660, 0) == 33660
    assert normalize_ts_seconds(33660, None) == 33660


# ---- normalize_markdown_timestamps ----------------------------------------
def test_normalize_markdown_timestamps_fixes_misformatted():
    md = "### 나눗셈 정리 🎬 [09:21:00] (교재 p.3)\n본문\n"
    out = normalize_markdown_timestamps(md, 7209)
    assert "[00:09:21]" in out          # 9h21m → 9m21s 로 교정
    assert "[09:21:00]" not in out
    assert "나눗셈 정리" in out and "(교재 p.3)" in out


def test_normalize_markdown_timestamps_keeps_valid():
    md = "### 소수정리 🎬 [01:05:00]\n본문\n"
    out = normalize_markdown_timestamps(md, 7209)
    assert out == md                     # 1시간5분 = 정상 → 멱등


def test_normalize_markdown_timestamps_no_duration_noop():
    md = "### x 🎬 [09:21:00]\n"
    assert normalize_markdown_timestamps(md, None) == md


def test_normalize_markdown_timestamps_mixed():
    md = ("### A 🎬 [09:21:00]\n"
          "### B 🎬 [01:05:00]\n")
    out = normalize_markdown_timestamps(md, 7209)
    assert "[00:09:21]" in out           # 오형식만 교정
    assert "[01:05:00]" in out           # 정상은 유지


# ---- save_summary (저장 전 마커 교정 + json 동기화) -----------------------
def test_save_summary_normalizes_md_and_json(tmp_path):
    md = "# 이산수학 13강 - 정수론\n### 나눗셈 🎬 [09:21:00]\n본문\n"
    res = save_summary(md, tmp_path, "이산수학", 13, "정수론", duration=7209)
    note = Path(res["md"])
    saved = note.read_text(encoding="utf-8")
    assert "[00:09:21]" in saved and "[09:21:00]" not in saved
    # 사이드카 json 도 교정된 초로 저장
    ts = json.loads(Path(res["timestamps"]).read_text(encoding="utf-8"))
    secs = [t["seconds"] for t in ts["timestamps"]]
    assert secs == [561]


def test_save_summary_without_duration_unchanged(tmp_path):
    md = "# t\n### x 🎬 [09:21:00]\n"
    res = save_summary(md, tmp_path, "이산수학", 13, "정수론")
    saved = Path(res["md"]).read_text(encoding="utf-8")
    assert "[09:21:00]" in saved          # duration 없으면 교정 안 함
