"""[exam_files] 기출 원본 — 회차마다 시험지와 정답표 파일을 짝지어 둔다.

퀴즈에서 '2015-2 시험지' 를 누르면 그 회차의 원본이 열려야 한다. 그런데
파일 이름만으로는 회차를 알 수 없다.

  · 시험지 — 자료실의 첨부 이름은 회차마다 다르지 않다(2015-2 와 2017-2
    컴퓨터구조가 둘 다 '240-컴퓨터구조-3학년-3교시-(3p)'). 머리글의 학년도·
    학기를 읽어야 한다. 글자 층이 없는 PDF 는 AI 가 읽어야 하므로, **한 번
    읽은 것은 회차표.json 에 적어 두고** 다시 묻지 않는다. 화면을 열 때마다
    AI 를 부를 수는 없다.

  · 정답표 — 한 파일에 여러 회차가 들어 있을 수 있다.
      - ZIP 하나에 일곱 해(2014~2020) → 풀어 둔 회차별 파일을 가리킨다.
        ZIP 자체는 열지 않는다.
      - 학기 파일 하나에 전 학과·전 학년 과목 → 그 과목 줄을 찾아 둔다.
      - 문서 하나에 여러 해 → '2015학년도 2학기' 머리줄로 구간을 나누고, 그
        회차 구간 안에서만 과목 줄을 찾는다. 파일 전체에서 첫 줄을 집으면 늘
        맨 앞 해의 답이 나온다.
    열 때는 PDF 면 그 과목 줄이 있는 쪽만 잘라(줄에 형광 표시) 연다. HWP 는
    자를 수 없어 통째로 열고, 어디를 보면 되는지 말한다.

순수 로직(단위테스트 대상):
  - section_key(line)          : 머리줄 → (연도, 학기). 여러 해가 적힌 묶음 제목은 아니다
  - split_sections(lines, fb)  : 줄 목록 → 회차 구간들
  - term_label(key)            : (2015, 2) → '2015-2'
  - answer_hint(spot, course)  : 열고 나서 화면에 남길 한 줄

IO:
  - load_index / save_index / remember : 회차표.json (시험지 → 회차)
  - sheet_key(pdf, client, idx)        : 시험지 한 장의 회차(표 → 글줄 → AI 순)
  - sheet_files(work, course, client)  : {(연도, 학기): [시험지 PDF]}
  - answer_spots(work, course)         : {(연도, 학기): 정답표 속 그 과목 자리}
  - course_terms(work, course)         : 화면에 늘어놓을 회차 목록
  - answer_target(spot, course)        : 실제로 열 파일(PDF 면 잘라 낸 쪽)

⚠️ 원본 파일은 읽기만 한다. 잘라 낸 쪽은 정답표/_발췌 에 따로 쓴다.
"""
from __future__ import annotations

import json
import os
import re
from functools import lru_cache
from pathlib import Path

import exam_bank as eb

INDEX_NAME = "회차표.json"
ANSWER_DIR = "정답표"
EXCERPT_DIR = "_발췌"
MANUAL_DIR = "직접받은PDF"          # hwp_convert.MANUAL_DIR 과 같은 자리
ANSWER_EXTS = (".hwp", ".hwpx", ".pdf")
HIGHLIGHT = (1.0, 0.85, 0.2)       # 잘라 낸 쪽에서 과목 줄을 칠하는 색
ROW_MARGIN = 20.0                  # 줄을 칠할 때 쪽 가장자리에 남기는 여백(pt)

_HEAD_RE = re.compile(r"(20\d{2})\s*학년도\s*([12])\s*학기")
_YEAR_RE = re.compile(r"20\d{2}")
_MANUAL_RE = re.compile(r"_(20\d{2})-([12])\.pdf$", re.IGNORECASE)


def _norm(text) -> str:
    return re.sub(r"\s+", "", str(text or ""))


# ---------------------------------------------------------------------------
# 순수 조각
# ---------------------------------------------------------------------------
def section_key(line):
    """머리줄 → (연도, 학기). 머리줄이 아니면 None.

    '2014학년도 1학기 ~ 2020학년도 2학기 정답 모음' 처럼 **여러 해가 적힌 줄**은
    묶음 전체의 제목이지 한 회차의 시작이 아니다 — 구간을 열지 않는다.
    """
    s = str(line or "")
    m = _HEAD_RE.search(s)
    if not m or len(set(_YEAR_RE.findall(s))) > 1:
        return None
    return (int(m.group(1)), int(m.group(2)))


