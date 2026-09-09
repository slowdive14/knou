"""resize_embeds 단위테스트 — 이미 만든 노트의 임베드 폭 맞추기.

실측 배경: 캡처 이미지가 원본 해상도 그대로 임베드되어 노트마다 크기가
들쭉날쭉했다. 새 노트는 capture.embed_text 가 폭을 붙이지만, 그 전에 만든
노트 47개(임베드 601개)는 이 도구로 한 번에 맞춰야 했다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from capture import EMBED_WIDTH  # noqa: E402
from resize_embeds import plan_resize, resize_notes  # noqa: E402


# --- 계획 (순수) -----------------------------------------------------------
def test_plan_lists_only_notes_that_change():
    texts = [("a.md", "![[x.jpg]]\n"),
             ("b.md", f"![[y.jpg|{EMBED_WIDTH}]]\n"),   # 이미 맞음
             ("c.md", "임베드 없는 노트\n")]
    plan = plan_resize(texts)
    assert [p["name"] for p in plan] == ["a.md"]
    assert plan[0]["new_text"] == f"![[x.jpg|{EMBED_WIDTH}]]\n"


def test_plan_counts_embeds():
    plan = plan_resize([("a.md", "![[x.jpg]]\n글\n![[y.jpg|400]]\n")])
    assert plan[0]["embeds"] == 2


def test_plan_keeps_the_rest_of_the_note():
    body = "# 제목\n본문 🎬 [00:04:50]\n![[x.jpg]]\n표 |파이프| 유지\n"
    plan = plan_resize([("a.md", body)])
    out = plan[0]["new_text"]
    assert "# 제목" in out and "🎬 [00:04:50]" in out
    assert "표 |파이프| 유지" in out
    assert out.count("![[") == 1


def test_plan_can_strip_the_width():
    plan = plan_resize([("a.md", "![[x.jpg|695]]\n")], width=0)
    assert plan[0]["new_text"] == "![[x.jpg]]\n"


# --- 실제 적용 -------------------------------------------------------------
def _note(d, name, body):
    p = d / name
    p.write_text(body, encoding="utf-8")
    return p


def test_resize_rewrites_the_notes(tmp_path):
    a = _note(tmp_path, "a.md", "![[x.jpg]]\n본문\n")
    res = resize_notes(tmp_path)
    assert a.read_text(encoding="utf-8") == f"![[x.jpg|{EMBED_WIDTH}]]\n본문\n"
    assert res["changed"] == ["a.md"] and res["embeds"] == 1


def test_resize_does_not_touch_an_unchanged_note(tmp_path):
    """내용이 같으면 다시 쓰지 않는다 — 드라이브 동기화 소음을 만들지 않는다."""
    p = _note(tmp_path, "a.md", f"![[x.jpg|{EMBED_WIDTH}]]\n")
    before = p.stat().st_mtime_ns
    res = resize_notes(tmp_path)
    assert res["changed"] == [] and p.stat().st_mtime_ns == before


def test_resize_dry_run_writes_nothing(tmp_path):
    p = _note(tmp_path, "a.md", "![[x.jpg]]\n")
    res = resize_notes(tmp_path, dry_run=True)
    assert res["changed"] == ["a.md"]
    assert p.read_text(encoding="utf-8") == "![[x.jpg]]\n"


def test_resize_leaves_the_images_alone(tmp_path):
    """이미지 파일은 손대지 않는다 — 노트에 적힌 표시 폭만 바꾼다."""
    caps = tmp_path / "_captures"
    caps.mkdir()
    img = caps / "x.jpg"
    img.write_bytes(b"\xff\xd8\xff\xe0jpeg-ish")
    _note(tmp_path, "a.md", "![[x.jpg]]\n")
    resize_notes(tmp_path)
    assert img.read_bytes() == b"\xff\xd8\xff\xe0jpeg-ish"


def test_resize_reports_each_note(tmp_path):
    _note(tmp_path, "a.md", "![[x.jpg]]\n![[y.jpg]]\n")
    said: list[str] = []
    res = resize_notes(tmp_path, on_event=said.append)
    assert any("a.md" in m and "2개" in m for m in said)
    assert res["scanned"] == 1


def test_resize_is_idempotent(tmp_path):
    p = _note(tmp_path, "a.md", "![[x.jpg]]\n")
    resize_notes(tmp_path)
    once = p.read_text(encoding="utf-8")
    assert resize_notes(tmp_path)["changed"] == []
    assert p.read_text(encoding="utf-8") == once


def test_resize_needs_a_real_folder(tmp_path):
    import pytest
    with pytest.raises(NotADirectoryError):
        resize_notes(tmp_path / "없는폴더")


def test_resized_note_still_finds_its_captures(tmp_path):
    """폭을 붙인 뒤에도 참조 판정이 맞아야 한다(캡처 삭제 사고 방지)."""
    from capture import embed_names, orphan_captures
    p = _note(tmp_path, "a.md", "![[이산수학_1강_00-04-50.jpg]]\n")
    resize_notes(tmp_path)
    md = p.read_text(encoding="utf-8")
    assert orphan_captures(["이산수학_1강_00-04-50.jpg"],
                           embed_names(md), "이산수학", 1) == []
