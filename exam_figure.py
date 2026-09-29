"""[exam_figure] 기출 시험지에서 그림·표를 잘라 문항에 붙인다.

기출은 PDF 를 AI 가 **읽어** 만들었다. 글은 잘 옮겨졌지만 그림은 남지 않아서,
'아래 그림은 …' 으로 시작하는 문항을 아예 풀 수가 없다.

시험지 PDF 에서 그 문항이 놓인 자리를 찾아 **그림만** 잘라내 형성평가 지문과
같은 통로(quiz_intro 의 intro_image)로 붙인다. 화면도 HTML 도 이미 그 칸을
그리므로 붙이기만 하면 된다.

⚠️ 글자까지 벡터로 인쇄된 PDF 에는 통하지 않는다. 한글 배포용 문서를 '인쇄'
   로 변환한 시험지가 그렇다(글줄이 없어 문항 경계를 찾을 수 없다).
   has_text_layer() 로 미리 가려낸다.

순수 로직(단위테스트 대상):
  - head_no(text)        : '7. 직치 주소지정…' → 7
  - intro_range(text)    : '※ (3～5) …' → (3, 5)
  - is_option(text)      : '① …' 인가(그림은 보기 위에 있다)
  - covers(lo, hi)       : (3, 5) → [3, 4, 5]
  - grow(box, rect)      : 좌표를 직접 넓힌다(두께 0 인 선도 담기게)
  - q_no(qid)            : '2014-2-07' → 7
  - exam_key(text)       : 시험지 머리글 → (연도, 학기)

IO(PyMuPDF):
  - has_text_layer(pdf)  : 좌표로 다룰 수 있는 시험지인가
  - pdf_key(pdf)         : 그 PDF 의 (연도, 학기)
  - page_figures(page)   : {문항번호: 그림 네모}
  - pdf_figures(pdf)     : {문항번호: (쪽, 네모)}
  - render(pdf, 쪽, 네모): PNG bytes
"""
from __future__ import annotations

import re
from pathlib import Path

HEAD_RE = re.compile(r"^\s*(\d{1,2})\s*[.．]\s")
INTRO_RE = re.compile(r"^\s*※\s*\(\s*(\d{1,2})\s*[～~∼\-–]\s*(\d{1,2})\s*\)")
OPT_RE = re.compile(r"^\s*[①②③④⑤]")
QID_RE = re.compile(r"(\d{1,3})\s*$")
KEY_RE = re.compile(r"(\d{4})\s*학년도\s*(\d)\s*학기")

PAD = 5.0           # 잘라낸 그림 둘레에 두는 여백(pt)
ZOOM = 2.2          # 그림을 몇 배로 그릴지(글자가 또렷하게 보이는 정도)
MIN_H = 16.0        # 이보다 납작하면 밑줄 같은 것이다 — 그림이 아니다
MIN_W = 40.0        # 이보다 좁으면 괄호·기호다
MIN_LINES = 6       # 글줄이 이보다 적으면 글자가 벡터로 인쇄된 PDF 다
HEAD_GAP = 10.0     # 문항 첫 줄 아래로 이만큼은 글이다(그림이 아니다)


# ---------------------------------------------------------------------------
# 순수 조각
# ---------------------------------------------------------------------------
def head_no(text):
    """'7. 직치 주소지정방식과 …' → 7 (문항 머리가 아니면 None)."""
    m = HEAD_RE.match(str(text or ""))
    return int(m.group(1)) if m else None


def intro_range(text):
    """'※ (3～5) 다음 프로그램을 …' → (3, 5) (지문 머리가 아니면 None).

    여러 문항이 함께 쓰는 지문이다 — 그림 하나를 그 문항 모두에 붙여야 한다.
    """
    m = INTRO_RE.match(str(text or ""))
    if not m:
        return None
    lo, hi = int(m.group(1)), int(m.group(2))
    return (lo, hi) if lo <= hi else None


def is_option(text) -> bool:
    """'① …' 처럼 보기 줄인가 — 그림은 보기 위에 있다."""
    return bool(OPT_RE.match(str(text or "")))


def covers(lo, hi) -> list:
    """(3, 5) → [3, 4, 5]."""
    lo, hi = int(lo), int(hi)
    return list(range(lo, hi + 1)) if lo <= hi else []


