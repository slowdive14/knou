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

import re
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
NOTIFY_EVERY = 3       # 배경에서 이만큼 자리를 만들 때마다 화면에 반영

# 보이는 쪽 앞뒤로 이만큼만 실제 이미지를 채운다. 전 쪽을 채우면 큰 PDF 에서
# 전송량이 한계에 닿아 중간부터 안 내려간다(실측: 58쪽 중 41쪽에서 멈춤).
WINDOW = 4
# 화면용이라 JPEG 로 충분하다 — PNG 대비 70% 안팎으로 작아진다.
RENDER_FORMAT = "jpeg"
RENDER_QUALITY = 90


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


def parse_page_input(text, total: int):
    """쪽수 입력칸의 글자 → 0-based 쪽 인덱스. 못 읽으면 None.

    사람은 1부터 세므로 '42' 는 41번째다. 범위를 넘는 수는 **가장 가까운 쪽**
    으로 맞춘다(0 이나 999 를 넣어도 튕기지 않고 처음·마지막으로 간다).
    """
    s = str(text or "").strip()
    if not s or total <= 0:
        return None
    m = re.search(r"\d+", s)
    if not m:
        return None
    return clamp_page(int(m.group()) - 1, total)


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
    st = {"i": 0, "total": total, "loaded": 0, "drawn": 0, "closed": False,
          "w": float(width), "h": float(width) * aspect}

    # 쪽수를 직접 쳐서 뛰어갈 수 있게. 58쪽짜리를 화살표로 넘기면 너무 멀다.
    page_box = ft.TextField(
        value="1" if total else "", width=62, height=38, text_size=13,
        text_align=ft.TextAlign.CENTER, content_padding=6,
        keyboard_type=ft.KeyboardType.NUMBER,
        tooltip="쪽수를 입력하고 Enter",
        border_color=ft.Colors.with_opacity(.25, ft.Colors.ON_SURFACE))
    total_label = ft.Text(f"/ {total}" if total else "/ 0", size=12,
                          color=MUTE, font_family="Consolas")
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

    def _slot(i: int) -> ft.Control:
        """쪽 **자리**. 높이를 미리 잡아 두면 스크롤 길이가 처음부터 정확하다."""
        return ft.Container(
            width=st["w"], height=st["h"],
            bgcolor=ft.Colors.with_opacity(.04, ft.Colors.ON_SURFACE),
            border_radius=8,
        )

    def _image(i: int) -> ft.Control:
        w, h = st["w"], st["h"]
        return ft.Image(
            src=render_page(pdf_path, i, (w / max(pw, 1.0)) * RENDER_SHARPNESS,
                            fmt=RENDER_FORMAT, quality=RENDER_QUALITY),
            width=w, height=h, fit=ft.BoxFit.CONTAIN)

    def _add_pages(upto: int):
        """앞에서부터 upto 쪽까지 **자리**를 만든다(이미 있는 건 건너뜀)."""
        upto = min(int(upto), st["total"])
        while st["loaded"] < upto and not st["closed"]:
            stack.controls.append(_slot(st["loaded"]))
            st["loaded"] += 1

    def _window(center: int):
        """보이는 쪽 앞뒤 WINDOW 만큼만 실제로 그리고, 멀어진 쪽은 비운다.

        ⚠️ 예전에는 전 쪽을 이미지로 채웠는데, 58쪽짜리 슬라이드에서 **41쪽에서
        더 안 내려갔다**(실측). 41쪽까지가 6.44MB 라 전송 한계에 닿은 것으로
        보인다. 자리는 다 만들어 두고 이미지만 근처에 채우면, 쪽수가 몇이든
        오가는 양은 창 크기(약 9쪽)로 일정하다.
        """
        if st["closed"]:
            return
        lo = max(0, int(center) - WINDOW)
        hi = min(st["total"], int(center) + WINDOW + 1)
        drawn = 0
        for i, c in enumerate(stack.controls):
            want = lo <= i < hi
            has = getattr(c, "content", None) is not None
            if want and not has:
                c.content = _image(i)
            elif not want and has:
                c.content = None        # 멀어진 쪽은 비워 전송량을 돌려준다
            if want:
                drawn += 1
        st["drawn"] = drawn

    def _fill_rest():
        """나머지 쪽 **자리**를 배경에서 이어 붙인다 — 스크롤이 막히지 않게."""
        while st["loaded"] < st["total"] and not st["closed"]:
            _add_pages(st["loaded"] + NOTIFY_EVERY)
            note.value = loading_text(st["loaded"], st["total"])
            _upd()
        if not st["closed"]:
            note.value = ""
            _window(st["i"])
            _upd()

    def _mark(i: int):
        """지금 보는 쪽을 화면 곳곳에 반영한다(쪽 표시·입력칸·그리는 창)."""
        st["i"] = clamp_page(i, st["total"])
        page_box.value = str(st["i"] + 1) if st["total"] else ""
        _window(st["i"])

    def on_scroll(e):
        i = visible_page(getattr(e, "pixels", 0), st["h"], st["total"])
        if i != st["i"]:
            _mark(i)
            _upd()

    stack.on_scroll = on_scroll

    def jump_to(i: int):
        """그 쪽으로 옮기고 화면도 거기로 스크롤한다."""
        _mark(i)
        _upd()
        _scroll(page_offset(st["i"], st["h"]))

    def on_page_input(e=None):
        """쪽수 입력 → 그 쪽으로. 못 읽은 입력은 지금 쪽으로 되돌린다."""
        i = parse_page_input(getattr(page_box, "value", ""), st["total"])
        if i is None:                   # 빈 칸·글자 → 원래 쪽 번호를 되살린다
            page_box.value = str(st["i"] + 1) if st["total"] else ""
            _upd()
            return
        jump_to(i)

    page_box.on_submit = on_page_input
    page_box.on_blur = on_page_input    # 엔터를 안 쳐도 칸을 벗어나면 이동

    def goto(delta: int):
        def _h(_=None):
            jump_to(st["i"] + delta)
        return _h

    tools = ft.Row(
        [
            ft.IconButton(ft.Icons.KEYBOARD_ARROW_UP, tooltip="이전 쪽",
                          on_click=goto(-1)),
            page_box,
            total_label,
            ft.IconButton(ft.Icons.KEYBOARD_ARROW_DOWN, tooltip="다음 쪽",
                          on_click=goto(1)),
            ft.Container(expand=True),
            ft.Text("스크롤로 넘기거나 쪽수를 입력하세요", size=11, color=MUTE),
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
        _add_pages(eager)                       # 앞 몇 쪽 자리부터
        _window(0)                              # 보이는 곳은 바로 그린다
        note.value = loading_text(st["loaded"], st["total"])
        if background and st["loaded"] < total:
            threading.Thread(target=_fill_rest, daemon=True).start()
        elif not background:
            _add_pages(total)
            _window(st["i"])
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
