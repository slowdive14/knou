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
  - parse_boxes(raw)     : 모델 응답 → [{nos, box, kind}]
  - scale_box(box, w, h) : 0~1000 좌표 → 쪽 좌표
  - ai_pdf_figures(client, pdf) : {문항번호: (쪽, 네모, 종류)}
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
TIGHT_PAD = 1.5     # 잉크로 경계를 찾은 그림의 여백(pt) — 위아래 글이 걸리지 않게
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
  · 한 문항의 것   : {{"no": 11, "kind": "figure", "box": [y0, x0, y1, x1]}}
  · 여러 문항의 것 : {{"lo": 7, "hi": 9, "kind": "code", "box": [y0, x0, y1, x1]}}

kind 는 상자에 담긴 **프로그램 코드·의사코드**면 "code", 그 밖의 그림·트리·
그래프·표·식이면 "figure" 다. **한 문항에 그림과 코드 상자가 함께 있으면
반드시 따로따로 적어라**(예: 힙 그림 아래에 삽입 함수 코드가 있는 문항).

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
            kind = "code" if str(item.get("kind") or "") == "code" else "figure"
            out.append({"nos": nos, "box": box, "kind": kind})
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
            out.append({"nos": item["nos"], "box": box,
                        "kind": item.get("kind", "figure")})
    return out


# --- 잉크로 경계 찾기 ------------------------------------------------------
# AI 가 준 네모는 다듬게 해도 어림값이었다 — 넓으면 물음 끝·보기 줄이 함께
# 잘리고(2012-2-19), 좁으면 노드가 잘렸다(2012-2-20 의 C). 그래서 네모는
# 출발점으로만 쓰고, 둘레를 넉넉히 그려 **실제 잉크**를 본다.
#   · 가로로 빈 줄이 이어지는 곳에서 덩어리(띠)를 나눈다
#   · 출발 네모와 반 넘게 겹치는 띠를 고른다(그 사이 띠도 함께)
#   · 맨 위·아래에 붙은 글 한 줄짜리 띠(물음 끝·보기 줄)는 떼어 낸다
#   · 남은 띠 안에서 세로로 넓게 빈 곳으로 나눠 출발 네모와 겹치는 조각만
#   · 좌우는 그 네모가 든 **단 전체**를 본다(트리가 네모 밖으로 퍼져 있었다)
#   · 단 구분선·테두리처럼 위아래로 길게 이어진 선은 세지 않는다 — 그 선
#     때문에 모든 줄에 잉크가 있어 위아래 글이 한 덩어리로 묶였다
TIGHT_MARGIN_Y = 40.0   # 위아래로 더 볼 폭(pt) — 잘린 노드까지 닿게
COLUMN_INSET = 4.0      # 단 경계에서 이만큼 안쪽까지만 본다(pt)
TIGHT_ZOOM = 2.0
# 이보다 어두운 화소를 잉크로 본다(0 검정 ~ 255 흰색). 연한 파란 선(트리
# 가지)도 잡아야 한다 — 170 으로 두니 가지가 끊겨 K 노드가 따로 떨어졌다.
INK = 225
TEXT_WIDE = 0.4         # 단 너비의 이 비율 넘게 퍼진 낮은 띠만 글줄로 본다
RULE_FRAC = 0.8         # 이 비율 넘게 위아래로 이어진 칸은 구분선으로 본다
ROW_GAP = 1.0           # 이보다 짧은 빈 줄은 띠를 끊지 않는다(pt)
COL_GAP = 22.0          # 이보다 넓은 빈 칸에서 가로로 나눈다(pt)
TEXT_LINE = 15.0        # 이보다 낮은 띠는 글 한 줄로 본다(pt)


def ink_profile(gray: bytes, width: int, height: int, stride: int,
                ink: int = INK, rule_frac: float = RULE_FRAC):
    """흑백 화소 → (줄마다 잉크 수, 칸마다 잉크 수).

    위아래로 거의 끊김 없이 이어진 칸(단 구분선·상자 테두리)은 둘 다에서
    뺀다.
    """
    cols = [0] * width
    for y in range(height):
        line = gray[y * stride:y * stride + width]
        for x, v in enumerate(line):
            if v < ink:
                cols[x] += 1
    rule = {x for x, n in enumerate(cols) if height and n >= rule_frac * height}
    rows = [0] * height
    for y in range(height):
        line = gray[y * stride:y * stride + width]
        rows[y] = sum(1 for x, v in enumerate(line)
                      if v < ink and x not in rule)
    return rows, [0 if x in rule else n for x, n in enumerate(cols)]


def ink_extent(gray: bytes, width: int, stride: int, y0: int, y1: int,
               skip=(), ink: int = INK) -> int:
    """그 줄들에서 잉크가 퍼진 너비(화소) — 맨 왼쪽부터 맨 오른쪽까지."""
    lo, hi = width, -1
    for y in range(y0, y1):
        line = gray[y * stride:y * stride + width]
        for x, v in enumerate(line):
            if v < ink and x not in skip:
                lo, hi = min(lo, x), max(hi, x)
    return hi - lo + 1 if hi >= lo else 0


def column_of(seed, page_width: float, inset: float = COLUMN_INSET):
    """출발 네모가 든 단의 좌우 (x0, x1) — 시험지는 2단 조판이다.

    네모가 가운데를 크게 걸치면(1단 그림) 쪽 전체를 쓴다.
    """
    mid = float(page_width) / 2
    x0, x1 = float(seed[0]), float(seed[2])
    if x0 < mid - 30 and x1 > mid + 30:
        return (inset, float(page_width) - inset)
    if (x0 + x1) / 2 < mid:
        return (inset, mid - inset)
    return (mid + inset, float(page_width) - inset)


