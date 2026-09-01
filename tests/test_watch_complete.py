"""영상 완청 판정 — '못 읽음'을 '다 봤음'으로 오인하지 않는가.

실측 사고(logs/run_20260821_080808.log · 컴퓨터구조 10강, 67분 영상):

    12:50:00  {'pos': 7.28, 'dur': 4039.24, 'rate': 1, 'paused': False}
    12:50:16  {'evalErr': 'Target page, context or browser has been closed'}
    12:50:31  {'evalErr': '...closed'}
    12:50:31  ✓ watch: 완료          ← 7초만 보고 '완료'로 기록

플레이어 창이 죽어 상태를 못 읽자, dur 이 None 이라는 이유로 '재생 후 <video>
언로드'(=짧은 클립 완청) 규칙에 걸렸다. 그리고 ok=True 로 기록돼 그 차시는
다시 시도조차 되지 않았다(학습현황에 주황 '실행함'으로 남음).

고친 규칙 두 가지:
  - 상태를 못 읽은 것(evalErr)은 완청 근거가 아니다 → 연속되면 실패로 끝낸다
  - 언로드로 완청을 인정하려면 **길이의 90%까지는** 가 있어야 한다
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import watch  # noqa: E402
from watch import NEAR_END_RATIO, READ_FAIL_LIMIT, _play_until_end  # noqa: E402


def _run(monkeypatch, states, budget=60.0):
    """주어진 상태 시퀀스를 돌려주는 가짜 플레이어로 완청 판정을 돌린다."""
    seq = list(states)
    seen = []

    def _state(_popup, _idx):
        seen.append(1)
        return seq.pop(0) if seq else {"evalErr": "no more"}

    monkeypatch.setattr(watch, "_clip_state", _state)
    monkeypatch.setattr(watch, "_dismiss_quiz", lambda *a, **kw: None)
    return _play_until_end(object(), 0, 2.0, budget, poll=0), len(seen)


# --- 이번 사고 재현 ---------------------------------------------------------
def test_closed_player_is_not_completion(monkeypatch):
    """창이 죽은 뒤의 evalErr 연속 → 완청이 아니라 실패."""
    states = [{"pos": 7.28, "dur": 4039.24, "paused": False, "ended": False}]
    states += [{"evalErr": "Target page, context or browser has been closed"}] * 5
    ok, _ = _run(monkeypatch, states)
    assert ok is False


def test_read_failures_stop_early(monkeypatch):
    # 죽은 창을 예산이 끝날 때까지 붙들고 있지 않는다
    states = [{"pos": 5.0, "dur": 4000.0}] + [{"evalErr": "closed"}] * 20
    ok, polls = _run(monkeypatch, states)
    assert ok is False
    assert polls <= 1 + READ_FAIL_LIMIT


def test_single_read_failure_recovers(monkeypatch):
    # 한 번 튄 것으로 실패시키면 안 된다 — 다시 읽히면 계속 본다
    states = [
        {"pos": 10.0, "dur": 100.0},
        {"evalErr": "hiccup"},
        {"pos": 60.0, "dur": 100.0},
        {"pos": 99.5, "dur": 100.0, "ended": True},
    ]
    ok, _ = _run(monkeypatch, states)
    assert ok is True


# --- 언로드 완청은 '끝 근처'에서만 인정 --------------------------------------
def test_unload_near_the_end_is_completion(monkeypatch):
    # 끝까지 보고 <video> 가 사라진 정상 케이스는 그대로 완청
    states = [
        {"pos": 95.0, "dur": 100.0},
        {"gone": True},
        {"gone": True},
    ]
    ok, _ = _run(monkeypatch, states)
    assert ok is True


def test_unload_far_from_the_end_is_not_completion(monkeypatch):
    # 7초 보고 사라진 67분 영상 — 완청이 아니다
    states = [{"pos": 7.0, "dur": 4039.0}] + [{"gone": True}] * 4
    ok, _ = _run(monkeypatch, states, budget=0.4)
    assert ok is False


def test_unload_without_known_duration_still_allowed(monkeypatch):
    # 길이를 한 번도 못 잰 클립은 예전 동작 유지(과하게 막지 않는다)
    states = [{"pos": 30.0, "dur": None}] * 4
    ok, _ = _run(monkeypatch, states)
    assert ok is True


# --- 원래 되던 완청 경로는 그대로 -------------------------------------------
def test_ended_flag_completes(monkeypatch):
    ok, _ = _run(monkeypatch, [{"pos": 50.0, "dur": 100.0, "ended": True}])
    assert ok is True


def test_reaching_the_end_completes(monkeypatch):
    ok, _ = _run(monkeypatch, [{"pos": 99.5, "dur": 100.0}])
    assert ok is True


def test_near_end_ratio_is_strict_enough():
    # 규칙이 다시 느슨해지지 않게 못박는다
    assert 0.5 < NEAR_END_RATIO <= 1.0
    assert READ_FAIL_LIMIT >= 2        # 한 번 튄 것으로 실패시키지 않는다
