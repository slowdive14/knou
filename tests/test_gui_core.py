"""gui_core 순수 로직 단위 테스트 (Phase 1: .env 안전 읽기/쓰기/검증/마스킹).

⚠️ 비밀값(KNOU_PW/GEMINI_API_KEY)은 더미 문자열만 사용. 실제 비밀 미사용.
"""
from __future__ import annotations

import sys
from pathlib import Path

# 프로젝트 루트를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gui_core  # noqa: E402
from gui_core import (  # noqa: E402
    first_run_needed,
    is_frozen,
    mask_secret,
    read_env_file,
    resource_path,
    validate_settings,
    write_env_file,
)


# --- read_env_file ---------------------------------------------------------
def test_read_missing_file_returns_empty(tmp_path):
    assert read_env_file(tmp_path / "nope.env") == {}


def test_read_parses_key_values(tmp_path):
    p = tmp_path / ".env"
    p.write_text("KNOU_ID=myid\nKNOU_PW=secret\n", encoding="utf-8")
    d = read_env_file(p)
    assert d["KNOU_ID"] == "myid"
    assert d["KNOU_PW"] == "secret"


def test_read_ignores_comments_and_blanks(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# 주석\n\nKNOU_ID=myid\n  # 들여쓴 주석\n", encoding="utf-8")
    assert read_env_file(p) == {"KNOU_ID": "myid"}


def test_read_value_with_spaces_and_path(tmp_path):
    p = tmp_path / ".env"
    p.write_text("VAULT_PATH=G:\\내 드라이브\\방송대\n", encoding="utf-8")
    assert read_env_file(p)["VAULT_PATH"] == "G:\\내 드라이브\\방송대"


def test_read_strips_surrounding_quotes(tmp_path):
    p = tmp_path / ".env"
    p.write_text('GEMINI_API_KEY="AIzaQUOTED"\n', encoding="utf-8")
    assert read_env_file(p)["GEMINI_API_KEY"] == "AIzaQUOTED"


def test_read_value_may_contain_equals(tmp_path):
    p = tmp_path / ".env"
    p.write_text("GEMINI_API_KEY=ab==cd\n", encoding="utf-8")
    assert read_env_file(p)["GEMINI_API_KEY"] == "ab==cd"


# --- write_env_file --------------------------------------------------------
def test_write_creates_file(tmp_path):
    p = tmp_path / ".env"
    write_env_file(p, {"KNOU_ID": "myid"})
    assert read_env_file(p)["KNOU_ID"] == "myid"


def test_write_updates_existing_key_in_place(tmp_path):
    p = tmp_path / ".env"
    p.write_text("KNOU_ID=old\nKNOU_PW=secret\n", encoding="utf-8")
    write_env_file(p, {"KNOU_ID": "new"})
    d = read_env_file(p)
    assert d["KNOU_ID"] == "new"
    assert d["KNOU_PW"] == "secret"  # 다른 키 보존


def test_write_preserves_comments_and_unknown_keys(tmp_path):
    p = tmp_path / ".env"
    p.write_text("# 헤더 주석\nKNOU_ID=old\nUNKNOWN=keepme\n", encoding="utf-8")
    write_env_file(p, {"KNOU_ID": "new"})
    text = p.read_text(encoding="utf-8")
    assert "# 헤더 주석" in text       # 주석 보존
    assert "UNKNOWN=keepme" in text     # 미지 키 보존
    assert "KNOU_ID=new" in text


def test_write_appends_new_keys(tmp_path):
    p = tmp_path / ".env"
    p.write_text("KNOU_ID=myid\n", encoding="utf-8")
    write_env_file(p, {"GEMINI_API_KEY": "AIzaNEW"})
    d = read_env_file(p)
    assert d["KNOU_ID"] == "myid"
    assert d["GEMINI_API_KEY"] == "AIzaNEW"


def test_write_roundtrip_preserves_korean_path(tmp_path):
    p = tmp_path / ".env"
    write_env_file(p, {"VAULT_PATH": "G:\\내 드라이브\\방송대"})
    assert read_env_file(p)["VAULT_PATH"] == "G:\\내 드라이브\\방송대"


# --- mask_secret -----------------------------------------------------------
def test_mask_empty_is_blank():
    assert mask_secret("") == ""
    assert mask_secret(None) == ""


def test_mask_short_reveals_nothing():
    assert "…(가림)" in mask_secret("abc")
    assert "abc" not in mask_secret("abc")


def test_mask_long_reveals_prefix_only():
    out = mask_secret("AIzaSyABCDEFG")
    assert out.startswith("AIza")
    assert "…(가림)" in out
    assert "ABCDEFG" not in out


# --- validate_settings -----------------------------------------------------
def test_validate_all_present_returns_empty():
    d = {"KNOU_ID": "x", "KNOU_PW": "y", "GEMINI_API_KEY": "z", "VAULT_PATH": "C:/v"}
    assert validate_settings(d) == []


def test_validate_missing_lists_keys():
    missing = validate_settings({"KNOU_ID": "x"})
    assert "KNOU_PW" in missing
    assert "GEMINI_API_KEY" in missing
    assert "VAULT_PATH" in missing
    assert "KNOU_ID" not in missing


def test_validate_blank_counts_missing():
    d = {"KNOU_ID": "  ", "KNOU_PW": "y", "GEMINI_API_KEY": "z", "VAULT_PATH": "v"}
    assert "KNOU_ID" in validate_settings(d)


# --- first_run_needed ------------------------------------------------------
def test_first_run_needed_when_missing_file(tmp_path):
    assert first_run_needed(tmp_path / "nope.env") is True


def test_first_run_not_needed_when_complete(tmp_path):
    p = tmp_path / ".env"
    p.write_text(
        "KNOU_ID=x\nKNOU_PW=y\nGEMINI_API_KEY=z\nVAULT_PATH=C:/v\n",
        encoding="utf-8",
    )
    assert first_run_needed(p) is False


# --- is_frozen / resource_path (Phase 5: 패키징 대비) ----------------------
def test_is_frozen_false_in_source_run():
    # 소스(테스트)로 돌 땐 패키징 아님.
    assert is_frozen() is False


def test_resource_path_source_uses_base_dir():
    from config import BASE_DIR
    p = resource_path("assets/icon.ico")
    assert p == Path(BASE_DIR) / "assets/icon.ico"


def test_resource_path_explicit_base_wins(tmp_path):
    p = resource_path("icon.ico", base=tmp_path)
    assert p == tmp_path / "icon.ico"


def test_resource_path_frozen_uses_meipass(tmp_path, monkeypatch):
    # 패키징 상태를 흉내: sys.frozen + sys._MEIPASS → 그 경로 기준.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "_MEIPASS", str(tmp_path), raising=False)
    assert gui_core.is_frozen() is True
    assert resource_path("icon.ico") == tmp_path / "icon.ico"
