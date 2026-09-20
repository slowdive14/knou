"""[exam_bank] 기출문제를 반복해 풀 수 있는 문제은행으로 만든다.

강의자료실에는 기출문제(분류 '기출문제')와 정답표(분류 '기출문제정답')가 올라와
있다. 이 둘을 합쳐 **앱 퀴즈 화면이 그대로 읽는 형식**으로 저장하면, 풀이 화면을
새로 만들지 않고도 기출을 반복해서 풀 수 있다.

  자료실 ─┬─ 기출 PDF ── 쪽 이미지 ── Gemini 비전 ──┐
          └─ 정답표 HWP ── 텍스트 ── 과목별 정답 ───┴─ 퀴즈 은행 JSON

⚠️ **기출 PDF 는 글자를 뽑을 수 없다.** 한글에서 변환하며 글자가 벡터로 그려져
   `get_text()` 가 1자만 돌려준다(실측: 2019-1 기출 2쪽 → '  \\n\\uf012b\\n').
   대신 렌더링하면 아주 선명하므로 **쪽을 이미지로 그려 비전으로 읽힌다.**

순수 로직(단위테스트 대상):
  - parse_exam_title(title)        : '[2019-1학기] 기말시험 기출문제' → (2019, 1)
  - exam_seq(year, term)           : 정렬·식별용 번호(강의 차시와 겹치지 않게)
  - bank_filename(course, y, t)    : 'C프로그래밍_기출2019-1.json'
  - parse_answer_lines(lines, 과목): 정답표 줄 → [1, 4, 1, …]
  - attach_answers(문항, 정답)     : 문항에 정답을 채우고 어긋난 곳을 알린다

IO(수동 검증):
  - hwp_text(path)                 : HWP 본문 텍스트(olefile + zlib)
  - fetch_exam_posts(page, course) : 자료실의 기출·정답표 글
  - extract_questions(...)         : PDF → 문항 목록(Gemini 비전)
  - build_bank(...)                : 위를 합쳐 은행 JSON 하나

⚠️ 자료를 **읽기만** 한다. 서버에 아무것도 제출하지 않는다.
"""
from __future__ import annotations

import json
import re
import zlib
from pathlib import Path

# 기출 은행의 seq 는 강의 차시(1~15)와 겹치면 안 된다 — 같은 폴더에 섞이므로.
# 연도·학기를 눌러 담아 정렬이 자연스럽게 되도록 한다: 2019-1 → 20191.
EXAM_SEQ_BASE = 10


def parse_exam_title(title) -> tuple[int, int] | None:
    """자료실 글 제목 → (연도, 학기). 못 읽으면 None.

    실제 제목들(실측):
        '[2019-1학기] 기말시험 기출문제'
        '[2017.1학기] 기말시험'
        '[2015학년도 1학기] 기말시험'
        '[2014.1학기 기말시험] C프로그래밍'
        '[2017 동계계절수업시험] C프로그래밍'   ← 학기가 없다(동계=0)
    """
    s = str(title or "")
    m = re.search(r"(20\d{2}|19\d{2})", s)
    if not m:
        return None
    year = int(m.group(1))
    if re.search(r"동계|계절", s):
        return (year, 0)            # 계절수업은 학기 대신 0
    t = re.search(r"([12])\s*학기", s)
    return (year, int(t.group(1))) if t else None


def exam_seq(year: int, term: int) -> int:
    """기출 은행의 정렬·식별 번호. 강의 차시(1~15)와 절대 겹치지 않는다."""
    return int(year) * EXAM_SEQ_BASE + int(term)


def term_label(term: int) -> str:
    """학기 표시 — 0 은 계절수업이다."""
    return "동계" if int(term) == 0 else f"{int(term)}학기"


def bank_filename(course: str, year: int, term: int) -> str:
    """은행 파일명. 강의 퀴즈(`{과목}_{N}강.json`)와 한눈에 구분된다."""
    from download import sanitize
    return f"{sanitize(course)}_기출{int(year)}-{int(term)}.json"


def exam_name(year: int, term: int, kind: str = "기말시험") -> str:
    """은행 표시 이름 — '2019학년도 1학기 기말시험'."""
    return f"{int(year)}학년도 {term_label(term)} {kind}".strip()


