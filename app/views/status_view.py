"""[status_view] 학습 현황 — 앱 안에서 보는 과목·차시별 현황 화면.

생성 HTML(status_html)과 같은 내용을 Flet 컨트롤로 직접 그린다 → 브라우저 창이
따로 뜨지 않고 앱 창 하나에서 끝난다. 줄마다 놓인 버튼이 각자 알맞은 곳으로 보낸다:

  · 예습노트 → 옵시디언(켜져 있으면 그 창에서, 꺼져 있으면 띄운 뒤)
  · 강의록   → 앱 안 PDF 뷰어(pdf_view)
  · MP3      → 윈도우 기본 프로그램
  · 형성평가 → 앱 안 퀴즈 화면(on_open_quiz 콜백)

데이터는 status_page.collect_status() 를 그대로 쓴다(로그인·네트워크 없음).
"""
from __future__ import annotations

from pathlib import Path

import flet as ft

from open_target import open_path
from status_page import collect_status, default_status_path, snapshot_time
from status_html import fmt_when

# 생성 HTML 과 같은 색 언어(민트=완료, 애프리콧=진행중)
MINT = "#00a37a"
MINT_BG = "#e3f6ef"
APRI = "#d98324"
APRI_BG = "#fbf0df"
MUTE = "#8b9198"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = PROJECT_ROOT / "lectures.json"
STATE_PATH = PROJECT_ROOT / "state.json"


# ---------------------------------------------------------------------------
# 순수 조각 (오프라인 테스트 가능)
# ---------------------------------------------------------------------------
_KINDS = {
    # 종류 → (완료 필드, 실행 기록 필드, 갱신 후 실행 필드, 완료 문구)
    "watch": ("video_done", "watch_run", "watch_new", "이수완료"),
    "exam": ("exam_done", "exam_run", "exam_new", "완료"),
}


def status_label(row: dict, kind: str = "watch") -> tuple[str, str]:
    """차시 한 줄의 상태 → (표시문구, 색종류). 색종류: done|fresh|wait|none.

    HTML 페이지와 판정 규칙을 맞춘다 — 목록 스냅샷 이후에 실행한 건 따로 표시
    (LMS 가 아직 모르는 상태라 '미완료'로 보이는 게 당연하므로).
    """
    done_f, ran_f, new_f, done_text = _KINDS.get(kind, _KINDS["watch"])
    if row.get(done_f):
        return (done_text, "done")
    if row.get(ran_f) and row.get(new_f):
        return ("실행함*", "fresh")
    if row.get(ran_f):
        return ("실행함", "wait")
    return ("", "none")


def summary_text(courses) -> str:
    """머리말 한 줄 — 몇 과목 몇 차시, 이수·노트·형성평가 몇 개."""
    from status_html import overall_stats
    t = overall_stats(courses)
    return (f"{len(list(courses))}과목 · {t['total']}차시 · 이수 {t['watched']} · "
            f"예습노트 {t['noted']} · 형성평가 {t['exam']}")


def _pill(text: str, kind: str) -> ft.Control:
    if kind == "none" or not text:
        return ft.Text("·", size=15, color=MUTE)
    color, bg = {
        "done": (MINT, MINT_BG),
        "fresh": (MINT, None),
        "wait": (APRI, APRI_BG),
    }.get(kind, (MUTE, None))
    return ft.Container(
        content=ft.Text(text, size=11, weight=ft.FontWeight.BOLD, color=color),
        bgcolor=bg, padding=ft.Padding(9, 3, 9, 3), border_radius=99,
        border=ft.Border.all(1, ft.Colors.with_opacity(.35, color)),
    )


def _chip(label: str, icon, on_click, tone: str = "", tooltip: str = "") -> ft.Control:
    """글자가 뜻을 담는 칩(4문항·노트) — 좁은 열에서도 접히지 않게 여백을 줄였다."""
    color = MINT if tone == "mint" else None
    return ft.OutlinedButton(label, icon=icon, on_click=on_click, height=30,
                             tooltip=tooltip or None,
                             style=ft.ButtonStyle(
                                 color=color, padding=ft.Padding(8, 0, 10, 0)))


def _icon_chip(icon, tooltip: str, on_click) -> ft.Control:
    """머리글이 이미 뜻을 말해주는 칸(MP3·강의록)은 아이콘만 — 폭을 아낀다."""
    return ft.IconButton(icon, tooltip=tooltip, on_click=on_click,
                         icon_size=19, width=38, height=34)


def _dash() -> ft.Control:
    return ft.Text("·", size=15, color=MUTE)


