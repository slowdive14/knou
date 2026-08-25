"""ui_async 단위테스트 — 워커 스레드에서 부른 갱신이 루프를 깨우는가.

실측 증상: 진행 로그가 실시간으로 안 붙고 **창을 내렸다 올려야** 밀린 줄이
한꺼번에 나타났다. 원인은 Flet 0.85 의 전송 경로에 있다 —

    Session.patch_control → __send_message → conn.send_message
      → self.__send_queue.put_nowait(m)      # asyncio.Queue

`asyncio.Queue.put_nowait` 는 루프를 깨우지 않는다. 그래서 워커 스레드에서
page.update() 를 부르면 패치가 큐에만 쌓이고, 휠·리사이즈 같은 다른 사건이
루프를 깨워야 그제서야 나간다. page.run_task 는 run_coroutine_threadsafe 라
루프를 깨우므로 갱신 요청은 항상 그 통로로 보내야 한다.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui_async import make_updater  # noqa: E402


class _LoopPage:
    """run_task 를 가진 page 대역 — 코루틴을 즉시 돌려 준다."""

    def __init__(self):
        self.tasks = 0
        self.direct = 0

    def run_task(self, coro_fn, *a, **kw):
        self.tasks += 1
        asyncio.run(coro_fn(*a, **kw))

    def update(self):
        self.direct += 1


class _PlainPage:
    """run_task 가 없는 page(오프라인 테스트 대역)."""

    def __init__(self):
        self.direct = 0

    def update(self):
        self.direct += 1


class _DeferredPage(_LoopPage):
    """run_task 로 예약만 하고 아직 돌리지 않는 page(합치기 확인용)."""

    def __init__(self):
        super().__init__()
        self.queued = []

    def run_task(self, coro_fn, *a, **kw):
        self.tasks += 1
        self.queued.append(coro_fn)

    def flush(self):
        while self.queued:
            asyncio.run(self.queued.pop(0)())


# --- 루프를 깨우는 통로로 보낸다 --------------------------------------------
def test_update_goes_through_run_task():
    page = _LoopPage()
    make_updater(page)()
    assert page.tasks == 1        # run_task 를 거쳤다(루프가 깨어난다)
    assert page.direct == 1       # 그 안에서 실제 update 가 일어났다


def test_page_without_run_task_falls_back():
    page = _PlainPage()
    make_updater(page)()
    assert page.direct == 1


def test_none_page_is_safe():
    make_updater(None)()          # 예외 없이 지나가야 한다


# --- 연달아 부르면 한 번으로 합친다 -----------------------------------------
def test_bursts_are_coalesced():
    page = _DeferredPage()
    upd = make_updater(page)
    for _ in range(50):           # 로그가 쏟아지는 상황
        upd()
    assert page.tasks == 1        # 태스크 폭주 없이 한 번만 예약
    page.flush()
    assert page.direct == 1


def test_next_update_after_flush_is_scheduled_again():
    page = _DeferredPage()
    upd = make_updater(page)
    upd()
    page.flush()
    upd()                         # 다음 변경은 새로 예약되어야 한다
    assert page.tasks == 2


# --- 어떤 경우에도 실행을 죽이지 않는다 --------------------------------------
def test_run_task_failure_falls_back_to_direct_update():
    class _Broken(_LoopPage):
        def run_task(self, coro_fn, *a, **kw):
            raise RuntimeError("아직 루프가 없음")

    page = _Broken()
    make_updater(page)()
    assert page.direct == 1       # 직접 갱신으로 떨어졌다


def test_update_failure_is_swallowed():
    class _Dead:
        def update(self):
            raise RuntimeError("창이 닫힘")

    make_updater(_Dead())()       # 예외가 새어나오면 실패
