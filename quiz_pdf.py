"""고른 강의 퀴즈를 **인쇄용 PDF**로 — 앱 화면이 좁아 풀 맛이 안 날 때.

문제지(지문·그림·코드·보기)를 먼저 싣고, 원하면 맨 뒤에 정답과 해설을
붙인다. 문제를 풀다가 답이 눈에 들어오지 않게 정답은 새 쪽에서 시작한다.

순수 로직(단위테스트 대상):
  - mark(n)                       : 보기 번호 → ①②③…
  - lectures_label(nos)           : [3, 5] → '3·5강'
  - pdf_name(course, nos)         : 저장할 파일 이름
  - sections(banks, course, nos)  : 강마다 (번호, 제목, 문항들)
  - build_html(course, secs, ...) : 인쇄용 HTML 한 장

IO(수동 검증):
  - write_pdf(html, out_path)     : Playwright(Chromium)로 HTML → PDF
  - make_quiz_pdf(...)            : 위를 묶어 PDF 한 부를 만든다
"""
from __future__ import annotations

import base64
import datetime as dt
import re
from html import escape
from pathlib import Path

import quiz_intro as qi
import quiz_lecture as ql
from download import sanitize
from quizbank import AI_ANSWER_HEAD, answer_text, correct_nos, is_ai_answer

PDF_DIR_NAME = "퀴즈 PDF"   # 퀴즈 폴더 옆에 둔다(퀴즈 폴더는 *.json 만 읽는다)
NAME_MAX_LECTURES = 6        # 파일 이름에 강 번호를 이만큼까지만 늘어놓는다
# 문항 글이 이미 'Q1 ' 로 시작하는 은행이 있다 — 번호를 두 번 달지 않는다
_QNUM_RE = re.compile(r"^\s*Q\s*\d+\s*[.)]?\s*")
_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
         ".gif": "image/gif", ".webp": "image/webp"}


def mark(n) -> str:
    """보기 번호 → 동그라미 숫자(①~⑳). 범위 밖이면 '(n)'."""
    try:
        n = int(n)
    except (TypeError, ValueError):
        return f"({n})"
    return chr(0x2460 + n - 1) if 1 <= n <= 20 else f"({n})"


def lectures_label(nos) -> str:
    """[3, 5] → '3·5강'."""
    nums = sorted({int(n) for n in nos or [] if int(n) > 0})
    return "·".join(str(n) for n in nums) + "강" if nums else ""


def pdf_name(course, nos, answers: bool = True) -> str:
    """'C프로그래밍_3·5강_퀴즈.pdf' — 강이 많으면 '3강 외 7개 강'."""
    nums = sorted({int(n) for n in nos or [] if int(n) > 0})
    if len(nums) > NAME_MAX_LECTURES:
        lab = f"{nums[0]}강 외 {len(nums) - 1}개 강"
    else:
        lab = lectures_label(nums)
    tail = "퀴즈" if answers else "퀴즈(문제만)"
    return sanitize(f"{course}_{lab}_{tail}") + ".pdf"


def stem(q) -> str:
    """문항 글 — 앞에 붙어 온 'Q1 ' 은 뗀다(번호는 PDF 가 단다)."""
    return _QNUM_RE.sub("", str((q or {}).get("question") or ""), count=1)


def answer_line(q) -> str:
    """정답 한 줄 — 보기와 같은 ①② 로. 번호를 모르면 answer_text 그대로."""
    nos = correct_nos(q)
    if not nos:
        return answer_text(q)
    opts = {int(o.get("no") or 0): str(o.get("text") or "")
            for o in (q.get("options") or [])}
    body = " · ".join(f"{mark(n)} {opts.get(n, '')}".strip() for n in nos)
    head = AI_ANSWER_HEAD if is_ai_answer(q) else "정답"
    return head + ("(중복정답) " if len(nos) > 1 else " ") + body


def sections(banks, course, nos) -> list:
    """강마다 (번호, 제목, 문항들) — 문항이 없는 강은 뺀다."""
    out = []
    for n in sorted({int(x) for x in nos or [] if int(x) > 0}):
        got = ql.gather(banks, course, n)
        qs = got.get("questions") or []
        if qs:
            out.append((n, str(got.get("name") or ""), qs))
    return out


def _image_tag(path) -> str:
    """지문 그림을 HTML 안에 그대로 싣는다(about:blank 에서는 파일을 못 읽는다)."""
    try:
        data = Path(path).read_bytes()
    except OSError:
        return ""
    mime = _MIME.get(Path(path).suffix.lower(), "image/png")
    b64 = base64.b64encode(data).decode("ascii")
    return f'<img class="intro-img" src="data:{mime};base64,{b64}">'


def _question_html(num: int, q: dict, quiz_dir=None) -> str:
    parts = [f'<div class="q"><div class="qhead"><b>{num}.</b>']
    src = " · ".join(str(x) for x in (q.get("bank_name"), q.get("source"))
                     if x)
    if src:
        parts.append(f'<span class="src">{escape(src)}</span>')
    parts.append("</div>")
    img = qi.intro_file(q, quiz_dir)
    if img is not None:
        parts.append(_image_tag(img))
    intro = str(q.get("intro") or "").strip()
    if intro:
        parts.append(f'<div class="intro">{escape(intro)}</div>')
    parts.append(f'<div class="stem">{escape(stem(q))}'
                 "</div>")
    code = str(q.get("code") or "").strip()
    if code:
        parts.append(f"<pre>{escape(code)}</pre>")
    opts = q.get("options") or []
    if opts:
        parts.append('<ol class="opts">')
        for o in opts:
            parts.append(f'<li><span class="no">{mark(o.get("no"))}</span>'
                         f'{escape(str(o.get("text") or ""))}</li>')
        parts.append("</ol>")
    parts.append("</div>")
    return "".join(parts)