# 정답표는 '과목명' 줄 아래에 **5개씩 묶인 숫자 줄**이 이어진다(실측):
#     C프로그래밍
#     14142      ← 1~5번
#     31312      ← 6~10번
#     …
#     1          ← 과목 구분자(정답이 아니다)
#
# ⚠️ 숫자가 아닌 글자가 섞여 있는 줄이 있다(실측: 2018 '2241C', 2016 '1212K',
#    2015 '33CD1'). 원본에 그렇게 적혀 있다 — 복수정답이나 특수기호로 보인다.
#    그 자리는 **0(모름)** 으로 두고 나머지는 살린다. 한 회차를 통째로 버리면
#    멀쩡한 24문항까지 정답 없이 풀게 된다.
_ANSWER_ROW_RE = re.compile(r"^[0-9A-Za-z]{2,6}$")


def _row_answers(row: str) -> list[int]:
    """정답 줄 한 개 → 번호 목록. 숫자가 아닌 자리는 0(모름)."""
    return [int(c) if c.isdigit() and c != "0" else 0 for c in row]


def _looks_like_answers(row: str) -> bool:
    """정답 줄인가 — ASCII 영숫자뿐이고 숫자를 둘 이상 담고 있어야 한다."""
    if not _ANSWER_ROW_RE.match(row):
        return False
    return sum(c.isdigit() for c in row) >= 2


def _norm(text) -> str:
    """과목명 비교용 — 공백을 없앤다('C 프로그래밍' vs 'C프로그래밍')."""
    return re.sub(r"\s+", "", str(text or ""))


def parse_answer_lines(lines, course: str, expect: int = 25) -> list[int]:
    """정답표 줄 목록에서 그 과목의 정답 번호를 뽑는다.

    과목명 줄을 찾아 그 아래 숫자 묶음을 이어 붙인다. 다음 과목명이 나오거나
    expect 개를 채우면 멈춘다. 길이 1인 줄은 과목 구분자라 건너뛴다 —
    정답이 아니다(실측: 각 과목 끝에 '1' 이 따로 붙어 있다).
    """
    want = _norm(course)
    rows = [str(x or "").strip() for x in (lines or [])]
    try:
        start = next(i for i, l in enumerate(rows) if _norm(l) == want)
    except StopIteration:
        return []
    out: list[int] = []
    for l in rows[start + 1:]:
        if not l:
            continue
        if len(l) == 1 and l.isdigit():
            continue                      # 과목 구분자
        if not _looks_like_answers(l):
            break                         # 다음 과목명 등 — 여기서 끝
        out.extend(_row_answers(l))
        if expect and len(out) >= expect:
            break
    return out[:expect] if expect else out


def attach_answers(questions, answers) -> tuple[list, list[str]]:
    """문항에 정답 번호를 채운다. 반환: (문항, 경고 목록).

    개수가 어긋나면 **채우지 않고 알린다** — 한 칸 밀린 정답으로 공부하는 것이
    정답 없이 공부하는 것보다 나쁘다.
    """
    qs = list(questions or [])
    ans = list(answers or [])
    warn: list[str] = []
    if not ans:
        return qs, ["정답표에서 이 과목을 찾지 못했습니다"]
    if len(qs) != len(ans):
        warn.append(f"문항 {len(qs)}개인데 정답은 {len(ans)}개 — 정답을 붙이지 "
                    f"않았습니다(어긋난 채로 풀면 잘못 외웁니다)")
        return qs, warn
    out = []
    unknown = []
    for q, a in zip(qs, ans):
        q = dict(q)
        if not int(a):          # 정답표에 글자가 적혀 있던 자리 — 비워 둔다
            unknown.append(q.get("qid") or "?")
            out.append(q)
            continue
        q["answer_no"] = int(a)
        opts = q.get("options") or []
        pick = next((o.get("text") for o in opts
                     if int(o.get("no") or 0) == int(a)), "")
        if pick:
            q["answer_text"] = pick
        out.append(q)
    if unknown:
        warn.append(f"정답표에 숫자가 아닌 표기가 있어 {len(unknown)}문항은 "
                    f"정답을 비웠습니다: {', '.join(unknown)}")
    return out, warn


def make_bank(course: str, year: int, term: int, questions,
              kind: str = "기말시험") -> dict:
    """앱 퀴즈 화면이 그대로 읽는 은행 dict.

    `exam` 이 있으면 기출이다 — 화면이 '1강' 대신 '기출 2019-1학기'로 보여준다.
    """
    return {
        "course": course,
        "seq": exam_seq(year, term),
        "name": exam_name(year, term, kind),
        "exam": {"year": int(year), "term": int(term), "kind": kind},
        "questions": list(questions or []),
    }


# ---------------------------------------------------------------------------
# HWP 본문 텍스트 (정답표)
# ---------------------------------------------------------------------------
_HWPTAG_PARA_TEXT = 67      # 한글 문서 레코드에서 문단 글자를 담는 태그

