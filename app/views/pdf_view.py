"""[pdf_view] 강의록 PDF — 앱 창 안에서 스크롤로 넘겨 보는 뷰어.

Flet 에 PDF 컨트롤이 없어 PyMuPDF(pdf_render)로 페이지를 그려 `ft.Image` 에 싣는다.
페이지를 세로로 쌓아 **스크롤로 넘기는 것이 기본**이고, 이전/다음 버튼은 그 위치로
스크롤해 준다.

  - page_label(i, total)            : '3 / 51' (순수)
  - visible_page(pixels, h, total)  : 스크롤 위치 → 지금 보고 있는 쪽 (순수)
  - page_offset(i, h)               : 그 쪽의 스크롤 위치 (순수)
  - build_pdf_view(...)             : 뷰어 화면(오프라인 테스트 가능)

실측으로 확인한 Flet 0.85 의 함정들 — 다시 밟지 않도록 여기 적어둔다:
  ⚠️ 화면 갱신은 `page.update()` 로. 컨트롤 개별 `.update()` 는 다이얼로그 안에서
     조용히 실패해 '버튼을 눌러도 아무 일 없는' 증상이 된다.
  ⚠️ `scroll_to` 는 **코루틴**이라 그냥 부르면 아무 일도 안 일어난다 → `run_task`.
  ⚠️ `scroll_to(scroll_key=…)` 는 동작하지 않는다 → **offset** 으로 이동한다.
  ⚠️ AlertDialog 안에 스크롤 목록을 넣으면 **다이얼로그가 휠을 가져간다**(실측:
     휠을 굴려도 목록의 pixels 가 125 에서 멈춤) → 뷰어는 **화면 전체**로 띄운다.
  ⚠️ **배경 스레드에서 부른 page.update() 는 즉시 반영되지 않는다**(루프를 안 깨움)
     → `ui_async.make_updater` 를 거친다.

쪽이 많으면(43쪽 ≈ 4.7초) 여는 순간 다 그릴 수 없다. 그래서 앞 두 쪽만 먼저 그려
바로 띄우고, 나머지는 **배경 스레드**가 이어 붙인다(스크롤이 중간에 막히지 않게).
"""
from __future__ import annotations

import threading

import flet as ft

from pdf_render import available, clamp_page, page_count, page_size, render_page
from ui_async import make_updater

MINT = "#00a37a"
MUTE = "#8b9198"

# 렌더 선명도 — 표시 폭 대비 이 배로 그려 글자가 뭉개지지 않게.
RENDER_SHARPNESS = 1.4
PAGE_GAP = 12          # 페이지 사이 여백(스크롤 위치 계산에 포함)
EAGER_PAGES = 2        # 열자마자 보여줄 쪽(나머지는 배경에서)
NOTIFY_EVERY = 3       # 배경에서 이만큼 그릴 때마다 화면에 반영


def page_label(index: int, total: int) -> str:
    """0-based 페이지 인덱스 → '3 / 51'(빈 문서면 '0 / 0')."""
    if total <= 0:
        return "0 / 0"
    return f"{clamp_page(index, total) + 1} / {total}"


def page_offset(index: int, page_height: float) -> float:
    """그 쪽이 시작되는 스크롤 위치(px)."""
    return max(0.0, float(index) * (float(page_height) + PAGE_GAP))


def visible_page(pixels, page_height: float, total: int) -> int:
    """세로 스크롤 위치 → 지금 화면에 있는 쪽(0-based).

    페이지 높이가 모두 같다는 전제(강의록 슬라이드) — 위치/한쪽높이로 계산한다.
    """
    if total <= 0 or not page_height:
        return 0
    try:
        idx = int(float(pixels) / (float(page_height) + PAGE_GAP) + 0.35)
    except (TypeError, ValueError):
        return 0
    return clamp_page(idx, total)


def loading_text(done: int, total: int) -> str:
    """배경 렌더 진행 안내(다 되면 빈 문자열)."""
    if total <= 0 or done >= total:
        return ""
    return f"{done}/{total}쪽 준비 중… (준비된 쪽까지 먼저 볼 수 있어요)"


