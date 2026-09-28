"""[plan_view] 진도 트래커 — 목표일까지 모든 강의를 한 번은 보려면.

LMS 의 '이수' 는 이 프로그램이 영상을 돌려 채운 것이라, 내가 **실제로 본**
강의와는 다르다. 여기서는 실제로 본 것만 센다.

  · 과목마다 1~15강 칸 — 들은 강을 누르면 채워지고, 잘못 눌렀으면 다시 눌러 뺀다
  · 머리말은 남은 날과 하루치를 말한다(D-49 · 하루 1.3강)
  · 차질이 생기면 **남은 강의 ÷ 남은 날**을 다시 나눈다 — 하루치가 늘어난다
  · 주별 막대로 어느 주에 쉬었는지 보인다

계산은 study_plan 이 다 한다(여기서는 그리기만 — 오프라인·네트워크 없음).
"""
from __future__ import annotations

from pathlib import Path

import flet as ft

import study_plan as sp

MINT = "#00a37a"
MINT_BG = "#e3f6ef"
ROSE = "#c8452f"
ROSE_BG = "#fbe9e5"
APRI = "#d98324"
APRI_BG = "#fbf0df"
MUTE = "#8b9198"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = PROJECT_ROOT / "lectures.json"

CELL = 30          # 강 번호 칸 한 변(px)
BAR_H = 66         # 주별 막대의 가장 높은 칸(px)
BAR_W = 30         # 막대 폭(px)
WEEKS = 8          # 주별 막대를 몇 주 보여줄지

# 목표에서 빼는 과목 — 이수만 하면 되는 필수 교육이라 '한 번은 본다' 의 대상이
# 아니다. AI네이티브는 이미 다 이수했고 강의도 13강뿐이라 함께 뺀다.
SKIP = sp.SKIP_COURSES + ("AI네이티브가되기위한기초소양",)


# ---------------------------------------------------------------------------
# 순수 조각 (오프라인 테스트 가능)
# ---------------------------------------------------------------------------
def drift_tone(plan, today=None) -> str:
    """머리말 경고의 색: behind | ahead | ontrack | done."""
    t = sp.totals(plan)
    if not t["total"] or not t["left"]:
        return "done"
    d = sp.drift(plan, today)
    if d <= -0.5:
        return "behind"
    return "ahead" if d >= 0.5 else "ontrack"


def course_line(row, days) -> str:
    """과목 카드의 오른쪽 문구 — '3 / 15강 · 남은 12 · 하루 0.2강'."""
    row = row or {}
    body = f"{row.get('done', 0)} / {row.get('total', 0)}강"
    left = int(row.get("left") or 0)
    if not left:
        return f"{body} · 다 봤습니다"
    need = sp.course_need(row, days)
    return f"{body} · 남은 {left} · 하루 {sp.num_text(need)}강"


def bar_height(n, top) -> float:
    """주별 막대 높이(px) — 가장 많이 본 주를 꼭대기로 맞춘다.

    한 강이라도 본 주는 눈에 보여야 한다(0 과 1 이 똑같이 납작하면 쉰 주와
    구분되지 않는다).
    """
    n, top = int(n or 0), int(top or 0)
    if not n:
        return 2.0
    return max(6.0, round(BAR_H * n / max(top, 1), 1))


def week_label(iso: str) -> str:
    """'2026-09-07' → '9/7' — 막대 아래에 적는다."""
    s = str(iso or "")
    if len(s) < 10:
        return s
    return f"{int(s[5:7])}/{int(s[8:10])}"


