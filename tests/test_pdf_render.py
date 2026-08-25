"""pdf_render 단위테스트 — 강의록 PDF 를 앱 안에서 그리기.

임시 PDF 를 직접 만들어(외부 파일 의존 없음) 페이지 수·렌더 결과·범위 보정을
검증한다. PyMuPDF 가 없는 환경에서는 렌더 관련 테스트를 건너뛴다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pdf_render import (  # noqa: E402
    DEFAULT_ZOOM,
    page_size,
    MAX_ZOOM,
    MIN_ZOOM,
    available,
    clamp_page,
    clamp_zoom,
    page_count,
    render_page,
)

needs_fitz = pytest.mark.skipif(not available(), reason="PyMuPDF 미설치")


@pytest.fixture
def sample_pdf(tmp_path):
    """3쪽짜리 임시 PDF."""
    fitz = pytest.importorskip("fitz")
    p = tmp_path / "sample.pdf"
    doc = fitz.open()
    for i in range(3):
        page = doc.new_page()
        page.insert_text((72, 100), f"page {i + 1}")
    doc.save(str(p))
    doc.close()
    return p


# --- 범위 보정(순수) --------------------------------------------------------
def test_clamp_page_keeps_inside_range():
    assert clamp_page(-3, 5) == 0
    assert clamp_page(9, 5) == 4
    assert clamp_page(2, 5) == 2


def test_clamp_page_empty_document():
    assert clamp_page(3, 0) == 0


def test_clamp_zoom_bounds():
    assert clamp_zoom(99) == MAX_ZOOM
    assert clamp_zoom(0.01) == MIN_ZOOM
    assert clamp_zoom(1.5) == 1.5


def test_default_zoom_within_bounds():
    assert MIN_ZOOM <= DEFAULT_ZOOM <= MAX_ZOOM


# --- 파일 처리 -------------------------------------------------------------
def test_page_count_missing_file_is_zero(tmp_path):
    assert page_count(tmp_path / "none.pdf") == 0


def test_render_missing_file_is_empty(tmp_path):
    assert render_page(tmp_path / "none.pdf") == b""


def test_broken_pdf_is_safe(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"not a pdf at all")
    assert page_count(p) == 0 and render_page(p) == b""


@needs_fitz
def test_page_count_reads_real_pdf(sample_pdf):
    assert page_count(sample_pdf) == 3


@needs_fitz
def test_render_page_returns_png(sample_pdf):
    data = render_page(sample_pdf, 0)
    assert data[:4] == b"\x89PNG" and len(data) > 100


@needs_fitz
def test_render_page_clamps_out_of_range(sample_pdf):
    # 마지막 쪽을 넘겨도 마지막 쪽이 나온다(예외 없이)
    assert render_page(sample_pdf, 99)[:4] == b"\x89PNG"


@needs_fitz
def test_bigger_zoom_makes_bigger_image(sample_pdf):
    small = render_page(sample_pdf, 0, zoom=0.8)
    big = render_page(sample_pdf, 0, zoom=2.5)
    assert len(big) > len(small)


# --- page_size (스크롤 위치 계산용) -----------------------------------------
@needs_fitz
def test_page_size_reads_real_pdf(sample_pdf):
    w, h = page_size(sample_pdf)
    assert w > 0 and h > 0


def test_page_size_missing_file_is_a4(tmp_path):
    assert page_size(tmp_path / "none.pdf") == (595.0, 842.0)


def test_page_size_broken_pdf_is_a4(tmp_path):
    p = tmp_path / "broken.pdf"
    p.write_bytes(b"nope")
    assert page_size(p) == (595.0, 842.0)
