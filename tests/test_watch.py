"""watch 모듈 time-budget 순수 로직 단위 테스트.

실제 재생/배속/완료판정의 시간 예산 계산만 검증한다.
(브라우저 제어는 수동 검증)
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discover import Lecture  # noqa: E402
from watch import (  # noqa: E402
    ALLOWED_SPEEDS,
    clamp_speed,
    is_complete,
    needs_topup,
    remaining_minutes,
    wall_clock_seconds,
)


def _lec(watched, total, done=False, prog=0, has_video=True):
    return Lecture(
        seq=1, name="x", watched_min=watched, total_min=total, prog_rt=prog,
        video_done=done, exam_done=False, has_video=has_video, cnts_tc="01",
        sbjt_id="S", toc_no="T", atlc_no="A",
        enc_sbjt_id="", enc_toc_no="", enc_atlc_no="", video_url="")


def test_remaining_minutes():
    assert remaining_minutes(2, 105) == 103
    assert remaining_minutes(55, 55) == 0
    assert remaining_minutes(60, 55) == 0   # 음수 방지
    assert remaining_minutes(0, 0) == 0


def test_wall_clock_seconds_with_speed_and_buffer():
    # 100분 남음, 2배속, 버퍼 12% → 100*60/2*1.12 = 3360초
    assert wall_clock_seconds(100, 2.0, buffer=0.12) == pytest.approx(3360.0)
    # 버퍼 0, 1배속 → 그대로 초
    assert wall_clock_seconds(10, 1.0, buffer=0.0) == pytest.approx(600.0)


def test_wall_clock_seconds_zero_remaining():
    assert wall_clock_seconds(0, 2.0) == 0.0


def test_wall_clock_seconds_invalid_speed_falls_back():
    # 0 이하 배속은 1.0으로 처리(0 division 방지)
    assert wall_clock_seconds(10, 0, buffer=0.0) == 600.0


def test_clamp_speed():
    assert clamp_speed(2.0) == 2.0
    assert clamp_speed(2.5) == 2.0       # 최대 2.0
    assert clamp_speed(0.1) == 0.5       # 최소 0.5
    assert clamp_speed(1.3) in ALLOWED_SPEEDS  # 허용값으로 스냅
    assert clamp_speed(1.4) == 1.4


def test_is_complete_uses_video_done():
    assert is_complete(_lec(55, 55, done=True)) is True
    assert is_complete(_lec(2, 105, done=False, prog=50)) is False
    # prog_rt 는 신뢰 불가 → done 플래그가 없으면 100%여도 완료 아님
    assert is_complete(_lec(105, 105, done=False, prog=100)) is False


def test_needs_topup():
    # 재생 후에도 미완료면 top-up 필요
    assert needs_topup(_lec(50, 105, done=False, prog=50)) is True
    assert needs_topup(_lec(105, 105, done=True, prog=100)) is False