def grow(box, rect):
    """네모를 좌표로 직접 넓힌다 → (x0, y0, x1, y1).

    ⚠️ 표는 **두께 0 인 선**으로 그려진다. PyMuPDF 는 그런 사각형을 '비었다'
       고 보아 union 에서 무시하므로, 좌표를 직접 비교해야 한다.
    """
    x0, y0, x1, y1 = rect
    if box is None:
        return (x0, y0, x1, y1)
    return (min(box[0], x0), min(box[1], y0),
            max(box[2], x1), max(box[3], y1))


def q_no(qid):
    """'2014-2-07' → 7 (번호를 못 읽으면 None)."""
    m = QID_RE.search(str(qid or ""))
    return int(m.group(1)) if m else None


def exam_key(text):
    """시험지 머리글 → (연도, 학기). 못 읽으면 None."""
    m = KEY_RE.search(str(text or ""))
    return (int(m.group(1)), int(m.group(2))) if m else None


def big_enough(box) -> bool:
    """이 네모가 그림이라 할 만한가 — 밑줄·괄호를 걸러낸다."""
    if not box:
        return False
    return (box[2] - box[0]) >= MIN_W and (box[3] - box[1]) >= MIN_H


# ---------------------------------------------------------------------------
# PDF 읽기 (PyMuPDF)
# ---------------------------------------------------------------------------
def _fitz():
    try:
        import pymupdf
    except ImportError:
        return None
    return pymupdf


def page_lines(page) -> list:
    """이 쪽의 글줄 — [{x, y, y1, text}] (읽기 순서와 무관하게 좌표로)."""
    out = []
    for b in page.get_text("dict")["blocks"]:
        for ln in b.get("lines") or []:
            t = "".join(s["text"] for s in ln["spans"]).strip()
            if t:
                out.append({"x": ln["bbox"][0], "y": ln["bbox"][1],
                            "y1": ln["bbox"][3], "text": t})
    return out


def split_columns(page, lines) -> list:
    """2단 조판이면 가운데로 나눈다(1단이면 통째로).

    방송대 시험지는 대개 2단이다. 단을 나누지 않으면 왼쪽 문항의 그림 영역에
    오른쪽 단의 표가 딸려 들어온다.
    """
    mid = page.rect.width / 2
    left = [ln for ln in lines if ln["x"] < mid]
    right = [ln for ln in lines if ln["x"] >= mid]
    return [left, right] if len(right) > 5 else [lines]


def marks(col) -> list:
    """이 단에서 문항·지문이 시작하는 자리 — 위에서 아래 순서로."""
    got = []
    for ln in col or []:
        rng = intro_range(ln["text"])
        if rng:
            got.append({"kind": "intro", "lo": rng[0], "hi": rng[1],
                        "y": ln["y"]})
            continue
        no = head_no(ln["text"])
        if no is not None:
            got.append({"kind": "q", "no": no, "y": ln["y"]})
    got.sort(key=lambda g: g["y"])
    return got


def first_option_y(col, y0, y1):
    """이 구간에서 첫 보기(①)의 y — 그림은 그 위에 있다."""
    ys = [ln["y"] for ln in col or []
          if y0 < ln["y"] < y1 and is_option(ln["text"])]
    return min(ys) if ys else y1


def page_marks_boxes(page) -> list:
    """이 쪽에 그려진 것들의 네모 — 벡터 도형과 **박힌 그림** 모두.

    ⚠️ 같은 시험지 안에서도 쪽마다 다르다. 표·상자는 벡터로, 블록도·회로도는
       래스터 그림으로 들어가 있다. 한쪽만 보면 절반을 놓친다.
    """
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.width < 2 and r.height < 2:        # 점 하나는 그림이 아니다
            continue
        out.append((r.x0, r.y0, r.x1, r.y1))
    try:
        for info in page.get_image_info():
            b = info.get("bbox")
            if b:
                out.append((b[0], b[1], b[2], b[3]))
    except Exception:  # noqa: BLE001 - 그림 정보가 없어도 도형은 쓴다
        pass
    return out


