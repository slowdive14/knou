"""[exam_figure] 기출 시험지에서 그림·표를 잘라 문항에 붙인다.

기출은 PDF 를 AI 가 **읽어** 만들었다. 글은 잘 옮겨졌지만 그림은 남지 않아서,
'아래 그림은 …' 으로 시작하는 문항을 아예 풀 수가 없다.

시험지 PDF 에서 그 문항이 놓인 자리를 찾아 **그림만** 잘라내 형성평가 지문과
같은 통로(quiz_intro 의 intro_image)로 붙인다. 화면도 HTML 도 이미 그 칸을
그리므로 붙이기만 하면 된다.

글줄이 없는 시험지도 있다. 한글 배포용 문서를 '인쇄' 로 변환하면 글자까지
벡터가 되어(도형이 30만 개) 문항 경계를 좌표로 찾을 수 없다. 그럴 때는 지면을
**그림으로 보여 주고** 자료의 자리를 물어본다(ai_ 로 시작하는 함수들).
has_text_layer() 로 어느 길을 쓸지 가른다.

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

글줄이 없는 시험지용(지면을 보여 주고 묻는다):
  - parse_boxes(raw)     : 모델 응답 → [{nos, box}]
  - scale_box(box, w, h) : 0~1000 좌표 → 쪽 좌표
  - ai_pdf_figures(client, pdf) : {문항번호: (쪽, 네모)}
  - ai_pdf_key(client, pdf)     : (연도, 학기)
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


# ---------------------------------------------------------------------------
# 글줄이 없는 시험지 — 지면을 보여 주고 물어본다
# ---------------------------------------------------------------------------
# 한글 배포용 문서를 '인쇄' 로 변환한 PDF 는 글자까지 벡터라(도형이 30만 개)
# 문항 경계를 좌표로 찾을 수 없다. 그럴 때만 쓰는 길이다.
FIGURE_PROMPT = """이것은 한국방송통신대학교 기말시험 문제지 한 쪽이다(보통 2단 조판).

이 쪽에 그려진 **시각 자료를 하나도 빠짐없이** 찾아라. 시각 자료란 글자만
옮겨 적어서는 문제를 풀 수 없는 것이다: 그림·블록도·회로도·표·상자에 담긴
프로그램 코드·테두리를 두른 식.

**특히 놓치기 쉬운 것 — 여러 문항이 함께 쓰는 지문의 자료다.**
'※ (7~9) 아래 그림은 …' 처럼 범위가 적힌 안내문 아래에 놓인 그림이나 표는
그 범위의 모든 문항에 딸린 것이다. 반드시 찾아서 lo·hi 로 적어라.

자료마다 이렇게 적는다:
  · 한 문항의 것   : {{"no": 11, "box": [y0, x0, y1, x1]}}
  · 여러 문항의 것 : {{"lo": 7, "hi": 9, "box": [y0, x0, y1, x1]}}

box 는 그 자료만 감싸는 네모다. 쪽 전체를 0~1000 으로 본 값으로,
[위, 왼쪽, 아래, 오른쪽] 차례다. **문항 글과 보기(①②③④)는 빼라.**

머리말(학과·학번·감독관 칸), 쪽 번호, 단 구분선, 과목 안내 상자는 넣지 마라.

먼저 이 쪽의 문항 번호를 왼쪽 단 위에서 아래로, 이어서 오른쪽 단 위에서
아래로 훑어보고, 각 문항에 딸린 자료가 있는지 하나씩 확인하라.

JSON 배열만 출력하라. 없으면 [] 만 출력하라."""

KEY_PROMPT = """이것은 한국방송통신대학교 기말시험 문제지의 첫 쪽이다.

맨 위에 적힌 **학년도와 학기**를 읽어라. '2014학년도 2 학기' 처럼 적혀 있다.