def split_sections(lines, fallback=None) -> list:
    """줄 목록 → [{"key", "start", "end"}] — 회차마다 한 구간.

    쪽마다 되풀이되는 머리말(같은 회차가 연달아 나오는 것)은 한 구간으로
    합친다. 머리줄이 하나도 없으면 파일 이름에서 읽은 fallback 하나로 본다.
    """
    rows = list(lines or [])
    out: list[dict] = []
    for i, line in enumerate(rows):
        k = section_key(line)
        if k is None or (out and out[-1]["key"] == k):
            continue
        if out:
            out[-1]["end"] = i
        out.append({"key": k, "start": i, "end": len(rows)})
    if not out and fallback:
        out.append({"key": tuple(fallback), "start": 0, "end": len(rows)})
    return out


def term_label(key) -> str:
    """(2015, 2) → '2015-2'."""
    y, t = key
    return f"{int(y)}-{int(t)}"


def answer_hint(spot, course) -> str:
    """정답표를 열고 나서 남길 한 줄 — 어디를 보면 되는지."""
    spot = spot or {}
    y, t = spot.get("key") or (0, 0)
    head = f"{y}학년도 {t}학기 정답표"
    pages = spot.get("pages") or []
    if pages:
        where = (f"{pages[0] + 1}쪽" if len(pages) == 1 else
                 f"{pages[0] + 1}~{pages[-1] + 1}쪽")
        return f"{head}에서 {course} 줄이 있는 {where}만 열었습니다(노란 표시)"
    many = " · 여러 해가 든 파일이니 이 학기 구간에서" if spot.get("many") else ""
    return f"{head}를 열었습니다{many} '{course}' 줄을 찾으세요(Ctrl+F)"


# ---------------------------------------------------------------------------
# 시험지 → 회차 (회차표.json)
# ---------------------------------------------------------------------------
def index_path(work) -> Path:
    return Path(work) / INDEX_NAME


def load_index(work) -> dict:
    """회차표를 읽는다 — {"sheets": {파일명: {"key": [연도, 학기], "size": 바이트}}}."""
    p = index_path(work)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"sheets": {}}
    if not isinstance(data, dict) or not isinstance(data.get("sheets"), dict):
        return {"sheets": {}}
    return data


def save_index(work, idx) -> Path:
    """회차표를 저장한다 — 임시 파일에 쓴 뒤 바꿔치기(AI 로 읽은 값이다)."""
    p = index_path(work)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(idx, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)
    return p


def _size(path) -> int:
    try:
        return Path(path).stat().st_size
    except OSError:
        return -1


def _rel(work, path) -> str:
    """회차표에 적는 이름 — 기출 폴더 기준 상대 경로(직접받은PDF/… 도 갈리게)."""
    try:
        return Path(path).relative_to(Path(work)).as_posix()
    except ValueError:
        return Path(path).name


def known_key(idx, work, path):
    """회차표에 적힌 회차 — 파일이 바뀌었으면(크기가 다르면) 모르는 것으로."""
    got = ((idx or {}).get("sheets") or {}).get(_rel(work, path)) or {}
    key = got.get("key")
    if not key or got.get("size") != _size(path):
        return None
    try:
        return (int(key[0]), int(key[1]))
    except (TypeError, ValueError, IndexError):
        return None


def note_key(idx, work, path, key) -> None:
    """회차표에 한 장을 적는다(저장은 부르는 쪽이)."""
    idx.setdefault("sheets", {})[_rel(work, path)] = {
        "key": [int(key[0]), int(key[1])], "size": _size(path)}


def remember(work, path, key) -> None:
    """시험지 한 장의 회차를 바로 적어 둔다 — 기출을 담을 때 부른다.

    담는 쪽은 이미 회차를 안다(자료실 글 제목). 그때 적어 두면 나중에 AI 로
    다시 읽을 일이 없다.
    """
    if not key:
        return
    idx = load_index(work)
    note_key(idx, work, path, key)
    save_index(work, idx)