def figure_box(page, x0, x1, y0, y1, boxes=None):
    """이 구간 안에 그려진 것을 감싸는 네모 → (x0,y0,x1,y1) 또는 None."""
    box = None
    for r in (boxes if boxes is not None else page_marks_boxes(page)):
        if not (x0 - 2 <= r[0] and r[2] <= x1 + 2):
            continue
        if not (y0 <= r[1] and r[3] <= y1):
            continue
        box = grow(box, r)
    return box


def page_figures(page) -> dict:
    """이 쪽의 {문항번호: (x0,y0,x1,y1)} — 지문 그림은 그 범위의 문항 모두에."""
    lines = page_lines(page)
    cols = split_columns(page, lines)
    boxes = page_marks_boxes(page)      # 쪽마다 한 번만 모은다(느리다)
    out: dict[int, tuple] = {}
    for ci, col in enumerate(cols):
        if not col:
            continue
        cx0 = min(ln["x"] for ln in col) - 6
        cx1 = (page.rect.width / 2 - 6) if (ci == 0 and len(cols) > 1) \
            else (page.rect.width - 20)
        ms = marks(col)
        for i, m in enumerate(ms):
            y0 = m["y"]
            y1 = ms[i + 1]["y"] if i + 1 < len(ms) else page.rect.height - 40
            top = y0 + HEAD_GAP
            bot = y1 if m["kind"] == "intro" else first_option_y(col, y0, y1)
            box = figure_box(page, cx0, cx1, top, bot, boxes)
            if not big_enough(box):
                continue
            nos = covers(m["lo"], m["hi"]) if m["kind"] == "intro" \
                else [m["no"]]
            for n in nos:
                out.setdefault(n, box)
    return out


def has_text_layer(pdf) -> bool:
    """좌표로 다룰 수 있는 시험지인가.

    한글 배포용 문서를 '인쇄' 로 변환한 PDF 는 글자까지 벡터라 글줄이 없다 —
    문항 경계를 찾을 수 없으므로 손대지 않는다.
    """
    fitz = _fitz()
    if fitz is None or not Path(pdf).exists():
        return False
    try:
        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001 - 손상 파일
        return False
    try:
        for i in range(doc.page_count):
            if len(marks(page_lines(doc[i]))) >= MIN_LINES:
                return True
        return False
    finally:
        doc.close()


def pdf_key(pdf):
    """이 시험지의 (연도, 학기) — 머리글에서 읽는다(못 읽으면 None)."""
    fitz = _fitz()
    if fitz is None or not Path(pdf).exists():
        return None
    try:
        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001 - 손상 파일
        return None
    try:
        for i in range(min(2, doc.page_count)):
            got = exam_key(" ".join(doc[i].get_text().split()))
            if got:
                return got
        return None
    finally:
        doc.close()


def pdf_figures(pdf) -> dict:
    """시험지 한 벌 → {문항번호: (쪽, 네모)}. 앞쪽에서 찾은 것이 이긴다."""
    fitz = _fitz()
    if fitz is None or not Path(pdf).exists():
        return {}
    try:
        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001 - 손상 파일
        return {}
    out: dict[int, tuple] = {}
    try:
        for i in range(doc.page_count):
            for no, box in page_figures(doc[i]).items():
                out.setdefault(no, (i, box))
        return out
    finally:
        doc.close()


def render(pdf, page_no, box, zoom: float = ZOOM, pad: float = PAD) -> bytes:
    """그 네모를 PNG 로 그린다(못 그리면 빈 bytes)."""
    fitz = _fitz()
    if fitz is None or not box:
        return b""
    try:
        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001 - 손상 파일
        return b""
    try:
        page = doc[int(page_no)]
        rect = fitz.Rect(box[0] - pad, box[1] - pad,
                         box[2] + pad, box[3] + pad) & page.rect
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect)
        return pix.tobytes("png")
    except Exception:  # noqa: BLE001 - 한 장 실패가 전체를 막지 않게
        return b""
    finally:
        doc.close()


def find_pdfs(work_dir, course: str) -> list:
    """이 과목의 시험지 PDF 들 — 파일 이름에 과목명이 든 것."""
    d = Path(work_dir)
    if not d.exists():
        return []
    key = str(course or "").replace(" ", "")
    return [p for p in sorted(d.glob("*.pdf")) if key and key in p.name]