# 열 배치 — 24칸 반응형 그리드(12칸은 눈금이 굵어 칩이 열을 넘쳤다).
# 창이 좁아지면 고정폭처럼 겹치지 않고 '차시' 한 줄 + 나머지가 아랫줄로 접힌다.
#   넓을 때(md 이상): 차시8 + 이수3 + 형성평가5 + 노트4 + MP3 2 + 강의록2 = 24
#   좁을 때(xs):      차시24 / 이수8+형성평가16 / 노트8+MP3 8+강의록8
GRID = 24
COLS = {
    "lec": {"xs": 24, "md": 8},
    "watch": {"xs": 8, "md": 3},
    "exam": {"xs": 16, "md": 5},
    "note": {"xs": 8, "md": 4},
    "mp3": {"xs": 8, "md": 2},
    "doc": {"xs": 8, "md": 2},
}


def _cell(control, key: str) -> ft.Control:
    """반응형 칸 하나 — COLS 의 배치값을 그대로 쓴다."""
    return ft.Container(content=control, col=COLS[key])


def _grid(controls) -> ft.Control:
    """차시 한 줄(또는 머리글)을 담는 24칸 반응형 줄."""
    return ft.ResponsiveRow(controls, columns=GRID, spacing=6, run_spacing=6,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)


# 창이 이보다 좁으면 표 배치를 접는다(칸을 우겨넣어 글자가 깨지는 걸 막는다).
COMPACT_WIDTH = 980


def is_compact(width) -> bool:
    """창 폭 → 접힌 배치를 쓸지. 폭을 모르면(테스트 등) 넓은 배치."""
    try:
        return float(width) < COMPACT_WIDTH
    except (TypeError, ValueError):
        return False


def short_course(name: str, limit: int = 9) -> str:
    """과목 칩에 넣을 짧은 이름('AI네이티브가되기위한기초소양' → 'AI네이티브가되기…')."""
    name = (name or "").strip()
    return name if len(name) <= limit else name[:limit] + "…"