def build_pdf_view(pdf_path, title: str = "강의록", on_back=None,
                   on_fallback=None, page=None, width: int = 820,
                   eager: int = EAGER_PAGES, background: bool = True):
    """PDF 뷰어 화면 → (컨트롤, 상태 dict). page 없이도 만들 수 있다(테스트용).

    다이얼로그가 아니라 **화면 전체**를 쓴다 — 스크롤러가 하나뿐이라 휠이 그대로
    페이지 목록으로 간다. background=False 면 배경 스레드 없이 전부 그린다.
    """
    total = page_count(pdf_path)
    pw, ph = page_size(pdf_path)
    aspect = (ph / pw) if pw else 1.4
    st = {"i": 0, "total": total, "loaded": 0, "closed": False,
          "w": float(width), "h": float(width) * aspect}

    label = ft.Text(page_label(0, total), size=12, color=MUTE,
                    font_family="Consolas")
    note = ft.Text("", size=12, color=MUTE)
    stack = ft.Column(spacing=PAGE_GAP, scroll=ft.ScrollMode.AUTO, expand=True)

    # 화면 갱신은 페이지 단위로 — 컨트롤 개별 update() 는 다이얼로그에서 실패한다.
    # 배경 스레드(_fill_rest)에서도 부르므로 루프를 깨우는 통로로 보낸다
    # (그냥 page.update() 하면 다른 사건이 있어야 반영된다 — ui_async 설명 참고).
    _upd = make_updater(page)

    def _scroll(offset: float):
        """scroll_to 는 코루틴이라 run_task 로 돌리고, 키가 아닌 offset 으로 옮긴다."""
        if page is None:
            return
        try:
            page.run_task(stack.scroll_to, offset=max(0.0, offset), duration=200)
        except Exception:  # noqa: BLE001
            pass

    def _page_control(i: int) -> ft.Control:
        w, h = st["w"], st["h"]
        return ft.Container(
            content=ft.Image(
                src=render_page(pdf_path, i, (w / max(pw, 1.0)) * RENDER_SHARPNESS),
                width=w, height=h, fit=ft.BoxFit.CONTAIN),
            width=w, height=h,
            bgcolor=ft.Colors.with_opacity(.04, ft.Colors.ON_SURFACE),
            border_radius=8,
        )

    def _add_pages(upto: int):
        """앞에서부터 upto 쪽까지 그려 붙인다(이미 그린 건 건너뜀)."""
        upto = min(int(upto), st["total"])
        while st["loaded"] < upto and not st["closed"]:
            stack.controls.append(_page_control(st["loaded"]))
            st["loaded"] += 1

    def _fill_rest():
        """나머지 쪽을 배경에서 이어 붙인다 — 스크롤이 중간에 막히지 않게."""
        while st["loaded"] < st["total"] and not st["closed"]:
            _add_pages(st["loaded"] + NOTIFY_EVERY)
            note.value = loading_text(st["loaded"], st["total"])
            _upd()
        if not st["closed"]:
            note.value = ""
            _upd()

    def on_scroll(e):
        i = visible_page(getattr(e, "pixels", 0), st["h"], st["total"])
        if i != st["i"]:
            st["i"] = i
            label.value = page_label(i, st["total"])
            _upd()

    stack.on_scroll = on_scroll

    def goto(delta: int):
        def _h(_=None):
            st["i"] = clamp_page(st["i"] + delta, st["total"])
            label.value = page_label(st["i"], st["total"])
            _upd()
            _scroll(page_offset(st["i"], st["h"]))
        return _h

    tools = ft.Row(
        [
            ft.IconButton(ft.Icons.KEYBOARD_ARROW_UP, tooltip="이전 쪽",
                          on_click=goto(-1)),
            label,
            ft.IconButton(ft.Icons.KEYBOARD_ARROW_DOWN, tooltip="다음 쪽",
                          on_click=goto(1)),
            ft.Container(expand=True),
            ft.Text("스크롤로 넘겨 보세요", size=11, color=MUTE),
            ft.TextButton("기본 프로그램으로 열기", icon=ft.Icons.OPEN_IN_NEW,
                          on_click=(lambda e: on_fallback()) if on_fallback else None),
        ],
        spacing=4, vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    if not available():
        note.value = ("앱 안 PDF 보기에는 PyMuPDF 가 필요합니다 "
                      "(pip install pymupdf).")
    elif total <= 0:
        note.value = "PDF 를 열 수 없습니다(손상되었거나 암호가 걸린 파일)."
    else:
        _add_pages(eager)                       # 앞 몇 쪽은 즉시
        note.value = loading_text(st["loaded"], st["total"])
        if background and st["loaded"] < total:
            threading.Thread(target=_fill_rest, daemon=True).start()
        elif not background:
            _add_pages(total)
            note.value = ""

    header = ft.Row(
        [
            ft.TextButton("뒤로", icon=ft.Icons.ARROW_BACK,
                          on_click=(lambda e: on_back()) if on_back else None),
            ft.Text(title, size=15, weight=ft.FontWeight.BOLD, no_wrap=True,
                    overflow=ft.TextOverflow.ELLIPSIS, expand=True),
        ],
        spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )

    view = ft.Column([header, tools, note, stack], spacing=8, expand=True)
    return view, st
