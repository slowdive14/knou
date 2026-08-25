"""KNOU 강의 이수 + 예습 노트 — Flet 데스크톱 앱 진입점.

좌측 네비게이션(홈·실행·예약·설정)으로 화면을 전환한다. 첫 실행(.env 필수값
누락) 시 설정 화면으로 유도한다. 실제 작업은 후속 Phase에서 subprocess로 main.py를
구동해 채운다(현재 홈/실행/예약은 자리표시 뷰).

⚠️ 비밀번호·GEMINI_API_KEY 등은 화면에서 마스킹하며 로그/콘솔에 출력하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가(스크립트 직접 실행 대응)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import flet as ft  # noqa: E402

from app.views.quiz_view import build_quiz_view  # noqa: E402
from app.views.run_view import build_run_view  # noqa: E402
from app.views.schedule_view import build_schedule_view  # noqa: E402
from app.views.status_view import build_status_view  # noqa: E402
from app.views.settings_view import build_settings_view  # noqa: E402
from gui_core import ENV_PATH, first_run_needed  # noqa: E402
from ui_prefs import load_theme, next_theme, save_theme, theme_label  # noqa: E402

APP_TITLE = "KNOU 강의 이수 + 예습 노트"

# 생성 HTML(ui_theme)과 같은 액센트 — 앱과 페이지의 색을 맞춘다
SEED_COLOR = "#00a37a"

# 화면 밝기 값 → Flet ThemeMode / 버튼 아이콘
_THEME_MODES = {
    "system": ft.ThemeMode.SYSTEM,
    "light": ft.ThemeMode.LIGHT,
    "dark": ft.ThemeMode.DARK,
}
_THEME_ICONS = {
    "system": ft.Icons.BRIGHTNESS_AUTO_OUTLINED,
    "light": ft.Icons.LIGHT_MODE_OUTLINED,
    "dark": ft.Icons.DARK_MODE_OUTLINED,
}


def theme_mode_for(value: str) -> ft.ThemeMode:
    """'system|light|dark' → Flet ThemeMode(모르는 값이면 시스템)."""
    return _THEME_MODES.get(value, ft.ThemeMode.SYSTEM)


def theme_icon_for(value: str):
    """화면 밝기 값 → 버튼 아이콘."""
    return _THEME_ICONS.get(value, _THEME_ICONS["system"])

# (라벨, 아이콘) — 인덱스 순서가 곧 네비 순서
NAV = [
    ("홈", ft.Icons.HOME),
    ("실행", ft.Icons.PLAY_CIRCLE),
    ("현황", ft.Icons.DASHBOARD_OUTLINED),
    ("퀴즈", ft.Icons.QUIZ),
    ("예약", ft.Icons.SCHEDULE),
    ("설정", ft.Icons.SETTINGS),
]
# 네비 인덱스 — 코드에서 이름으로 부르기 위해
NAV_HOME, NAV_RUN, NAV_STATUS, NAV_QUIZ, NAV_SCHEDULE, NAV_SETTINGS = range(6)


def _placeholder(title: str, note: str) -> ft.Control:
    return ft.Column(
        [
            ft.Text(title, size=24, weight=ft.FontWeight.BOLD),
            ft.Divider(),
            ft.Text(note, size=14, color=ft.Colors.GREY),
        ],
        spacing=14,
        expand=True,
    )


def _build_view(index: int, page: ft.Page, go=None, quiz_start=None,
                open_pdf=None) -> ft.Control:
    """네비 인덱스 → 해당 화면 컨트롤.

    go(과목, 차시) 는 화면 간 이동 콜백(현황의 '형성평가' 칩 → 퀴즈 화면),
    quiz_start=(과목, 차시) 면 퀴즈 화면이 그 강의부터 열린다.
    """
    if index == NAV_STATUS:
        return build_status_view(page, on_open_quiz=go, on_open_pdf=open_pdf)
    if index == NAV_QUIZ:
        return build_quiz_view(page, initial=quiz_start)
    if index == 0:
        return _placeholder(
            "홈",
            "왼쪽 메뉴에서 작업을 고르세요.\n"
            "· 실행: 강의를 골라 예습 노트 생성 / 영상 이수\n"
            "· 현황: 과목·차시별로 뭐가 만들어졌는지 한눈에 "
            "(노트는 옵시디언, 강의록은 앱 안에서 열림)\n"
            "· 퀴즈: 모아둔 돌발퀴즈·형성평가 문항 풀어보기\n"
            "· 예약: 정해진 시각에 자동 실행\n"
            "· 설정: 아이디·비밀번호·Gemini 키·볼트 경로 입력",
        )
    if index == NAV_RUN:
        return build_run_view(page)
    if index == NAV_SCHEDULE:
        return build_schedule_view(page)
    return build_settings_view(ENV_PATH)


def main(page: ft.Page) -> None:
    page.title = APP_TITLE
    try:  # 창 크기(API가 다르면 무시하고 기본값 사용)
        page.window.width = 1040
        page.window.height = 720
        page.window.min_width = 780
        page.window.min_height = 560
    except Exception:
        pass

    # 색은 생성 페이지와 같은 민트 계열로, 밝기는 저장해둔 선택으로 시작
    try:
        page.theme = ft.Theme(color_scheme_seed=SEED_COLOR)
        page.dark_theme = ft.Theme(color_scheme_seed=SEED_COLOR)
    except Exception:
        pass
    theme_state = {"value": load_theme()}
    page.theme_mode = theme_mode_for(theme_state["value"])

    content = ft.Container(expand=True, padding=24)
    # 실행 화면은 **버리지 않고 숨기기만** 한다. 매번 새로 만들면 돌고 있는 작업의
    # 진행 로그·경과시간·'실행 중' 표시가 통째로 사라진다(실측 증상: 현황 탭에
    # 갔다 오면 실행 중이던 표시가 없어짐). 화면에서 감춰도 컨트롤이 트리에
    # 남아 있어야 워커 스레드가 보내는 갱신이 계속 반영된다.
    run_box = ft.Container(expand=True, padding=24, visible=False)
    nav_state = {"quiz_start": None}

    def show(index: int) -> None:
        start = nav_state.pop("quiz_start", None) if index == NAV_QUIZ else None
        nav_state["quiz_start"] = None
        if index == NAV_RUN:
            if run_box.content is None:      # 처음 들어올 때 한 번만 만든다
                run_box.content = build_run_view(page)
            run_box.visible = True
            content.visible = False
            content.content = None
        else:
            run_box.visible = False
            content.visible = True
            content.content = _build_view(index, page, go=open_quiz,
                                          quiz_start=start, open_pdf=open_pdf)
        rail.selected_index = index
        page.update()

    def open_pdf(path, title) -> None:
        """강의록 → 화면 전체를 PDF 뷰어로. (다이얼로그로 띄우면 다이얼로그가
        휠을 가로채 페이지가 안 넘어간다 — 실측 확인.)"""
        from app.views.pdf_view import build_pdf_view
        from open_target import open_path
        view, _st = build_pdf_view(
            path, title=title, page=page,
            on_back=lambda: show(NAV_STATUS),
            on_fallback=lambda: open_path(path))
        run_box.visible = False
        content.visible = True
        content.content = view
        page.update()

    def open_quiz(course, seq) -> None:
        """현황 화면의 '형성평가 N문항' 칩 → 퀴즈 화면의 그 강의로 이동."""
        nav_state["quiz_start"] = (course, seq)
        show(NAV_QUIZ)

    def on_toggle_theme(_) -> None:
        """화면 밝기 순환: 시스템 → 밝게 → 어둡게 (선택은 파일에 저장)."""
        theme_state["value"] = next_theme(theme_state["value"])
        save_theme(theme_state["value"])
        page.theme_mode = theme_mode_for(theme_state["value"])
        theme_btn.icon = theme_icon_for(theme_state["value"])
        theme_btn.tooltip = f"화면 밝기: {theme_label(theme_state['value'])}"
        theme_lbl.value = theme_label(theme_state["value"])
        page.update()

    theme_btn = ft.IconButton(
        icon=theme_icon_for(theme_state["value"]),
        tooltip=f"화면 밝기: {theme_label(theme_state['value'])}",
        on_click=on_toggle_theme,
    )
    theme_lbl = ft.Text(theme_label(theme_state["value"]), size=10,
                        color=ft.Colors.ON_SURFACE_VARIANT)

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=92,
        destinations=[
            ft.NavigationRailDestination(icon=icon, label=label)
            for label, icon in NAV
        ],
        on_change=lambda e: show(e.control.selected_index),
        trailing=ft.Column(
            [theme_btn, theme_lbl],
            spacing=0, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
    )

    # 실행 화면과 나머지 화면을 겹쳐 두고 visible 로 전환한다(Stack 이라 숨은 쪽이
    # 자리를 차지하지 않는다). 실행 화면이 트리에서 빠지지 않는 것이 핵심.
    page.add(
        ft.Row(
            [rail, ft.VerticalDivider(width=1),
             ft.Stack([content, run_box], expand=True)],
            expand=True,
        )
    )

    # 첫 실행(필수값 누락) 시 설정 화면으로 유도
    start = (len(NAV) - 1) if first_run_needed(ENV_PATH) else 0
    rail.selected_index = start
    show(start)


def run() -> None:
    ft.run(main)


if __name__ == "__main__":
    run()