def sheet_key(path, client=None, idx=None, work=None, on_event=None):
    """시험지 한 장의 (연도, 학기) — 회차표 → 파일 이름 → 글줄 → AI 순으로.

    찾으면 idx 에 적는다(저장은 부르는 쪽이). 못 찾은 것은 적지 않는다 —
    AI 가 잠깐 바빠서 못 읽은 것을 '모른다' 로 굳히면 다시 묻지 않게 된다.
    """
    import exam_figure as ef

    p = Path(path)
    work = Path(work) if work is not None else p.parent
    if idx is not None:
        got = known_key(idx, work, p)
        if got:
            return got
    m = _MANUAL_RE.search(p.name) if p.parent.name == MANUAL_DIR else None
    if m:
        got = (int(m.group(1)), int(m.group(2)))
    elif ef.has_text_layer(p):
        got = ef.pdf_key(p)
    elif client is not None:
        if on_event:
            on_event(f"   {p.name} — 글줄이 없어 지면을 보여 주고 묻습니다")
        got = ef.ai_pdf_key(client, p, on_event)
    else:
        got = None
    if got and idx is not None:
        note_key(idx, work, p, got)
    return tuple(got) if got else None


def sheet_pdfs(work, course=None) -> list:
    """시험지 PDF 들 — 이름에 과목명이 든 것(course 가 없으면 전부).

    사람이 한글에서 인쇄해 넣어 둔 PDF(직접받은PDF/과목_2015-2.pdf)도 넣는다.
    """
    d = Path(work)
    key = _norm(course)
    out = []
    for folder in (d, d / MANUAL_DIR):
        if not folder.exists():
            continue
        for p in sorted(folder.glob("*.pdf")):
            if not key or key in _norm(p.name):
                out.append(p)
    return out


def sheet_files(work, course=None, client=None, on_event=None) -> dict:
    """{(연도, 학기): [시험지 PDF, …]} — client 가 없으면 회차표·글줄로만 읽는다."""
    idx = load_index(work)
    before = json.dumps(idx, sort_keys=True)
    out: dict = {}
    for p in sheet_pdfs(work, course):
        key = sheet_key(p, client, idx, work, on_event)
        if key:
            out.setdefault(key, []).append(p)
    if json.dumps(idx, sort_keys=True) != before:
        save_index(work, idx)
    return out


# ---------------------------------------------------------------------------
# 정답표 → 그 과목 자리
# ---------------------------------------------------------------------------
def answer_docs(work) -> list:
    """풀어 둔 정답표 파일들(잘라 낸 쪽과 ZIP 은 빼고)."""
    d = Path(work) / ANSWER_DIR
    if not d.exists():
        return []
    return [p for p in sorted(d.rglob("*"))
            if p.is_file() and p.suffix.lower() in ANSWER_EXTS
            and EXCERPT_DIR not in p.parts]


@lru_cache(maxsize=64)
def _doc_lines(path: str, _stamp) -> tuple:
    """(줄 목록, 줄마다 (쪽, 상자) 또는 None) — 파일이 바뀌면 다시 읽는다.

    HWP 는 쪽을 모른다(본문 글자만 읽는다). PDF 는 줄마다 쪽과 상자를 함께
    적어 두어, 잘라 낼 쪽과 칠할 줄을 정확히 집는다.
    """
    p = Path(path)
    if p.suffix.lower() != ".pdf":
        return tuple(eb.hwp_text(p)), None
    try:
        import fitz
    except ImportError:
        return (), None
    lines, where = [], []
    try:
        doc = fitz.open(p)
    except Exception:  # noqa: BLE001 - 손상 파일
        return (), None
    try:
        for i, page in enumerate(doc):
            for block in page.get_text("dict").get("blocks") or []:
                for line in block.get("lines") or []:
                    text = "".join(s.get("text") or ""
                                   for s in line.get("spans") or []).strip()
                    if text:
                        lines.append(text)
                        where.append((i, tuple(line.get("bbox") or ())))
    finally:
        doc.close()
    return tuple(lines), tuple(where)


def doc_lines(path) -> tuple:
    p = Path(path)
    try:
        st = p.stat()
    except OSError:
        return (), None
    return _doc_lines(str(p), (st.st_mtime_ns, st.st_size))


