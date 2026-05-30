"""summarize 모듈 순수 로직 단위 테스트 (Phase 5).

타임스탬프 변환 / 노트 파일명 / 요약 필요판정 / 타임스탬프 추출 / 프롬프트 빌더만 검증.
실제 Gemini 호출(업로드·생성)은 수동 검증(summarize_one.py).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from summarize import (  # noqa: E402
    build_prompt,
    extract_timestamps,
    needs_summary,
    note_filename,
    seconds_to_timestamp,
    timestamp_to_seconds,
)


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