# ---------------------------------------------------------------------------
# 화면 (Flet — 수동 스모크)
# ---------------------------------------------------------------------------
def build_plan_view(page=None, plan_path=None, today=None,
                    snapshot_path=None) -> ft.Control:
    """진도 트래커 화면."""
    if plan_path is None:
        try:
            from config import load_config
            plan_path = sp.plan_path(load_config())
        except Exception:  # noqa: BLE001 - 설정 전이면 빈 화면으로
            plan_path = None
    snapshot_path = snapshot_path or SNAPSHOT_PATH

    st = {"plan": sp.load_plan(plan_path) if plan_path else {}}

    title = ft.Text("진도 트래커", size=26, weight=ft.FontWeight.BOLD)
    sub = ft.Text("", size=13, color=MUTE)
    # 트래커를 여는 이유가 이 한 줄이다 — 오늘 몇 강을 들어야 하는가.
    todo = ft.Text("", size=14, weight=ft.FontWeight.BOLD, color=MINT)
    bar = ft.ProgressBar(value=0, height=6, color=MINT,
                         bgcolor=ft.Colors.with_opacity(
                             .08, ft.Colors.ON_SURFACE))
    note = ft.Text("", size=13, weight=ft.FontWeight.BOLD)
    note_box = ft.Container(content=note, padding=ft.Padding(14, 10, 14, 10),
                            border_radius=10, visible=False)
    goal_box = ft.TextField(label="목표일", width=150, text_size=13,
                            height=46,
                            content_padding=ft.Padding(12, 8, 12, 8),
                            tooltip="이 날까지 모든 강의를 한 번은 봅니다")
    body = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)

    def _save():
        if plan_path:
            sp.save_plan(plan_path, st["plan"])

    def _safe_update():
        try:
            if page is not None:
                page.update()
        except Exception:  # noqa: BLE001 - 화면이 없어도 계산은 끝나야 한다
            pass

    def _days() -> int:
        return sp.days_left(st["plan"].get("goal"), today)

    def _toggle(course, no):
        """강 하나를 봤다/안 봤다로 뒤집는다 — 누르는 즉시 저장한다."""
        st["plan"] = sp.toggle(st["plan"], course, no, today)
        _save()
        _render()

    def _cell(course, no, done) -> ft.Control:
        when = sp.watched_on(st["plan"], course, no)
        return ft.Container(
            content=ft.Text(str(no), size=12, weight=ft.FontWeight.BOLD,
                            color="#ffffff" if done else MUTE),
            width=CELL, height=CELL, border_radius=8,
            alignment=ft.Alignment.CENTER,
            bgcolor=MINT if done else None,
            border=ft.Border.all(1, MINT if done else ft.Colors.with_opacity(
                .16, ft.Colors.ON_SURFACE)),
            tooltip=(f"{no}강 — {when} 에 봤습니다" if done
                     else f"{no}강 — 아직 안 봤습니다(누르면 표시)"),
            ink=True, on_click=lambda _e, c=course, n=no: _toggle(c, n))

    def _course_card(row) -> ft.Control:
        done = set(row["nos"])
        head = ft.Row(
            [ft.Text(row["course"], size=15, weight=ft.FontWeight.BOLD,
                     expand=True),
             ft.Text(course_line(row, _days()), size=12,
                     color=MINT if not row["left"] else MUTE)],
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
        cells = ft.Row([_cell(row["course"], n, n in done)
                        for n in range(1, row["total"] + 1)],
                       spacing=5, wrap=True)
        return ft.Container(
            content=ft.Column([head, cells], spacing=10, tight=True),
            padding=16, border_radius=12,
            bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
            border=ft.Border.all(1, ft.Colors.with_opacity(
                .08, ft.Colors.ON_SURFACE)))

    def _weeks_card() -> ft.Control:
        rows = sp.weekly(st["plan"], WEEKS, today)
        top = max([w["n"] for w in rows] or [0])
        bars = []
        for w in rows:
            bars.append(ft.Column(
                [ft.Text(str(w["n"]) if w["n"] else "", size=11, color=MUTE),
                 ft.Container(width=BAR_W, height=bar_height(w["n"], top),
                              border_radius=4,
                              bgcolor=MINT if w["n"] else
                              ft.Colors.with_opacity(.12,
                                                     ft.Colors.ON_SURFACE)),
                 ft.Text(week_label(w["start"]), size=10, color=MUTE)],
                spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER))
        return ft.Container(
            content=ft.Column(
                [ft.Text("주마다 몇 강", size=13, weight=ft.FontWeight.BOLD),
                 ft.Row(bars, spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.END)],
                spacing=10, tight=True),
            padding=16, border_radius=12,
            bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
            border=ft.Border.all(1, ft.Colors.with_opacity(
                .08, ft.Colors.ON_SURFACE)))

    def _render():
        plan = st["plan"]
        rows = sp.course_rows(plan)
        t = sp.totals(plan)
        sub.value = sp.status_line(plan, today)
        todo.value = sp.today_line(plan, today)
        bar.value = (t["done"] / t["total"]) if t["total"] else 0
        goal_box.value = str(plan.get("goal") or "")

        tone = drift_tone(plan, today)
        msg = sp.drift_text(plan, today)
        worst = sp.worst_course(plan, today)
        if tone == "behind" and worst:
            # 뒤처졌다고만 하면 막막하다 — 어디부터 손댈지 함께 말한다.
            msg = f"{msg} · {worst}부터 손대세요"
        note.value = msg
        note.color = {"behind": ROSE, "ahead": MINT}.get(tone, MUTE)
        note_box.bgcolor = {"behind": ROSE_BG, "ahead": MINT_BG}.get(
            tone, ft.Colors.with_opacity(.05, ft.Colors.ON_SURFACE))
        note_box.visible = bool(msg)

        body.controls.clear()
        if not rows:
            body.controls.append(ft.Text(
                "아직 과목이 없습니다. [과목 불러오기] 를 누르면 강의 목록에서 "
                "과목과 강의 수를 집어 옵니다.", color=MUTE))
        else:
            body.controls += [_course_card(r) for r in rows]
            body.controls.append(_weeks_card())
        _safe_update()

    def on_goal(_e):
        """목표일을 고친다 — 날짜가 바뀌면 하루치가 저절로 다시 나뉜다."""
        got = str(goal_box.value or "").strip()
        if not sp.is_date(got):
            sub.value = "목표일은 2026-11-16 처럼 적어 주세요"
            _safe_update()
            return
        st["plan"] = dict(st["plan"], goal=got)
        _save()
        _render()

    def on_load_courses(_e):
        """[과목 불러오기] — 강의 목록에서 과목과 강의 수를 집어 온다."""
        courses = sp.courses_from_lectures(snapshot_path, skip=SKIP)
        if not courses:
            sub.value = "강의 목록(lectures.json)이 없습니다. [실행] 에서 한 번 훑어 주세요."
            _safe_update()
            return
        plan = st["plan"] or sp.make_plan(courses)
        plan["courses"] = courses
        plan.setdefault("goal", sp.DEFAULT_GOAL)
        plan.setdefault("watched", {})
        st["plan"] = plan
        _save()
        _render()

    head = ft.Row(
        [ft.Column([title, sub, todo], spacing=2, expand=True),
         goal_box,
         ft.TextButton("적용", icon=ft.Icons.CHECK, on_click=on_goal,
                       style=ft.ButtonStyle(color=MINT)),
         ft.TextButton("과목 불러오기", icon=ft.Icons.REFRESH,
                       tooltip="강의 목록에서 과목과 강의 수를 다시 집어 옵니다",
                       on_click=on_load_courses)],
        vertical_alignment=ft.CrossAxisAlignment.CENTER)

    _render()
    return ft.Column([head, bar, note_box, ft.Divider(height=1), body],
                     spacing=12, expand=True)