def _answer_html(num: int, q: dict) -> str:
    expl = str(q.get("explanation") or "").strip()
    body = f'<div class="expl">{escape(expl)}</div>' if expl else ""
    return (f'<div class="a"><b>{num}.</b> {escape(answer_line(q))}'
            f"{body}</div>")


_CSS = """
@page { size: A4; margin: 16mm 15mm 18mm; }
* { box-sizing: border-box; }
body { font-family: "Malgun Gothic", "Noto Sans KR", sans-serif;
       font-size: 10.5pt; line-height: 1.55; color: #111; margin: 0; }
h1 { font-size: 17pt; margin: 0 0 2mm; }
.meta { color: #666; font-size: 9pt; margin-bottom: 6mm; }
h2 { font-size: 13pt; border-bottom: 1.5px solid #222; padding-bottom: 1mm;
     margin: 7mm 0 3mm; break-after: avoid; }
h2 .cnt { font-size: 9pt; color: #666; font-weight: normal; }
.q { break-inside: avoid; margin: 0 0 6mm; }
.qhead { margin-bottom: 1mm; }
.src { color: #888; font-size: 8.5pt; margin-left: 2mm; }
.intro { white-space: pre-wrap; background: #f4f4f4; padding: 2mm 3mm;
         border-radius: 2mm; margin: 1mm 0 2mm; font-size: 9.5pt; }
.intro-img { max-width: 100%; max-height: 120mm; display: block;
             margin: 1mm 0 2mm; border: 1px solid #ddd; }
.stem { white-space: pre-wrap; font-weight: bold; }
pre { font-family: Consolas, "D2Coding", monospace; font-size: 9pt;
      background: #f7f7f7; border: 1px solid #ddd; padding: 2mm 3mm;
      white-space: pre-wrap; margin: 2mm 0; }
.opts { list-style: none; padding: 0; margin: 2mm 0 0 2mm; }
.opts li { margin: 0.6mm 0; padding-left: 6mm; text-indent: -6mm;
           white-space: pre-wrap; }
.opts .no { display: inline-block; width: 6mm; text-indent: 0; }
.answers { break-before: page; }
.a { break-inside: avoid; margin: 0 0 3mm; }
.expl { white-space: pre-wrap; color: #333; font-size: 9pt;
        margin: 1mm 0 0 5mm; }
"""


def build_html(course, secs, quiz_dir=None, answers: bool = True,
               today=None) -> str:
    """인쇄용 HTML 한 장 — 강마다 문제를 싣고, 원하면 뒤에 정답과 해설."""
    nos = [n for n, _name, _qs in secs]
    total = sum(len(qs) for _n, _name, qs in secs)
    day = (today or dt.date.today()).isoformat()
    title = f"{course} 퀴즈 — {lectures_label(nos)}"
    out = ["<!doctype html><html lang='ko'><head><meta charset='utf-8'>",
           f"<title>{escape(title)}</title><style>{_CSS}</style></head><body>",
           f"<h1>{escape(title)}</h1>",
           f'<div class="meta">{total}문항 · {day}</div>']

    def _head(n, name, qs):
        lab = escape(ql.lecture_label(n) + (f" · {name}" if name else ""))
        return f'<h2>{lab} <span class="cnt">{len(qs)}문항</span></h2>'

    for n, name, qs in secs:
        out.append(_head(n, name, qs))
        out += [_question_html(i, q, quiz_dir) for i, q in enumerate(qs, 1)]
    if answers and secs:
        out.append('<div class="answers"><h1>정답과 해설</h1>')
        for n, name, qs in secs:
            out.append(_head(n, name, qs))
            out += [_answer_html(i, q) for i, q in enumerate(qs, 1)]
        out.append("</div>")
    out.append("</body></html>")
    return "".join(out)


_FOOTER = ('<div style="font-size:8px;width:100%;text-align:center;'
           'color:#888"><span class="pageNumber"></span> / '
           '<span class="totalPages"></span></div>')


def write_pdf(html: str, out_path) -> Path:
    """HTML → PDF(Chromium 인쇄). 쪽 번호를 아래에 단다.

    ⚠️ Playwright 의 sync API 는 asyncio 루프 안에서 못 쓴다 — 앱(Flet)에서는
       워커 스레드에서 부른다.
    """
    from playwright.sync_api import sync_playwright

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            page = browser.new_page()
            page.set_content(html, wait_until="load")
            page.pdf(path=str(out), format="A4", print_background=True,
                     prefer_css_page_size=True, display_header_footer=True,
                     header_template="<div></div>", footer_template=_FOOTER)
        finally:
            browser.close()
    return out


def make_quiz_pdf(banks, course, nos, quiz_dir, out_dir=None,
                  answers: bool = True) -> Path:
    """고른 강의 퀴즈 PDF 한 부 → 저장한 경로. 문항이 없으면 ValueError."""
    secs = sections(banks, course, nos)
    if not secs:
        raise ValueError("고른 강에 문항이 없습니다")
    folder = Path(out_dir) if out_dir else Path(quiz_dir).parent / PDF_DIR_NAME
    html = build_html(course, secs, quiz_dir, answers=answers)
    return write_pdf(html, folder / pdf_name(course, [n for n, *_ in secs],
                                             answers))
