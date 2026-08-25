"""open_target 단위테스트 — 예습노트만 옵시디언으로, 나머지는 기본 프로그램.

URI 조립·판정은 순수 함수로 검증하고, 실제 실행(open_path)은 파일 없음·
호출 경로만 확인한다(옵시디언을 실제로 띄우지 않는다).
"""
from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import unquote, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import open_target  # noqa: E402
from open_target import (  # noqa: E402
    is_note,
    obsidian_uri,
    open_path,
    target_for,
)


# --- 판정 -----------------------------------------------------------------
def test_markdown_is_note():
    assert is_note("a.md") and is_note("A.MD") and is_note("b.markdown")


def test_other_files_are_not_notes():
    for name in ("a.mp3", "b.pdf", "c.html", "d.pptx", "e"):
        assert not is_note(name)


def test_target_for_splits_note_and_rest():
    assert target_for("노트.md") == "obsidian"
    assert target_for("강의.mp3") == "external"
    assert target_for("강의록.pdf") == "external"


# --- URI ------------------------------------------------------------------
def test_obsidian_uri_uses_path_param():
    uri = obsidian_uri(r"C:\vault\note.md")
    assert uri.startswith("obsidian://open?path=")
    assert "vault=" not in uri          # 볼트 이름 없이 절대경로만으로 연다


def test_obsidian_uri_encodes_korean_and_spaces():
    p = r"G:\내 드라이브\방송대예습\C프로그래밍 1강 - 개요.md"
    uri = obsidian_uri(p)
    assert " " not in uri and "\\" not in uri     # 전부 퍼센트 인코딩
    got = unquote(uri.split("path=", 1)[1])
    assert got == str(Path(p))                    # 디코딩하면 원래 경로


def test_obsidian_uri_scheme_is_obsidian():
    assert urlparse(obsidian_uri("a.md")).scheme == "obsidian"


# --- open_path ------------------------------------------------------------
def test_open_path_missing_file_is_error(tmp_path):
    r = open_path(tmp_path / "none.md")
    assert r["ok"] is False and "없" in r["error"]


def test_open_path_note_goes_to_obsidian(tmp_path, monkeypatch):
    p = tmp_path / "노트.md"
    p.write_text("# 노트", encoding="utf-8")
    seen = []
    monkeypatch.setattr(open_target, "_start", lambda t: seen.append(t))
    r = open_path(p)
    assert r["ok"] and r["how"] == "obsidian"
    assert seen and seen[0].startswith("obsidian://open?path=")


def test_open_path_other_file_goes_external(tmp_path, monkeypatch):
    p = tmp_path / "강의.mp3"
    p.write_bytes(b"x")
    seen = []
    monkeypatch.setattr(open_target, "_start", lambda t: seen.append(t))
    r = open_path(p)
    assert r["ok"] and r["how"] == "external"
    assert seen == [str(p)]


def test_open_path_falls_back_when_obsidian_missing(tmp_path, monkeypatch):
    # 옵시디언 미설치(프로토콜 미등록) → 기본 프로그램으로 한 번 더 시도
    p = tmp_path / "노트.md"
    p.write_text("x", encoding="utf-8")
    calls = []

    def fake(target):
        calls.append(target)
        if target.startswith("obsidian://"):
            raise OSError("no handler")

    monkeypatch.setattr(open_target, "_start", fake)
    r = open_path(p)
    assert r["ok"] and r["how"] == "external"
    assert len(calls) == 2 and "옵시디언" in r["error"]


def test_open_path_can_skip_obsidian(tmp_path, monkeypatch):
    p = tmp_path / "노트.md"
    p.write_text("x", encoding="utf-8")
    seen = []
    monkeypatch.setattr(open_target, "_start", lambda t: seen.append(t))
    r = open_path(p, prefer_obsidian=False)
    assert r["how"] == "external" and seen == [str(p)]
