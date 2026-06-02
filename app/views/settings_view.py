"""설정 화면 — .env 값을 안전하게 입력/저장(비밀번호·API 키 마스킹).

순수 로직 `apply_settings()`(쓰기+검증)는 단위테스트 대상.
화면 구성 `build_settings_view()`는 페이지 없이도 생성 가능(오프라인 스모크 테스트).
⚠️ 비밀값은 password 필드로만 표시하고 로그에 출력하지 않는다.
"""
from __future__ import annotations

import flet as ft

from deploy import create_desktop_shortcut
from gui_core import (
    ENV_PATH,
    SECRET_KEYS,
    SETTINGS_KEYS,
    read_env_file,
    validate_settings,
    write_env_file,
)

# 키 → 한글 라벨/도움말
LABELS = {
    "KNOU_ID": "방송대 아이디",
    "KNOU_PW": "방송대 비밀번호",
    "GEMINI_API_KEY": "Gemini API 키",
    "VAULT_PATH": "옵시디언 볼트 경로",
    "SUMMARY_SUBDIR": "노트 저장 하위폴더",
    "PLAYBACK_SPEED": "영상 재생 배속",
}
HINTS = {
    "VAULT_PATH": r"예: G:\내 드라이브\...\방송대예습",
    "SUMMARY_SUBDIR": "비우면 '방송대' 사용",
    "PLAYBACK_SPEED": "예: 2.0 (0.5~2.0)",
}
REQUIRED_KEYS = {"KNOU_ID", "KNOU_PW", "GEMINI_API_KEY", "VAULT_PATH"}


def apply_settings(env_path, values: dict) -> list:
    """폼 값을 .env에 저장하고 누락 필수키 리스트를 돌려준다(순수 저장 경로).

    SETTINGS_KEYS만 추려 앞뒤 공백을 제거해 기록한다(기존 주석/미지 키 보존).
    """
    updates = {k: (str(values.get(k) or "")).strip() for k in SETTINGS_KEYS}
    write_env_file(env_path, updates)
    return validate_settings(updates)


def build_settings_view(env_path=ENV_PATH, show_message=None) -> ft.Control:
    """설정 입력 폼 컨트롤을 만든다.

    show_message(text, is_error) 콜백이 있으면 저장 결과를 추가로 알린다
    (없어도 화면 내 배너로 표시).
    """
    data = read_env_file(env_path)
    fields: dict[str, ft.TextField] = {}
    field_rows: list[ft.Control] = []

    for key in SETTINGS_KEYS:
        is_secret = key in SECRET_KEYS
        label = LABELS.get(key, key)
        if key in REQUIRED_KEYS:
            label += " *"
        tf = ft.TextField(
            label=label,
            value=data.get(key, ""),
            hint_text=HINTS.get(key),
            password=is_secret,
            can_reveal_password=is_secret,
            width=560,
        )
        fields[key] = tf
        field_rows.append(tf)

    banner = ft.Text("", size=14)

    def _notify(text: str, is_error: bool) -> None:
        banner.value = text
        banner.color = ft.Colors.RED if is_error else ft.Colors.GREEN
        if show_message:
            try:
                show_message(text, is_error)
            except Exception:
                pass
        try:  # 페이지에 붙어 있으면 즉시 반영(테스트 등 미부착 시 무시)
            banner.update()
        except Exception:
            pass

    def on_save(_=None) -> None:
        values = {k: fields[k].value for k in SETTINGS_KEYS}
        missing = apply_settings(env_path, values)
        if missing:
            names = ", ".join(LABELS.get(k, k) for k in missing)
            _notify(f"필수 항목이 비었습니다: {names}", True)
        else:
            _notify("설정을 저장했습니다 ✓", False)

    save_btn = ft.FilledButton("저장", icon=ft.Icons.SAVE, on_click=on_save)

    def on_make_shortcut(_=None) -> None:
        try:
            res = create_desktop_shortcut()
        except Exception:
            _notify("바로가기 생성에 실패했습니다(PowerShell 확인).", True)
            return
        if res.get("ok"):
            _notify("바탕화면에 '바로가기'를 만들었습니다 ✓ "
                    "(더블클릭하면 앱이 창 없이 열립니다)", False)
        else:
            _notify("바로가기 생성에 실패했습니다(권한/PowerShell 확인).", True)

    shortcut_btn = ft.OutlinedButton(
        "바탕화면 바로가기 만들기", icon=ft.Icons.ADD_LINK,
        tooltip="더블클릭으로 앱을 켤 수 있는 바로가기를 바탕화면에 생성",
        on_click=on_make_shortcut)

    # 첫 실행(필수값 누락) 시 친절 안내 — 설정 마법사 역할.
    first_hint = None
    if validate_settings(data):
        first_hint = ft.Container(
            content=ft.Text(
                "처음이신가요? 아래 필수 항목(*)을 채우고 [저장]을 누르세요. "
                "그다음 '실행' 탭에서 강의를 고르거나 '예약' 탭에서 자동 실행을 거세요.",
                size=13, color=ft.Colors.BLUE),
            bgcolor=ft.Colors.BLUE_50, padding=10, border_radius=8)

    return ft.Column(
        [
            ft.Text("설정", size=24, weight=ft.FontWeight.BOLD),
            ft.Text("아이디·비밀번호·Gemini 키·볼트 경로를 입력하세요. "
                    "별표(*)는 필수입니다.", size=13, color=ft.Colors.GREY),
            *([first_hint] if first_hint else []),
            ft.Divider(),
            *field_rows,
            ft.Row([save_btn, shortcut_btn]),
            banner,
        ],
        spacing=14,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
