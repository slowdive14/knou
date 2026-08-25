"""ui_prefs 단위테스트 — 앱 화면 밝기 저장(시스템/밝게/어둡게).

파일이 없거나 깨졌을 때도 앱이 죽지 않고 기본값으로 떨어지는지까지 확인한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from ui_prefs import (  # noqa: E402
    DEFAULT_THEME,
    THEMES,
    load_prefs,
    load_theme,
    next_theme,
    save_prefs,
    save_theme,
    theme_label,
)


# --- 순환 -----------------------------------------------------------------
def test_next_theme_cycles_three_states():
    assert next_theme("system") == "light"
    assert next_theme("light") == "dark"
    assert next_theme("dark") == "system"


def test_next_theme_full_loop_returns_to_start():
    v = "system"
    for _ in range(3):
        v = next_theme(v)
    assert v == "system"


def test_next_theme_unknown_value_goes_light():
    assert next_theme("보라색") == "light"


def test_theme_label_korean():
    assert theme_label("system") == "시스템"
    assert theme_label("light") == "밝게"
    assert theme_label("dark") == "어둡게"
    assert theme_label("???") == "시스템"


def test_default_theme_is_in_themes():
    assert DEFAULT_THEME in THEMES and len(THEMES) == 3


# --- 저장/불러오기 ----------------------------------------------------------
def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "ui_prefs.json"
    assert save_theme("dark", p) is True
    assert load_theme(p) == "dark"


def test_load_theme_missing_file_is_default(tmp_path):
    assert load_theme(tmp_path / "none.json") == DEFAULT_THEME


def test_load_theme_broken_json_is_default(tmp_path):
    p = tmp_path / "ui_prefs.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_theme(p) == DEFAULT_THEME


def test_load_theme_invalid_value_is_default(tmp_path):
    p = tmp_path / "ui_prefs.json"
    p.write_text(json.dumps({"theme": "무지개"}), encoding="utf-8")
    assert load_theme(p) == DEFAULT_THEME


def test_save_theme_rejects_unknown_value(tmp_path):
    p = tmp_path / "ui_prefs.json"
    save_theme("무지개", p)
    assert load_theme(p) == DEFAULT_THEME


def test_save_theme_keeps_other_prefs(tmp_path):
    p = tmp_path / "ui_prefs.json"
    save_prefs({"other": 1}, p)
    save_theme("light", p)
    prefs = load_prefs(p)
    assert prefs == {"other": 1, "theme": "light"}


def test_prefs_file_has_no_secrets(tmp_path):
    p = tmp_path / "ui_prefs.json"
    save_theme("dark", p)
    text = p.read_text(encoding="utf-8")
    assert "KNOU_PW" not in text and "GEMINI_API_KEY" not in text
