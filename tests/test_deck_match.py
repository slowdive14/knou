"""deck_match 순수 로직 — 빈 표지 슬라이드 판별/제외.

본문 잉크 비율로 '제목만 있고 본문이 텅 빈' 표지/구분 슬라이드를 골라
덱에서 빼는 로직만 검증한다(영상 추출·Gemini 매칭은 수동 검증).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest

pytest.importorskip("PIL")
pytest.importorskip("google.genai")  # deck_match 가 상단에서 import

from PIL import Image, ImageDraw  # noqa: E402

from deck_match import (  # noqa: E402
    body_ink_ratio,
    drop_empty_slides,
    is_empty_slide,
    scrub_empty_embeds,
)


def _img(tmp_path, name, black_box=None):
    """흰 슬라이드(920x660). black_box=(l,t,r,b) 면 그 영역을 검게 칠한다."""
    im = Image.new("RGB", (920, 660), (255, 255, 255))
    if black_box:
        ImageDraw.Draw(im).rectangle(black_box, fill=(10, 10, 30))
    p = tmp_path / name
    im.save(p)
    return p


# --- body_ink_ratio --------------------------------------------------------
def test_body_ink_ratio_white_is_near_zero(tmp_path):
    assert body_ink_ratio(_img(tmp_path, "white.png")) < 0.001


def test_body_ink_ratio_with_content_is_high(tmp_path):
    p = _img(tmp_path, "content.png", black_box=(120, 220, 700, 520))
    assert body_ink_ratio(p) > 0.1


def test_body_ink_ratio_unreadable_returns_one(tmp_path):
    # 못 읽는 경로 → 1.0(보수적으로 '내용 있음')
    assert body_ink_ratio(tmp_path / "nope.png") == 1.0


# --- is_empty_slide --------------------------------------------------------
def test_is_empty_slide_true_for_blank(tmp_path):
    assert is_empty_slide(_img(tmp_path, "blank.png")) is True


def test_is_empty_slide_false_for_content(tmp_path):
    p = _img(tmp_path, "c.png", black_box=(120, 220, 700, 520))
    assert is_empty_slide(p) is False


def test_is_empty_slide_unreadable_kept(tmp_path):
    # 못 읽으면 빈 슬라이드로 보지 않는다(=유지)
    assert is_empty_slide(tmp_path / "missing.png") is False


# --- drop_empty_slides -----------------------------------------------------
def test_drop_empty_slides_filters_and_renumbers(tmp_path):
    blank = _img(tmp_path, "b.png")
    full = _img(tmp_path, "f.png", black_box=(120, 220, 700, 520))
    deck = [
        {"n": 1, "sec": 0, "path": blank},
        {"n": 2, "sec": 10, "path": full},
        {"n": 3, "sec": 20, "path": blank},
    ]
    kept = drop_empty_slides(deck)
    assert len(kept) == 1
    assert kept[0]["sec"] == 10
    assert kept[0]["n"] == 1          # 남은 슬라이드 번호 재정렬


def test_drop_empty_slides_disabled_with_zero_thresh(tmp_path):
    blank = _img(tmp_path, "b.png")
    deck = [{"n": 1, "sec": 0, "path": blank}]
    assert len(drop_empty_slides(deck, thresh=0)) == 1


# --- scrub_empty_embeds (잔존 빈 임베드 청소) ------------------------------
def test_scrub_empty_embeds_removes_blank_keeps_content(tmp_path):
    blank = _img(tmp_path, "blank.png")
    full = _img(tmp_path, "full.png", black_box=(120, 220, 700, 520))
    md = (
        "## 개념A\n- 내용 🎬 [00:10]\n"
        f"![[{full.name}]]\n"
        "## 개념B\n- 내용 🎬 [00:54]\n"
        f"![[{blank.name}]]\n"
    )
    new_md, removed = scrub_empty_embeds(md, tmp_path)
    assert blank.name in removed
    assert f"![[{blank.name}]]" not in new_md
    assert f"![[{full.name}]]" in new_md     # 내용 임베드는 유지
    assert "🎬 [00:54]" in new_md            # 마커(타임스탬프)는 유지


def test_scrub_empty_embeds_keeps_missing_file(tmp_path):
    # 파일이 없으면 함부로 지우지 않는다(보수적)
    md = "글 🎬 [00:01]\n![[gone.png]]\n"
    new_md, removed = scrub_empty_embeds(md, tmp_path)
    assert removed == set()
    assert "![[gone.png]]" in new_md