def answer_spots(work, course) -> dict:
    """{(연도, 학기): {"key","file","line","pages","count","many"}}.

    line 은 과목명 줄, pages 는 그 줄과 정답 줄이 걸친 쪽(PDF 만), many 는
    그 파일에 회차가 여럿 들었는지. 같은 회차가 두 파일에 있으면(1·2학년과
    3·4학년으로 나뉜 2018-1) **과목 줄이 실제로 있는 파일**을 고른다.
    """
    out: dict = {}
    for f in answer_docs(work):
        lines, where = doc_lines(f)
        if not lines:
            continue
        fb = eb.parse_exam_title(f.name) or eb.parse_exam_title(f.parent.name)
        secs = split_sections(lines, fb)
        for sec in secs:
            # 정답을 못 읽어도(한 칸에 한 글자씩 적힌 2020 PDF) 과목 줄이
            # 있으면 가리킨다 — 여기서는 열어 보여 주기만 한다.
            got = eb.answer_span(lines, course, 0, sec["start"], sec["end"])
            if not got or sec["key"] in out:
                continue
            i, last, ans = got
            out[sec["key"]] = {
                "key": sec["key"], "file": f, "line": i, "count": len(ans),
                "pages": (sorted({w[0] for w in where[i:last + 1]})
                          if where else []),
                "mark": list(where[i]) if where else None,
                "many": len(secs) > 1}
    return out


def course_terms(work, course) -> list:
    """화면에 늘어놓을 회차 — [{"key","label","sheets","answer"}], 오래된 것부터.

    AI 는 부르지 않는다(회차표에 적힌 것과 글줄로 읽히는 것만).
    """
    sheets = sheet_files(work, course)
    answers = answer_spots(work, course)
    keys = sorted(set(sheets) | set(answers))
    return [{"key": k, "label": term_label(k), "sheets": sheets.get(k) or [],
             "answer": answers.get(k)} for k in keys]


def excerpt_path(spot, course) -> Path:
    """잘라 낸 쪽을 둘 자리 — 정답표/_발췌/컴퓨터구조_2015-2_정답.pdf."""
    f = Path(spot["file"])
    root = next((p for p in f.parents if p.name == ANSWER_DIR), f.parent)
    return root / EXCERPT_DIR / \
        f"{_norm(course)}_{term_label(spot['key'])}_정답.pdf"


def answer_target(spot, course) -> Path:
    """실제로 열 파일 — PDF 면 그 과목 줄이 있는 쪽만 잘라 낸 사본.

    한 학기 정답표는 전 학과 과목이 수십 쪽에 걸쳐 있고, 여러 해가 든 파일은
    더 길다. 통째로 열면 그 줄을 찾아 헤매야 한다. HWP 는 자를 수 없어 원본을
    그대로 연다.
    """
    f = Path(spot["file"])
    pages = spot.get("pages") or []
    if f.suffix.lower() != ".pdf" or not pages:
        return f
    out = excerpt_path(spot, course)
    if out.exists() and out.stat().st_mtime >= f.stat().st_mtime:
        return out
    import fitz
    out.parent.mkdir(parents=True, exist_ok=True)
    src = fitz.open(f)
    try:
        doc = fitz.open()
        for n in pages:
            doc.insert_pdf(src, from_page=n, to_page=n)
        # 과목 줄 **그 자리만** 칠한다. 쪽 안에서 과목명을 검색해 칠하면 같은
        # 쪽에 걸친 다른 회차·다른 학과의 같은 과목까지 칠해진다.
        mark = spot.get("mark")
        if mark and len(mark) == 2 and len(mark[1]) == 4 and \
                mark[0] in pages:
            page = doc[pages.index(mark[0])]
            # 표의 한 줄이다 — 과목명 칸만 칠하면 정답 칸으로 눈을 옮기다
            # 줄을 놓친다. 그 높이로 쪽 너비 전체를 칠한다.
            _x0, y0, _x1, y1 = mark[1]
            box = fitz.Rect(page.rect.x0 + ROW_MARGIN, y0 - 1,
                            page.rect.x1 - ROW_MARGIN, y1 + 1)
            annot = page.add_highlight_annot(box)
            annot.set_colors(stroke=HIGHLIGHT)
            annot.update()
        tmp = out.with_suffix(".tmp.pdf")
        doc.save(tmp)
        doc.close()
        os.replace(tmp, out)
    finally:
        src.close()
    return out
