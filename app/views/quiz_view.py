"""[quiz_view] 강의 퀴즈 — 앱 안에서 푸는 복습 화면.

생성 HTML(quiz_html)과 같은 내용을 Flet 컨트롤로 직접 그린다 → 브라우저를 따로
띄우지 않고 앱 창에서 바로 푼다. 보기를 고르면 정답/오답 색이 붙고, [정답 보기]를
눌러야 정답·해설이 열린다(다시 풀어보기 가치 보존).

  - 강의 고르기(드롭다운) · 진행률 · 현재 강/전체 초기화
  - 풀이 기록은 앱이 켜져 있는 동안 유지(HTML 페이지는 브라우저에 저장)

데이터는 quiz_page.collect_banks(볼트/퀴즈) 를 그대로 쓴다(로그인·네트워크 없음).
"""
from __future__ import annotations

import flet as ft

from quiz_page import collect_banks, default_quiz_paths

MINT = "#00a37a"
MINT_BG = "#e3f6ef"
ROSE = "#c8452f"
ROSE_BG = "#fbe9e5"
MUTE = "#8b9198"


# ---------------------------------------------------------------------------
# 순수 조각 (오프라인 테스트 가능)
# ---------------------------------------------------------------------------
def bank_title(bank: dict) -> str:
    """드롭다운 표시문구: 'C프로그래밍 · 1강 · C 언어의 개요'."""
    parts = [str(bank.get("seq", "")) + "강", bank.get("name") or ""]
    head = " · ".join(p for p in parts if p)
    course = bank.get("course") or ""
    return f"{course} · {head}" if course else head


def bank_index(banks, course: str | None, seq=None) -> int:
    """과목·차시로 은행 위치 찾기(못 찾으면 0)."""
    if course is None and seq is None:
        return 0
    for i, b in enumerate(banks or []):
        if (course is None or b.get("course") == course) and \
                (seq is None or int(b.get("seq") or 0) == int(seq)):
            return i
    return 0


def progress_text(answered: int, total: int) -> str:
    return f"{int(answered)} / {int(total)}"


def option_tone(sel, no, answer_no) -> str:
    """보기 하나의 색: correct|wrong|selected|plain."""
    if sel is None or str(sel) != str(no):
        return "plain"
    if answer_no is None or str(answer_no) == "":
        return "selected"
    return "correct" if str(sel) == str(answer_no) else "wrong"


def answer_text(q: dict) -> str:
    """정답 줄 문구 — 번호와 보기글이 있으면 함께."""
    no, txt = q.get("answer_no"), q.get("answer_text")
    if no is not None:
        return f"정답: {no}. {txt or ''}".strip()
    if txt:
        return f"정답: {txt}"
    return "정답 정보 없음"