# HWP 문단 글자에는 제어 문자가 섞여 있고, 그중 상당수는 **8글자(WCHAR) 자리를
# 차지한다**(표·그림·필드 등). 그 뒷자리를 건너뛰지 않으면 확장 바이트가 엉뚱한
# 글자로 읽힌다 — 실측 사고: 정답표가 '2241C'·'1212K'·'33CD1' 로 나와 정답
# 개수가 어긋났다. 아래 코드값만 한 글자이고, 나머지 제어 문자는 여덟 글자다.
_CTRL_ONE = frozenset({0, 10, 13, 24, 25, 26, 27, 28, 29, 30, 31})
_CTRL_MAX = 31


def _para_text(buf: bytes) -> list[str]:
    """문단 글자 바이트 → 조각 목록. 제어 문자에서 끊고, 그 자리는 건너뛴다.

    표는 셀마다 문단이 나뉘므로, 제어 문자에서 끊어야 옆 칸 글자가 붙지 않는다.
    """
    out: list[str] = []
    cur: list[str] = []
    i, n = 0, len(buf) - 1
    while i < n:
        code = buf[i] | (buf[i + 1] << 8)
        if code > _CTRL_MAX:
            cur.append(chr(code))
            i += 2
            continue
        if cur:                       # 제어 문자를 만나면 한 조각이 끝난다
            out.append("".join(cur))
            cur = []
        i += 2 if code in _CTRL_ONE else 16     # 8 WCHAR = 16바이트
    if cur:
        out.append("".join(cur))
    return [s.strip() for s in out if s.strip()]


def hwp_text(path) -> list[str]:
    """HWP(5.0) 본문에서 문단 글자만 뽑아 줄 목록으로. 못 읽으면 빈 목록.

    정답표는 표 한 장이라 이 정도로 충분하다(서식·표 구조는 필요 없다).
    """
    try:
        import olefile
    except ImportError:
        return []
    p = Path(path)
    if not p.exists():
        return []
    try:
        ole = olefile.OleFileIO(str(p))
    except Exception:  # noqa: BLE001 - 손상 파일
        return []
    names = sorted("/".join(x) for x in ole.listdir())
    out: list[str] = []
    for s in [n for n in names if n.startswith("BodyText")]:
        try:
            data = zlib.decompress(ole.openstream(s).read(), -15)
        except Exception:  # noqa: BLE001 - 비압축 저장본
            try:
                data = ole.openstream(s).read()
            except Exception:  # noqa: BLE001
                continue
        i = 0
        while i < len(data) - 4:
            head = int.from_bytes(data[i:i + 4], "little")
            i += 4
            tag, size = head & 0x3FF, (head >> 20) & 0xFFF
            if size == 0xFFF:             # 확장 길이
                size = int.from_bytes(data[i:i + 4], "little")
                i += 4
            if tag == _HWPTAG_PARA_TEXT:
                out.extend(_para_text(data[i:i + size]))
            i += size
    return out


def answers_from_hwp(path, course: str, expect: int = 25) -> list[int]:
    """정답표 HWP → 그 과목의 정답 번호."""
    return parse_answer_lines(hwp_text(path), course, expect)


# ---------------------------------------------------------------------------
# 문항 추출 (Gemini 비전)
# ---------------------------------------------------------------------------
QUESTION_PROMPT = """이 이미지는 한국방송통신대학교 '{course}' 기말시험 문제지의 한
쪽이다. 여기 **보이는 문항만** 빠짐없이 읽어 JSON 배열로 옮겨라.

각 문항은 다음 모양이다:
{{
  "no": 7,                       // 문제 번호(숫자)
  "question": "다음과 같은 프로그램의 실행결과로서 올바른 것은?",
  "code": "#include <stdio.h>\\nvoid main() {{ … }}",   // 코드 상자가 있으면 그대로, 없으면 ""
  "options": [
    {{"no": 1, "text": "a = 20  b = 21"}},
    {{"no": 2, "text": "a = 2  b = 9"}},
    {{"no": 3, "text": "a = 20  b = 9"}},
    {{"no": 4, "text": "a = 29 b = 11"}}
  ],
  "points": 2,                   // 배점(괄호 안 'N점'), 없으면 0
  "intro": ""                    // 여러 문항이 함께 쓰는 지문이 있으면 그 지문
}}

지켜야 할 것:
1. **글자를 그대로 옮겨라.** 고쳐 쓰거나 요약하지 마라. 코드의 들여쓰기와 줄바꿈,
   `printf("%d", a);` 같은 문장은 한 글자도 바꾸지 마라.
2. 보기는 ①②③④ 순서대로 no 1~4 로 적는다.
3. `※ (3~4) 다음과 같은 프로그램이…` 처럼 **여러 문항이 지문을 공유**하면, 그
   지문과 코드를 해당 문항 모두의 intro/code 에 각각 넣어라.
4. 쪽 머리말·꼬리말·학과/학번 칸·OMR 안내문은 문항이 아니다. 넣지 마라.
5. **정답은 적지 마라.** 정답은 따로 받는다. 추측한 정답이 섞이면 안 된다.
6. 잘려서 보기가 다 안 보이는 문항은 넣지 마라(다음 쪽에서 이어진다).

JSON 배열만 출력하라. 설명·코드펜스 없이."""


