"""[pdf_render] 강의록 PDF → 앱 안에서 볼 수 있는 페이지 이미지.

Flet 에는 PDF 뷰어가 없어서, PyMuPDF 로 페이지를 PNG 로 그려 `ft.Image` 에 실어
앱 창 안에서 넘겨 본다(외부 PDF 프로그램을 띄우지 않는다).

  - page_count(pdf)            : 총 페이지 수(못 열면 0)
  - page_size(pdf, i)          : 페이지 크기(포인트) — 스크롤 위치 계산용
  - render_page(pdf, i, zoom)  : i(0-based) 페이지 → PNG bytes
  - render_page_b64(pdf, i, …) : 같은 것을 base64 문자열로(ft.Image src_base64)
  - clamp_page(i, total)       : 페이지 번호를 범위 안으로

PyMuPDF(pymupdf)가 없으면 ImportError 대신 빈 결과/0 을 돌려주고, 화면은
'앱에서 열 수 없음' 안내로 떨어진다(앱이 죽지 않게).
"""
from __future__ import annotations

import base64
from pathlib import Path

DEFAULT_ZOOM = 1.7          # 100% 기준 배율(글자가 또렷하게 보이는 정도)
MAX_ZOOM = 4.0
MIN_ZOOM = 0.6


def _fitz():
    try:
        import fitz  # PyMuPDF
    except Exception:  # noqa: BLE001 - 미설치/로드 실패 모두 '없음'으로
        return None
    return fitz


def available() -> bool:
    """앱 안에서 PDF 를 그릴 수 있는 환경인가."""
    return _fitz() is not None


def clamp_page(i: int, total: int) -> int:
    """페이지 번호(0-based)를 0..total-1 안으로."""
    if total <= 0:
        return 0
    return max(0, min(int(i), total - 1))


def clamp_zoom(z: float) -> float:
    return max(MIN_ZOOM, min(float(z), MAX_ZOOM))


def page_count(pdf_path) -> int:
    """총 페이지 수(열 수 없으면 0)."""
    fitz = _fitz()
    p = Path(pdf_path)
    if fitz is None or not p.exists():
        return 0
    try:
        with fitz.open(str(p)) as doc:
            return int(doc.page_count)
    except Exception:  # noqa: BLE001 - 손상/암호 PDF
        return 0


def page_size(pdf_path, index: int = 0) -> tuple[float, float]:
    """페이지 크기(포인트) — 화면에 놓을 높이를 미리 계산해 스크롤 위치를 알기 위함.

    못 읽으면 A4 세로(595×842)로 가정한다.
    """
    fitz = _fitz()
    p = Path(pdf_path)
    if fitz is None or not p.exists():
        return (595.0, 842.0)
    try:
        with fitz.open(str(p)) as doc:
            if doc.page_count <= 0:
                return (595.0, 842.0)
            r = doc.load_page(clamp_page(index, doc.page_count)).rect
            w, h = float(r.width), float(r.height)
            return (w, h) if w > 0 and h > 0 else (595.0, 842.0)
    except Exception:  # noqa: BLE001
        return (595.0, 842.0)


def render_page(pdf_path, index: int = 0, zoom: float = DEFAULT_ZOOM) -> bytes:
    """PDF 한 페이지를 PNG bytes 로(실패하면 빈 bytes)."""
    fitz = _fitz()
    p = Path(pdf_path)
    if fitz is None or not p.exists():
        return b""
    try:
        with fitz.open(str(p)) as doc:
            if doc.page_count <= 0:
                return b""
            page = doc.load_page(clamp_page(index, doc.page_count))
            z = clamp_zoom(zoom)
            pix = page.get_pixmap(matrix=fitz.Matrix(z, z), alpha=False)
            return pix.tobytes("png")
    except Exception:  # noqa: BLE001
        return b""


def render_page_b64(pdf_path, index: int = 0, zoom: float = DEFAULT_ZOOM) -> str:
    """render_page 결과를 base64 문자열로(ft.Image(src_base64=…) 용)."""
    data = render_page(pdf_path, index, zoom)
    return base64.b64encode(data).decode("ascii") if data else ""
