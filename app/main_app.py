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

from app.views.run_view import build_run_view  # noqa: E402
from app.views.schedule_view import build_schedule_view  # noqa: E402
from app.views.settings_view import build_settings_view  # noqa: E402
from gui_core import ENV_PATH, first_run_needed  # noqa: E402

APP_TITLE = "KNOU 강의 이수 + 예습 노트"

# (라벨, 아이콘) — 인덱스 순서가 곧 네비 순서
NAV = [
    ("홈", ft.Icons.HOME),
    ("실행", ft.Icons.PLAY_CIRCLE),
    ("예약", ft.Icons.SCHEDULE),
    ("설정", ft.Icons.SETTINGS),
]


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


def _build_view(index: int, page: ft.Page) -> ft.Control:
    """네비 인덱스 → 해당 화면 컨트롤."""
    if index == 0:
        return _placeholder(
            "홈",
            "왼쪽 메뉴에서 작업을 고르세요.\n"
            "· 실행: 강의를 골라 예습 노트 생성 / 영상 이수\n"
            "· 예약: 정해진 시각에 자동 실행\n"
            "· 설정: 아이디·비밀번호·Gemini 키·볼트 경로 입력",
        )
    if index == 1:
        return build_run_view(page)
    if index == 2:
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

    content = ft.Container(expand=True, padding=24)

    def show(index: int) -> None:
        content.content = _build_view(index, page)
        page.update()

    rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=92,
        destinations=[
            ft.NavigationRailDestination(icon=icon, label=label)
            for label, icon in NAV
        ],
        on_change=lambda e: show(e.control.selected_index),
    )

    page.add(
        ft.Row(
            [rail, ft.VerticalDivider(width=1), content],
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