{"year": 2014, "term": 2} 형식의 JSON 만 출력하라. 읽을 수 없으면 {} 만."""

AI_ZOOM = 2.0       # 지면을 몇 배로 그려 보여줄지(글자가 읽히는 정도)
MAX_NO = 99         # 이보다 큰 번호는 문항 번호가 아니다


def parse_boxes(raw) -> list:
    """모델 응답 → [{"nos": [번호…], "box": [y0,x0,y1,x1]}] (못 읽으면 빈 목록).

    0~1000 으로 정규화된 좌표를 그대로 담는다 — 쪽 크기를 곱하는 일은
    scale_box 가 한다.
    """
    import json

    s = str(raw or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
    s = re.sub(r"\n?```$", "", s).strip()
    try:
        got = json.loads(s)
    except ValueError:
        return []
    if not isinstance(got, list):
        return []
    out = []
    for item in got:
        if not isinstance(item, dict):
            continue
        box = item.get("box")
        if not isinstance(box, (list, tuple)) or len(box) != 4:
            continue
        try:
            box = [float(v) for v in box]
        except (TypeError, ValueError):
            continue
        lo, hi = item.get("lo"), item.get("hi")
        shared = lo is not None and hi is not None
        try:
            nos = (covers(int(lo), int(hi)) if shared
                   else [int(item.get("no"))])
        except (TypeError, ValueError):
            continue
        nos = [n for n in nos if 1 <= n <= MAX_NO]
        if nos:
            out.append({"nos": nos, "box": box})
    return out


def scale_box(box, width, height):
    """0~1000 좌표 → 쪽 좌표 (x0, y0, x1, y1). 뒤집혀 있으면 바로잡는다."""
    if not box or len(box) != 4:
        return None
    y0, x0, y1, x1 = [float(v) / 1000 for v in box]
    x0, x1 = sorted((x0 * float(width), x1 * float(width)))
    y0, y1 = sorted((y0 * float(height), y1 * float(height)))
    return (x0, y0, x1, y1)


def ai_page_figures(client, pdf, page_no, width, height,
                    on_event=None) -> list:
    """한 쪽을 보여 주고 시각 자료를 받는다 → [{"nos", "box"(쪽 좌표)}]."""
    from google.genai import types

    from pdf_render import render_page
    from summarize import MAX_OUTPUT_TOKENS, _resp_text, generate

    img = render_page(pdf, page_no, AI_ZOOM, fmt="png")
    if not img:
        return []
    try:
        resp = generate(
            client,
            [types.Part.from_bytes(data=img, mime_type="image/png"),
             FIGURE_PROMPT],
            on_event=on_event,
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS))
    except Exception as e:  # noqa: BLE001 - 한 쪽 실패가 전체를 막지 않게
        if on_event:
            on_event(f"   {page_no + 1}쪽을 읽지 못했습니다 — {str(e)[:70]}")
        return []
    out = []
    for item in parse_boxes(_resp_text(resp)):
        box = scale_box(item["box"], width, height)
        if box and big_enough(box):
            out.append({"nos": item["nos"], "box": box})
    return out


def ai_pdf_figures(client, pdf, on_event=None) -> dict:
    """시험지 한 벌을 보여 주고 {문항번호: (쪽, 네모)} 를 받는다."""
    fitz = _fitz()
    if fitz is None or client is None or not Path(pdf).exists():
        return {}
    try:
        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001 - 손상 파일
        return {}
    out: dict[int, tuple] = {}
    try:
        for i in range(doc.page_count):
            page = doc[i]
            for item in ai_page_figures(client, pdf, i, page.rect.width,
                                        page.rect.height, on_event):
                for n in item["nos"]:
                    out.setdefault(n, (i, item["box"]))
        return out
    finally:
        doc.close()


def ai_pdf_key(client, pdf, on_event=None):
    """첫 쪽을 보여 주고 (연도, 학기)를 받는다 — 머리글을 글로 못 읽을 때."""
    import json

    from google.genai import types

    from pdf_render import render_page
    from summarize import _resp_text, generate

    if client is None or not Path(pdf).exists():
        return None
    img = render_page(pdf, 0, AI_ZOOM, fmt="png")
    if not img:
        return None
    try:
        resp = generate(
            client,
            [types.Part.from_bytes(data=img, mime_type="image/png"),
             KEY_PROMPT],
            on_event=on_event,
            config=types.GenerateContentConfig(max_output_tokens=2048))
        s = re.sub(r"^```[a-zA-Z]*\n?", "", _resp_text(resp).strip())
        got = json.loads(re.sub(r"\n?```$", "", s).strip())
        return (int(got["year"]), int(got["term"]))
    except Exception:  # noqa: BLE001 - 못 읽으면 그 시험지는 건너뛴다
        return None


def find_pdfs(work_dir, course: str) -> list:
    """이 과목의 시험지 PDF 들 — 파일 이름에 과목명이 든 것."""
    d = Path(work_dir)
    if not d.exists():
        return []
    key = str(course or "").replace(" ", "")
    return [p for p in sorted(d.glob("*.pdf")) if key and key in p.name]
