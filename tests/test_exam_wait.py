"""형성평가 프레임 대기 단위테스트 — '없음'으로 단정하기 전에 충분히 기다리는가.

실측 사례(logs/run_20260819_152412.log): 2초 고정 대기 뒤 한 번만 확인해
'형성평가 없음(skip)' 으로 **완료 기록**되면, 그 차시는 이후 실행에서 영영
건너뛰어진다(should_run_stage 가 완료로 보기 때문). 늦게 붙는 박스를 잡도록
폴링으로 바꾼 뒤의 동작을 고정한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exercise import (  # noqa: E402
    EXAM_POLL_MS,
    EXAM_WAIT_MS,
    wait_for_exam_frame,
)


class _Popup:
    """wait_for_timeout 호출만 기록하는 가짜 팝업(실제 대기 없음)."""

    def __init__(self, fail_on_wait=False):
        self.waits: list[int] = []
        self.fail_on_wait = fail_on_wait

    def wait_for_timeout(self, ms):
        if self.fail_on_wait:
            raise RuntimeError("창이 닫힘")
        self.waits.append(ms)


def _finder_after(n: int, frame="FRAME"):
    """n 번째 확인부터 프레임을 돌려주는 finder(그 전에는 None)."""
    calls = {"n": 0}

    def find(_popup):
        calls["n"] += 1
        return frame if calls["n"] >= n else None

    find.calls = calls  # type: ignore[attr-defined]
    return find


def test_found_immediately_does_not_wait():
    popup = _Popup()
    assert wait_for_exam_frame(popup, finder=_finder_after(1)) == "FRAME"
    assert popup.waits == []          # 이미 있으면 한 번도 기다리지 않는다


def test_found_late_is_still_found():
    # 예전 코드(1회 확인)라면 '없음'으로 단정했을 상황
    popup = _Popup()
    find = _finder_after(5)
    assert wait_for_exam_frame(popup, finder=find) == "FRAME"
    assert len(popup.waits) == 4      # 4번 기다린 뒤 5번째에 발견


def test_absent_returns_none_after_full_timeout():
    popup = _Popup()
    find = _finder_after(9999)
    assert wait_for_exam_frame(popup, timeout_ms=5000, poll_ms=1000,
                               finder=find) is None
    assert popup.waits == [1000] * 5  # 끝까지 기다려 보고서야 '없음'


def test_polls_more_than_once_by_default():
    # 기본 설정이 다시 '한 번만 보고 단정'으로 퇴행하지 않도록 못박는다
    assert EXAM_WAIT_MS >= 10000
    assert 0 < EXAM_POLL_MS <= EXAM_WAIT_MS // 5


def test_closed_popup_stops_waiting():
    popup = _Popup(fail_on_wait=True)
    assert wait_for_exam_frame(popup, finder=_finder_after(9999)) is None


def test_zero_timeout_checks_once():
    popup = _Popup()
    find = _finder_after(9999)
    assert wait_for_exam_frame(popup, timeout_ms=0, finder=find) is None
    assert find.calls["n"] == 1 and popup.waits == []