# ---------------------------------------------------------------------------
# 화면 (Flet — 수동 스모크)
# ---------------------------------------------------------------------------
def build_status_view(page=None, on_open_quiz=None, on_open_pdf=None,
                      snapshot_path=None, state_path=None) -> ft.Control:
    """현황 화면.

    on_open_quiz(과목, 차시)  — '형성평가 N문항' 칩 → 퀴즈 화면
    on_open_pdf(경로, 제목)   — 강의록 칩 → 앱 안 PDF 화면(없으면 기본 프로그램)
    """
    snapshot_path = snapshot_path or SNAPSHOT_PATH
    state_path = state_path or STATE_PATH
    # course=None 이면 전체 보기, 과목명이면 그 과목만(스크롤 없이 바로 전환)
    state = {"only_todo": False, "courses": [], "course": None,
             "compact": is_compact(getattr(page, "width", None))}

    title = ft.Text("학습 현황", size=26, weight=ft.FontWeight.BOLD)
    sub = ft.Text("", size=13, color=MUTE)
    when = ft.Text("", size=12, color=MUTE)
    status_msg = ft.Text("", size=12, color=MUTE)
    body = ft.Column(spacing=14, expand=True, scroll=ft.ScrollMode.AUTO)
    tabs = ft.Row(spacing=6, wrap=True)     # 과목 바로가기(스크롤 대신)

    def _safe_update():
        if page is not None:
            try:
                page.update()
            except Exception:
                pass

    def _set_msg(text: str, color=None):
        status_msg.value = text
        status_msg.color = color or MUTE
        _safe_update()

    def _open_file(p, what: str):
        r = open_path(p)
        if r["ok"]:
            how = "옵시디언" if r["how"] == "obsidian" else "기본 프로그램"
            _set_msg(f"{what} 열기 — {how}", MINT)
            if r.get("error"):
                _set_msg(r["error"], APRI)
        else:
            _set_msg(f"{what} 열기 실패: {r.get('error')}", ft.Colors.RED)

    def _open_pdf(info):
        """강의록 → 앱 안 PDF 화면(연결이 없으면 기본 프로그램으로)."""
        path = info.get("path") or info.get("name")
        if on_open_pdf is None:
            _open_file(path, "강의록")
            return
        on_open_pdf(path, info.get("name") or "강의록")

    def _row_controls(r: dict) -> ft.Control:
        seq = ft.Text(f"{int(r['seq']):02d}", size=14, width=28,
                      weight=ft.FontWeight.BOLD, font_family="Consolas",
                      color=MINT if (r.get("notes") or r.get("video_done")
                                     or r.get("watch_run")) else MUTE)
        name = ft.Text(r.get("name") or "", size=13, no_wrap=True,
                       overflow=ft.TextOverflow.ELLIPSIS,
                       tooltip=r.get("name") or "", expand=True)
        mins = ft.Text(
            f"{r.get('watched_min', 0)}/{r.get('total_min', 0)}분",
            size=11, color=MUTE, font_family="Consolas",
        ) if r.get("total_min") else ft.Text("")

        w_txt, w_kind = status_label(r, "watch")
        e_txt, e_kind = status_label(r, "exam")

        exam_cell = [_pill(e_txt, e_kind)]
        if r.get("quiz_count"):
            exam_cell.append(_chip(
                f"{r['quiz_count']}문항", ft.Icons.QUIZ,
                (lambda e, c=r["course"], s=r["seq"]: on_open_quiz(c, s))
                if on_open_quiz else None, tone="mint"))

        notes = r.get("notes") or []
        note_cell = []
        for n in notes:
            part = int(n.get("part") or 1)
            note_cell.append(_chip(
                "노트" if part == 1 else f"({part})", ft.Icons.DESCRIPTION_OUTLINED,
                lambda e, p=n.get("path"): _open_file(p, "예습노트"),
                tooltip=(n.get("name") or "") +
                        ("" if part == 1 else " · 두 번째 영상 노트")))
        mp3 = r.get("mp3")
        mp3_cell = (_icon_chip(ft.Icons.GRAPHIC_EQ,
                               f"MP3 듣기 — {mp3.get('name')}",
                               lambda e, p=mp3.get("path"): _open_file(p, "MP3"))
                    if mp3 else None)
        doc = r.get("doc")
        doc_cell = (_icon_chip(ft.Icons.PICTURE_AS_PDF,
                               f"{doc.get('kind') or 'PDF'} 보기 — {doc.get('name')}",
                               lambda e, d=doc: _open_pdf(d))
                    if doc else None)

        lec = ft.Row([seq, name, mins], spacing=10, wrap=False,
                     vertical_alignment=ft.CrossAxisAlignment.CENTER)
        pad = ft.Padding(12, 7, 12, 7)
        border = ft.Border(top=ft.BorderSide(
            1, ft.Colors.with_opacity(.08, ft.Colors.ON_SURFACE)))

        if state["compact"]:
            # 좁은 창: 제목 한 줄 + 있는 것만 아랫줄에(빈 칸·머리글 없이 → 짧게)
            chips = [c for c in ([_pill(w_txt, w_kind)] if w_kind != "none" else [])]
            if e_kind != "none":
                chips.append(_pill(e_txt, e_kind))
            chips += [c for c in exam_cell[1:]] + note_cell
            chips += [c for c in (mp3_cell, doc_cell) if c is not None]
            lines = [lec]
            if chips:
                lines.append(ft.Row(chips, spacing=4, wrap=True, run_spacing=4))
            return ft.Container(content=ft.Column(lines, spacing=6, tight=True),
                                padding=pad, border=border)

        return ft.Container(
            content=_grid([
                _cell(lec, "lec"),
                _cell(ft.Row([_pill(w_txt, w_kind)], wrap=True), "watch"),
                _cell(ft.Row(exam_cell, spacing=4, wrap=True), "exam"),
                _cell(ft.Row(note_cell or [_dash()], spacing=4, wrap=True), "note"),
                _cell(ft.Row([mp3_cell or _dash()], wrap=True), "mp3"),
                _cell(ft.Row([doc_cell or _dash()], wrap=True), "doc"),
            ]),
            padding=pad, border=border,
        )

    def _header_row() -> ft.Control:
        """차시 표 머리글 — 줄과 같은 배치값을 써서 넓을 땐 세로줄이 맞고,
        좁아지면 줄과 똑같이 접힌다."""
        def hd(text, key):
            return _cell(ft.Text(text, size=10, color=MUTE), key)
        return ft.Container(
            content=_grid(
                [hd("차시", "lec"), hd("영상이수", "watch"), hd("형성평가", "exam"),
                 hd("예습노트", "note"), hd("MP3", "mp3"), hd("강의록", "doc")]),
            padding=ft.Padding(12, 2, 12, 0))

    def _course_card(c: dict) -> ft.Control:
        st = c.get("stats") or {}
        total = int(st.get("total") or 0)
        watched = int(st.get("watched") or 0)
        rows = c.get("rows") or []
        if state["only_todo"]:
            from status_html import row_is_done
            rows = [r for r in rows if not row_is_done(r)]
            if not rows:
                return ft.Container()
        head = ft.Row(
            [
                ft.Text(c.get("course") or "", size=17,
                        weight=ft.FontWeight.BOLD, expand=True),
                ft.Text(f"이수 {watched}/{total} · 노트 {st.get('noted', 0)} · "
                        f"형성평가 {st.get('exam', 0)} · 퀴즈 {st.get('quiz', 0)}문항",
                        size=11, color=MUTE),
            ],
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        bar = ft.ProgressBar(value=(watched / total) if total else 0, height=4,
                             color=MINT,
                             bgcolor=ft.Colors.with_opacity(.08, ft.Colors.ON_SURFACE))
        # 머리글은 카드 **안에** 둔다 — 바깥에 두면 스크롤바 폭만큼 어긋난다.
        # 좁은 배치에서는 칸이 접혀 머리글이 되레 헷갈리므로 빼고 툴팁으로 안내한다.
        parts = [head, bar] + ([] if state["compact"] else [_header_row()])
        return ft.Container(
            content=ft.Column(parts + [_row_controls(r) for r in rows], spacing=6),
            padding=16, border_radius=12,
            bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
            border=ft.Border.all(1, ft.Colors.with_opacity(.08, ft.Colors.ON_SURFACE)),
        )

    def _pick_course(name):
        """과목 칩 클릭 — 그 과목만 보여준다(None 이면 전체)."""
        state["course"] = name
        _render()

    def _build_tabs(courses):
        """과목 바로가기 칩 — 누르면 스크롤 없이 그 과목으로 바뀐다."""
        tabs.controls.clear()
        items = [(None, "전체", len(courses))] + [
            (c["course"], short_course(c["course"]),
             int((c.get("stats") or {}).get("total") or 0)) for c in courses]
        for key, label, n in items:
            on = state["course"] == key
            text = f"{label} {n}" if key is None else label
            btn = (ft.FilledButton if on else ft.OutlinedButton)(
                text, height=32, tooltip=key or "모든 과목 보기",
                on_click=lambda e, k=key: _pick_course(k),
                style=ft.ButtonStyle(
                    bgcolor=MINT if on else None,
                    color="#ffffff" if on else None,
                    padding=ft.Padding(12, 0, 12, 0)))
            tabs.controls.append(btn)

    def _render():
        """현재 필터(과목/남은 것만)로 본문만 다시 그린다."""
        body.controls.clear()
        courses = state["courses"]
        _build_tabs(courses)
        shown = [c for c in courses
                 if state["course"] in (None, c.get("course"))]
        if not shown:
            body.controls.append(ft.Text(
                "표시할 강의가 없습니다. '실행' 탭의 [목록 새로고침]을 먼저 눌러 주세요.",
                color=MUTE))
        for c in shown:
            card = _course_card(c)
            if isinstance(card, ft.Container) and card.content is not None:
                body.controls.append(card)
        _safe_update()

    def refresh(_=None):
        body.controls.clear()
        try:
            from config import load_config
            cfg = load_config()
        except Exception as ex:  # noqa: BLE001
            body.controls.append(ft.Text(f"설정이 필요합니다: {str(ex)[:120]} → '설정' 탭",
                                         color=ft.Colors.RED))
            _safe_update()
            return
        courses = collect_status(cfg, snapshot_path, state_path)
        state["courses"] = courses
        sub.value = summary_text(courses)
        gen = snapshot_time(snapshot_path)
        when.value = (f"목록 기준 {fmt_when(gen)} — 최신 상태는 '실행' 탭의 "
                      "[목록 새로고침] 후 다시 불러오세요") if gen else ""
        # 고른 과목이 목록에서 사라졌으면 전체로 되돌린다
        if state["course"] not in [c.get("course") for c in courses]:
            state["course"] = None
        _render()

    def on_filter(e):
        state["only_todo"] = bool(e.control.value)
        _render()

    def on_save_html(_):
        try:
            from config import load_config
            from status_page import write_status_page
            cfg = load_config()
            p = write_status_page(cfg, snapshot_path, state_path)
            _set_msg(f"HTML 저장: {default_status_path(cfg).name} "
                     f"({p.parent})", MINT)
        except Exception as ex:  # noqa: BLE001
            _set_msg(f"HTML 저장 실패: {str(ex)[:120]}", ft.Colors.RED)

    tools = ft.Row(
        [
            ft.OutlinedButton("다시 불러오기", icon=ft.Icons.REFRESH,
                              on_click=refresh),
            ft.Switch(label="남은 것만 보기", value=False, on_change=on_filter,
                      active_color=MINT),
            ft.TextButton("HTML로 저장", icon=ft.Icons.SAVE_ALT,
                          on_click=on_save_html),
        ],
        spacing=12, wrap=True,
    )

    def _on_resize(e=None):
        """창 폭이 접힘 기준을 넘나들 때만 다시 그린다(리사이즈마다 통째로 X)."""
        w = getattr(e, "width", None) or getattr(page, "width", None)
        now = is_compact(w)
        if now != state["compact"]:
            state["compact"] = now
            _render()

    if page is not None:
        try:
            page.on_resize = _on_resize
        except Exception:
            pass

    refresh()
    return ft.Column(
        [title, sub, when, tools, tabs, ft.Divider(height=1),
         body, status_msg],
        spacing=8, expand=True,
    )