# ---------------------------------------------------------------------------
# 화면 (Flet — 수동 스모크)
# ---------------------------------------------------------------------------
def build_quiz_view(page=None, quiz_dir=None, initial=None) -> ft.Control:
    """퀴즈 화면. initial=(과목, 차시) 를 주면 그 강의부터 연다."""
    if quiz_dir is None:
        try:
            from config import load_config
            quiz_dir = default_quiz_paths(load_config())[0]
        except Exception:  # noqa: BLE001 - 설정 전이면 빈 화면으로
            quiz_dir = None

    banks = collect_banks(quiz_dir) if quiz_dir else []
    st = {"idx": bank_index(banks, *(initial or (None, None))),
          "answers": {}, "revealed": set()}

    title = ft.Text("강의 퀴즈", size=26, weight=ft.FontWeight.BOLD)
    sub = ft.Text("", size=13, color=MUTE)
    prog = ft.Text("0 / 0", size=22, weight=ft.FontWeight.BOLD,
                   font_family="Consolas")
    bar = ft.ProgressBar(value=0, height=4, color=MINT,
                         bgcolor=ft.Colors.with_opacity(.08, ft.Colors.ON_SURFACE))
    cards = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
    picker = ft.Dropdown(label="강의", width=430, options=[])

    def _safe_update():
        if page is not None:
            try:
                page.update()
            except Exception:
                pass

    def _cur_bank() -> dict:
        return banks[st["idx"]] if 0 <= st["idx"] < len(banks) else {}

    def _questions() -> list:
        return _cur_bank().get("questions") or []

    def _refresh_progress():
        qs = _questions()
        done = sum(1 for q in qs if st["answers"].get(q.get("qid")) is not None)
        prog.value = progress_text(done, len(qs))
        bar.value = (done / len(qs)) if qs else 0
        _safe_update()

    def _option_button(q: dict, o: dict) -> ft.Control:
        qid = q.get("qid")
        no = o.get("no")
        tone = option_tone(st["answers"].get(qid), no, q.get("answer_no"))
        border, bg = {
            "correct": (MINT, MINT_BG),
            "wrong": (ROSE, ROSE_BG),
            "selected": (MINT, MINT_BG),
        }.get(tone, (ft.Colors.with_opacity(.14, ft.Colors.ON_SURFACE), None))
        badge_bg = {"correct": MINT, "wrong": ROSE}.get(tone)

        def choose(_):
            st["answers"][qid] = no
            _render_cards()
            _refresh_progress()

        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Text(str(no), size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color="#ffffff" if badge_bg else None),
                        width=24, height=24, border_radius=99,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=badge_bg or ft.Colors.with_opacity(
                            .08, ft.Colors.ON_SURFACE)),
                    ft.Text(str(o.get("text") or ""), size=14, expand=True),
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=choose, ink=True,
            padding=ft.Padding(13, 11, 13, 11), border_radius=10, bgcolor=bg,
            border=ft.Border.all(1.4, border),
        )

    def _card(num: int, q: dict) -> ft.Control:
        qid = q.get("qid")
        opened = qid in st["revealed"]

        def toggle(_):
            if opened:
                st["revealed"].discard(qid)
            else:
                st["revealed"].add(qid)
            _render_cards()

        items = [
            ft.Row([
                ft.Text(f"Q{num:02d}", size=13, weight=ft.FontWeight.BOLD,
                        color=MINT, font_family="Consolas", expand=True),
                ft.Text(str(q.get("source") or ""), size=11, color=MUTE),
            ]),
            ft.Text(str(q.get("question") or ""), size=15,
                    weight=ft.FontWeight.BOLD),
        ]
        items += [_option_button(q, o) for o in (q.get("options") or [])]
        items.append(ft.TextButton(
            "정답 숨기기" if opened else "정답 보기",
            icon=ft.Icons.VISIBILITY_OFF if opened else ft.Icons.VISIBILITY,
            on_click=toggle, style=ft.ButtonStyle(color=MINT)))
        if opened:
            items.append(ft.Container(
                content=ft.Column([
                    ft.Text(answer_text(q), size=13,
                            weight=ft.FontWeight.BOLD, color=MINT),
                    ft.Text(str(q.get("explanation") or ""), size=13,
                            selectable=True),
                ], spacing=6, tight=True),
                bgcolor=MINT_BG, padding=14, border_radius=10,
                border=ft.Border(left=ft.BorderSide(3, MINT))))

        return ft.Container(
            content=ft.Column(items, spacing=9, tight=True),
            padding=18, border_radius=12,
            bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
            border=ft.Border.all(1, ft.Colors.with_opacity(.08,
                                                           ft.Colors.ON_SURFACE)))

    def _render_cards():
        cards.controls.clear()
        qs = _questions()
        if not banks:
            cards.controls.append(ft.Text(
                "저장된 문제가 없습니다. 이수를 실행하면 돌발퀴즈·형성평가 문항이 모입니다.",
                color=MUTE))
        elif not qs:
            cards.controls.append(ft.Text("이 강의에 저장된 문제가 없습니다.",
                                          color=MUTE))
        for i, q in enumerate(qs, start=1):
            cards.controls.append(_card(i, q))
        _safe_update()

    def _load_bank(idx: int):
        st["idx"] = max(0, min(int(idx), max(0, len(banks) - 1)))
        b = _cur_bank()
        sub.value = (f"{bank_title(b)} · {len(_questions())}문제"
                     if b else "저장된 문제가 없습니다")
        picker.value = str(st["idx"])
        _render_cards()
        _refresh_progress()

    def on_pick(_=None):
        # 드롭다운이 고른 값은 옵션의 key(문자열 인덱스). 이벤트 인자에 기대지 않고
        # 컨트롤에서 직접 읽는다.
        try:
            _load_bank(int(picker.value))
        except (TypeError, ValueError):
            pass

    def on_reset_lec(_):
        for q in _questions():
            st["answers"].pop(q.get("qid"), None)
            st["revealed"].discard(q.get("qid"))
        _render_cards()
        _refresh_progress()

    def on_reset_all(_):
        st["answers"].clear()
        st["revealed"].clear()
        _render_cards()
        _refresh_progress()

    def on_save_html(_):
        try:
            from config import load_config
            from quiz_page import write_quiz_page
            cfg = load_config()
            qd, out = default_quiz_paths(cfg)
            p = write_quiz_page(qd, out)
            sub.value = f"HTML 저장: {p.name} ({p.parent})"
        except Exception as ex:  # noqa: BLE001
            sub.value = f"HTML 저장 실패: {str(ex)[:120]}"
        _safe_update()

    picker.options = [ft.DropdownOption(key=str(i), text=bank_title(b))
                      for i, b in enumerate(banks)]
    # ⚠️ Flet 0.85 의 Dropdown 은 on_change 가 아니라 **on_select** 다.
    # (없는 속성에 붙이면 조용히 무시되어 강의를 바꿔도 문제가 안 바뀐다)
    picker.on_select = on_pick

    tools = ft.Row(
        [
            ft.OutlinedButton("현재 강 초기화", icon=ft.Icons.RESTART_ALT,
                              on_click=on_reset_lec),
            ft.OutlinedButton("전체 초기화", icon=ft.Icons.REFRESH,
                              on_click=on_reset_all),
            ft.TextButton("HTML로 저장", icon=ft.Icons.SAVE_ALT,
                          on_click=on_save_html),
        ],
        spacing=10, wrap=True,
    )

    _load_bank(st["idx"])
    return ft.Column(
        [
            title, sub,
            ft.Row([picker, ft.Column([ft.Text("푼 문제", size=11, color=MUTE),
                                       prog], spacing=0)],
                   vertical_alignment=ft.CrossAxisAlignment.END, spacing=18),
            bar, tools, ft.Divider(height=1), cards,
        ],
        spacing=10, expand=True,
    )