def runs(counts, gap: int) -> list:
    """잉크가 있는 구간들 [(시작, 끝)] — gap 보다 짧은 빈 곳은 잇는다."""
    out = []
    start = last = None
    for i, n in enumerate(counts):
        if n <= 0:
            continue
        if start is None:
            start = last = i
        elif i - last > gap:
            out.append((start, last + 1))
            start = i
        last = i
    if start is not None:
        out.append((start, last + 1))
    return out


def _overlap(a, b) -> float:
    return max(0.0, min(a[1], b[1]) - max(a[0], b[0]))


def pick_bands(bands, seed, line: float, is_text=None) -> list:
    """출발 구간(seed)에 해당하는 띠들 → 이어진 띠 목록(빈 목록이면 못 고름).

    반 넘게 겹치는 띠를 고르고, 그 사이의 띠도 함께 넣는다. 맨 위·아래의
    글 한 줄짜리 띠는 더 큰 띠가 남아 있을 때만 떼어 낸다. is_text 를 주면
    그것이 글줄이라고 한 띠만 뗀다 — 낮기만 한 띠는 따로 떨어진 노드일 수
    있다(2012-2-20 의 K).
    """
    hit = [i for i, b in enumerate(bands)
           if _overlap(b, seed) >= 0.5 * (b[1] - b[0])]
    if not hit:
        best = max(range(len(bands)), key=lambda i: _overlap(bands[i], seed),
                   default=None)
        if best is None or _overlap(bands[best], seed) <= 0:
            return []
        hit = [best]
    got = list(bands[min(hit):max(hit) + 1])

    def tall(b):
        return b[1] - b[0] >= line or (is_text is not None and not is_text(b))

    while len(got) > 1 and not tall(got[0]) and any(tall(b) for b in got[1:]):
        got.pop(0)
    while len(got) > 1 and not tall(got[-1]) and any(tall(b) for b in got[:-1]):
        got.pop()
    return got


def pick_span(pieces, seed) -> tuple | None:
    """세로로 나뉜 조각 중 출발 구간과 겹치는 것들을 감싸는 (시작, 끝)."""
    hit = [p for p in pieces if _overlap(p, seed) > 0]
    if not hit:
        return None
    return (min(p[0] for p in hit), max(p[1] for p in hit))


def tighten_box(pdf, page_no, seed, zoom: float = TIGHT_ZOOM):
    """출발 네모 둘레의 잉크로 그림 경계를 찾는다 → 쪽 좌표 네모(못 찾으면 None)."""
    fitz = _fitz()
    if fitz is None or not seed:
        return None
    try:
        doc = fitz.open(pdf)
    except Exception:  # noqa: BLE001 - 손상 파일
        return None
    try:
        page = doc[int(page_no)]
        cx0, cx1 = column_of(seed, page.rect.width)
        rect = fitz.Rect(cx0, seed[1] - TIGHT_MARGIN_Y,
                         cx1, seed[3] + TIGHT_MARGIN_Y) & page.rect
        pix = page.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=rect,
                              colorspace=fitz.csGRAY, alpha=False)
        rows, cols = ink_profile(pix.samples, pix.width, pix.height,
                                 pix.stride)
        raw_cols = ink_profile(pix.samples, pix.width, pix.height,
                               pix.stride, rule_frac=2.0)[1]
        rule = {x for x, n in enumerate(cols) if n == 0 and raw_cols[x]}

        def is_text(b):
            # 단 너비만큼 퍼진 낮은 띠가 글줄이다(물음 끝·보기 줄)
            return ink_extent(pix.samples, pix.width, pix.stride, b[0], b[1],
                              rule) >= TEXT_WIDE * pix.width
        to_px = lambda v, o: (v - o) * zoom  # noqa: E731
        sy = (to_px(seed[1], rect.y0), to_px(seed[3], rect.y0))
        sx = (to_px(seed[0], rect.x0), to_px(seed[2], rect.x0))
        bands = pick_bands(runs(rows, int(ROW_GAP * zoom)), sy,
                           TEXT_LINE * zoom, is_text)
        if not bands:
            return None
        top, bottom = bands[0][0], bands[-1][1]
        # 고른 띠 안에서만 칸별 잉크를 다시 센다
        sub = pix.samples[top * pix.stride:bottom * pix.stride]
        _r, cols = ink_profile(sub, pix.width, bottom - top, pix.stride)
        span = pick_span(runs(cols, int(COL_GAP * zoom)), sx)
        if span is None:
            return None
        return (rect.x0 + span[0] / zoom, rect.y0 + top / zoom,
                rect.x0 + span[1] / zoom, rect.y0 + bottom / zoom)
    except Exception:  # noqa: BLE001 - 못 찾으면 출발 네모를 쓴다
        return None
    finally:
        doc.close()


def ai_pdf_figures(client, pdf, on_event=None) -> dict:
    """시험지 한 벌을 보여 주고 {문항번호: (쪽, 네모, 종류)} 를 받는다.

    종류는 'code'(코드 상자) 또는 'figure'(그림·표 등). 한 문항에 둘 다
    있으면 **그림** 쪽을 고른다 — 코드는 이미 글로 옮겨져 있다(2018-2-60 은
    힙 그림 없이 코드만 있어서 풀 수가 없었다).
    """
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
                    kind = item.get("kind", "figure")
                    if n not in out or (out[n][2] == "code"
                                        and kind == "figure"):
                        out[n] = (i, item["box"], kind)
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