def _clean_json(raw) -> list:
    """모델 응답에서 JSON 배열을 건져낸다(코드펜스·잡말 제거)."""
    s = str(raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    if not s.startswith("["):
        i, j = s.find("["), s.rfind("]")
        if i >= 0 and j > i:
            s = s[i:j + 1]
    try:
        data = json.loads(s)
    except (ValueError, TypeError):
        return []
    return data if isinstance(data, list) else []


def valid_question(q) -> bool:
    """풀 수 있는 문항인가 — 번호·질문·보기 4개가 갖춰졌는지."""
    if not isinstance(q, dict):
        return False
    try:
        int(q.get("no"))
    except (TypeError, ValueError):
        return False
    if not str(q.get("question") or "").strip():
        return False
    opts = q.get("options") or []
    return len(opts) >= 2 and all(str(o.get("text") or "").strip() for o in opts)


def extract_questions(client, pdf_path, course: str, year: int, term: int,
                      model: str | None = None, zoom: float = 2.4,
                      on_event=lambda m: None) -> list:
    """기출 PDF → 문항 목록. 쪽을 이미지로 그려 Gemini 비전에 읽힌다.

    ⚠️ 쪽마다 따로 물어본다. 한 번에 다 넣으면 뒤쪽 문항이 뭉개진다.
    ⚠️ 정답은 여기서 받지 않는다 — 추측한 정답이 섞이면 잘못 외우게 된다.
    """
    from google.genai import types
    from pdf_render import page_count, render_page
    from summarize import DEFAULT_MODEL, MAX_OUTPUT_TOKENS, _resp_text

    model = model or DEFAULT_MODEL
    total = page_count(pdf_path)
    if total <= 0:
        on_event(f"PDF 를 열 수 없습니다: {Path(pdf_path).name}")
        return []

    got: list = []
    for i in range(total):
        img = render_page(pdf_path, i, zoom, fmt="png")
        if not img:
            on_event(f"  {i + 1}쪽: 렌더 실패 — 건너뜁니다")
            continue
        parts = [types.Part.from_bytes(data=img, mime_type="image/png"),
                 QUESTION_PROMPT.format(course=course)]
        try:
            resp = client.models.generate_content(
                model=model, contents=parts,
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)))
            page_items = _clean_json(_resp_text(resp))
        except Exception as e:  # noqa: BLE001 - 한 쪽 실패가 전체를 막지 않게
            on_event(f"  {i + 1}쪽: 읽기 실패 — {str(e)[:100]}")
            continue
        on_event(f"  {i + 1}/{total}쪽: 문항 {len(page_items)}개")
        got.extend(page_items)
    return normalize_questions(got, year, term)


def normalize_questions(items, year: int, term: int) -> list:
    """모델이 준 문항 → 은행 형식(번호순, 중복 제거, 못 쓸 것 버림)."""
    seen: dict[int, dict] = {}
    for q in items or []:
        if not valid_question(q):
            continue
        no = int(q["no"])
        if no in seen:                    # 쪽 경계에서 겹쳐 온 것
            continue
        opts = [{"no": int(o.get("no") or i + 1),
                 "text": str(o.get("text") or "").strip()}
                for i, o in enumerate(q.get("options") or [])]
        seen[no] = {
            "qid": f"{year}-{term}-{no:02d}",
            "source": "기출",
            "qtype": "객관식",
            "question": str(q.get("question") or "").strip(),
            "code": str(q.get("code") or "").strip(),
            "intro": str(q.get("intro") or "").strip(),
            "points": int(q.get("points") or 0),
            "options": opts,
            "answer_no": 0,               # 정답은 정답표에서 채운다
            "answer_text": "",
            "explanation": "",
        }
    return [seen[k] for k in sorted(seen)]
