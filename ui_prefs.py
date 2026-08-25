"""[ui_prefs] 앱 화면 설정(화면 밝기) 저장 — 창을 닫아도 고른 값이 남는다.

생성 HTML(ui_theme)은 브라우저에 저장하지만, 앱(Flet)은 저장할 곳이 없어
프로젝트 폴더의 작은 JSON(`ui_prefs.json`)에 담는다. 비밀값은 넣지 않는다
(.env 와 별개 — 여기에는 화면 취향만 들어간다).

  - THEMES              : ("system", "light", "dark") 순환 순서
  - next_theme(cur)     : 다음 값(시스템 → 밝게 → 어둡게 → 시스템)
  - theme_label(v)      : 화면에 보일 문구
  - load_theme(path)    : 저장된 값(없거나 이상하면 "system")
  - save_theme(v, path) : 저장(실패해도 앱이 죽지 않게 조용히 무시)
"""
from __future__ import annotations

import json
from pathlib import Path

PREFS_PATH = Path(__file__).resolve().parent / "ui_prefs.json"

THEMES = ("system", "light", "dark")
DEFAULT_THEME = "system"

_LABELS = {"system": "시스템", "light": "밝게", "dark": "어둡게"}


def next_theme(current: str) -> str:
    """시스템 → 밝게 → 어둡게 → 시스템 순환(모르는 값이면 밝게부터)."""
    try:
        i = THEMES.index(current)
    except ValueError:
        return THEMES[1]
    return THEMES[(i + 1) % len(THEMES)]


def theme_label(value: str) -> str:
    """버튼에 보일 문구."""
    return _LABELS.get(value, _LABELS[DEFAULT_THEME])


def load_prefs(path=PREFS_PATH) -> dict:
    """설정 파일 읽기(없거나 깨졌으면 빈 dict)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_prefs(prefs: dict, path=PREFS_PATH) -> bool:
    """설정 저장. 실패해도 예외를 올리지 않는다(화면 취향일 뿐)."""
    try:
        Path(path).write_text(
            json.dumps(prefs or {}, ensure_ascii=False, indent=1),
            encoding="utf-8")
        return True
    except OSError:
        return False


def load_theme(path=PREFS_PATH) -> str:
    """저장된 화면 밝기(system|light|dark). 없으면 system."""
    v = load_prefs(path).get("theme")
    return v if v in THEMES else DEFAULT_THEME


def save_theme(value: str, path=PREFS_PATH) -> bool:
    """화면 밝기 저장(다른 설정은 보존)."""
    if value not in THEMES:
        value = DEFAULT_THEME
    prefs = load_prefs(path)
    prefs["theme"] = value
    return save_prefs(prefs, path)
