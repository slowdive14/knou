"""[ui_async] 워커 스레드에서도 화면이 **즉시** 갱신되게 하는 다리.

Flet 0.85 의 `page.update()` 는 **이벤트 루프 스레드에서 불러야** 곧바로 화면에
반영된다. 소스를 따라가면 이유가 분명하다:

    Session.patch_control → __send_message → conn.send_message
      → self.__send_queue.put_nowait(m)      # __send_queue 는 asyncio.Queue

`asyncio.Queue.put_nowait` 는 **루프를 깨우지 않는다**. 다른 스레드에서 부르면
패치가 큐에 쌓이기만 하고, 마우스 휠·창 크기 변경처럼 루프를 깨우는 다른 사건이
있어야 그제서야 한꺼번에 전송된다.
  → 실측 증상: 진행 로그가 실시간으로 안 붙고, **창을 내렸다 올리면** 밀린 줄이
    한꺼번에 나타난다.

`page.run_task` 는 `asyncio.run_coroutine_threadsafe` 로 루프에 넣으므로 루프를
깨운다. 그래서 갱신은 항상 이 통로로 보낸다.

  - make_updater(page) : 어느 스레드에서 불러도 안전한 갱신 함수를 만들어 준다

여러 번 연달아 부르면 **한 번으로 합친다**(로그가 쏟아질 때 태스크 폭주 방지).
page 가 없거나(오프라인 테스트) run_task 가 없으면 그냥 page.update() 로 떨어진다.
"""
from __future__ import annotations


def make_updater(page):
    """이 페이지를 갱신하는 호출 가능 객체를 만든다(스레드 안전 · 합쳐짐).

    반환된 함수는 인자 없이 부르면 되고, 어떤 예외도 밖으로 내보내지 않는다
    (창이 닫히는 중이거나 아직 안 붙었을 때 실행이 죽지 않게).
    """
    pending = {"on": False}

    def _direct():
        try:
            page.update()
        except Exception:  # noqa: BLE001 - 창이 닫혔거나 아직 안 붙음
            pass

    async def _flush():
        pending["on"] = False          # 먼저 내려야 이후 변경도 다음 번에 실린다
        _direct()

    def update():
        if page is None:
            return
        if pending["on"]:              # 이미 예약됨 — 그 한 번에 같이 실린다
            return
        run_task = getattr(page, "run_task", None)
        if run_task is None:           # 가짜 page(테스트) 등
            _direct()
            return
        pending["on"] = True
        try:
            run_task(_flush)
        except Exception:  # noqa: BLE001 - 아직 루프가 없으면(붙기 전) 직접 갱신
            pending["on"] = False
            _direct()

    return update
