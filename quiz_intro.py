"""[quiz_intro] 형성평가 '지문' — 문제를 풀려면 반드시 있어야 하는 그것.

실측 불편: '위 문장의 출력 결과는 무엇인가?' 를 담아 왔는데 그 **위 문장이
없다.** 지금까지 스캐너는 form 안의 문제글과 보기만 읽었다.

실제 화면(ucampus)에서 지문은 문항 form 안 `.exam-print` 에 들어 있고, 두 가지
모습이다.

    <div class="exam-print">
      <div class="exam-number">지문</div>
      <div class="exam-sentence">
        <p>if (a > 3 && --b < 10) printf("true");</p>   ← 글
        <p><img src="/user_uploading?…"></p>            ← 그림(842x498 png)
      </div>
    </div>

글이면 그대로 담고, 그림이면 **내려받아 파일로 남긴다.** 코드를 눈으로 읽어
글자로 옮기면 한 글자만 어긋나도 정답이 달라진다 — 화면에 있던 그림 그대로가
가장 안전하다.

순수 로직(단위테스트 대상):
  - looks_like_code(text)      : 이 지문은 코드인가(코드칸에 담을지 가른다)
  - has_intro(q) / needs_intro(q) : 지문이 있는가 / 있어야 하는데 없는가
  - image_name(과목, 차시, qid) : 지문 그림 파일명
  - apply_intro(q, 글, 그림)    : 문항에 지문을 담는다(원본은 안 건드린다)
  - missing_lectures(banks)     : 지문이 빠진 차시 목록

IO:
  - intro_dir/image_path(quiz_dir) : 지문 그림을 두는 자리
  - save_image(quiz_dir, 이름, 바이트)
  - download_intros(frame, 문항들, …) : 화면에서 지문을 읽어 담는다
  - store_intros(quiz_dir, bank, 표) : 은행 JSON 에 써넣기
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path

INTRO_DIR = "지문"          # 퀴즈 폴더 아래 그림을 두는 곳
INTRO_FIELD = "intro_image"

# '위 문장', '위 지문' 처럼 **위에 있는 무언가**를 가리키는 말. 이런 문항인데
# 지문이 없으면 아예 풀 수가 없다.
_DEICTIC = re.compile(
    r"위 ?(문장|지문|프로그램|코드|그림|표|식|함수|보기)|위에서|위의 |"
    r"다음 프로그램|다음 코드|아래 ?(프로그램|코드|지문)")

# 코드처럼 생겼는가 — 이 글자들이 있으면 고정폭 칸에 담아야 읽힌다.
_CODE_HINT = re.compile(
    r"[;{}]|#include|printf|scanf|int |char |float |double |void |return|"
    r"\bfor\b|\bwhile\b|\bif\b|=|\+\+|--")


_BR = re.compile(r"(?i)<\s*br\s*/?\s*>")


def clean_text(text) -> str:
    """지문 글 다듬기 — 글자로 적힌 <br> 은 줄바꿈으로, 빈 줄은 없앤다."""
    s = _BR.sub("\n", str(text or ""))
    rows = [r.strip() for r in s.replace("\r", "").split("\n")]
    return "\n".join(r for r in rows if r)


def looks_like_code(text) -> bool:
    """이 지문은 코드인가. 코드면 고정폭 칸(code), 아니면 설명칸(intro)."""
    t = str(text or "").strip()
    return bool(t) and bool(_CODE_HINT.search(t))


def has_intro(q) -> bool:
    """이 문항에 지문이 딸려 있는가(글이든 코드든 그림이든)."""
    q = q or {}
    return any(str(q.get(k) or "").strip()
               for k in ("intro", "code", INTRO_FIELD))


def needs_intro(q) -> bool:
    """지문을 가리키는 문항인데 지문이 없다 — 지금은 풀 수 없는 문항."""
    q = q or {}
    return bool(_DEICTIC.search(str(q.get("question") or ""))) and \
        not has_intro(q)


def image_name(course, seq, qid) -> str:
    """지문 그림 파일명 — 과목·차시·문항번호로 겹치지 않게."""
    from download import sanitize

    return f"{sanitize(str(course or ''))}_{int(seq or 0)}강_{qid}.png"


def apply_intro(q, text="", image="", force: bool = False) -> dict:
    """문항에 지문을 담은 **새 dict** 를 돌려준다(원본은 건드리지 않는다).

    글이 코드처럼 생겼으면 code 에, 아니면 intro 에 담는다. 이미 지문이 있는
    자리는 덮지 않는다(손으로 채워 둔 것을 지우지 않게).

    force 는 '다시 읽어 고쳐 담기' 다 — 읽는 방법을 고친 뒤 예전에 잘못 담긴
    지문을 바로잡을 때만 쓴다.
    """
    out = dict(q or {})
    text = clean_text(text)
    image = str(image or "").strip()
    if text:
        key = "code" if looks_like_code(text) else "intro"
        if force or not str(out.get(key) or "").strip():
            out[key] = text
    if image and (force or not str(out.get(INTRO_FIELD) or "").strip()):
        out[INTRO_FIELD] = image
    return out


def missing_lectures(banks) -> list:
    """지문이 빠진 차시 [(과목, 차시, 이름, [문항번호…]), …] — 강의 퀴즈만."""
    out = []
    for b in banks or []:
        if b.get("exam") or b.get("lecture_pick"):
            continue        # 기출은 PDF 에서 지문까지 함께 읽어 온다
        qids = [str(q.get("qid")) for q in (b.get("questions") or [])
                if needs_intro(q)]
        if qids:
            out.append((str(b.get("course") or ""), int(b.get("seq") or 0),
                        str(b.get("name") or ""), qids))
    return out


# ---------------------------------------------------------------------------
# 자리 (IO)
# ---------------------------------------------------------------------------
def intro_dir(quiz_dir) -> Path:
    """지문 그림을 두는 폴더 — 퀴즈 은행 옆."""
    return Path(quiz_dir) / INTRO_DIR


def image_path(quiz_dir, name) -> Path | None:
    """지문 그림의 실제 경로(이름이 없으면 None)."""
    name = str(name or "").strip()
    return (intro_dir(quiz_dir) / name) if name else None


def save_image(quiz_dir, name, data) -> Path | None:
    """지문 그림을 파일로 남긴다(빈 데이터면 아무것도 안 한다)."""
    if not data:
        return None
    p = image_path(quiz_dir, name)
    if p is None:
        return None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(data)
    return p


def intro_file(q, quiz_dir=None):
    """이 문항의 지문 그림 파일(없으면 None).

    화면에 올릴 때 붙여 둔 경로(intro_path)를 먼저 보고, 없으면 퀴즈 폴더에서
    찾는다 — 은행 JSON 에는 파일명만 적혀 있다(폴더를 옮겨도 살아 있게).
    """
    q = q or {}
    got = str(q.get("intro_path") or "")
    if got:
        p = Path(got)
        if p.exists():
            return p
    p = image_path(quiz_dir, q.get(INTRO_FIELD)) if quiz_dir else None
    return p if (p is not None and p.exists()) else None


def stamp_paths(banks, quiz_dir) -> list:
    """지문 그림의 실제 경로를 문항에 붙인다(파일에는 쓰지 않는다)."""
    for b in banks or []:
        for q in b.get("questions") or []:
            p = image_path(quiz_dir, q.get(INTRO_FIELD))
            if p is not None and p.exists():
                q["intro_path"] = str(p)
    return list(banks or [])


def intro_data_uri(q) -> str:
    """문항의 지문 그림 → data URI(없으면 빈 문자열)."""
    p = intro_file(q)
    return data_uri(p) if p is not None else ""


def data_uri(path) -> str:
    """그림 → data URI. 한 장짜리 HTML 에 그림을 실어 보낼 때 쓴다."""
    p = Path(path) if path else None
    if p is None or not p.exists():
        return ""
    try:
        raw = p.read_bytes()
    except OSError:
        return ""
    return "data:image/png;base64," + base64.b64encode(raw).decode("ascii")


# 화면에서 문항마다 지문 글과 지문 그림 주소를 읽는다.
# ⚠️ 입력칸 중에서는 **문항 번호(exqsId)만** 읽는다. 같은 form 에 학번이
#    들어 있는 칸이 섞여 있어 통째로 훑으면 안 된다.
INTRO_SCAN_JS = r"""
() => {
  // 줄바꿈을 살려 읽는다. 코드가 한 줄로 뭉치면 읽을 수가 없다.
  // ⚠️ LMS 에는 줄바꿈을 **글자 그대로** '<br>' 이라 적어 둔 지문도 있다.
  const lines = el => {
    if (!el) return '';
    const html = (el.innerHTML || '')
      .replace(/<img[^>]*>/gi, '')
      .replace(/<br\s*\/?>/gi, '\n')
      .replace(/&lt;br\s*\/?&gt;/gi, '\n')
      .replace(/<\/(p|div|li|tr)>/gi, '\n');
    const tmp = document.createElement('div');
    tmp.innerHTML = html;
    return (tmp.textContent || '')
      .replace(/[ \t\u00a0]+/g, ' ')
      .split('\n').map(s => s.trim()).filter(s => s.length).join('\n');
  };
  const out = [];
  document.querySelectorAll(".exam-content-box form, [id^='quiz_'] form")
    .forEach(f => {
      const idEl = f.querySelector('input[name="exqsId"]');
      const print = f.querySelector('.exam-print');
      if (!idEl || !print) return;
      const sent = print.querySelector('.exam-sentence');
      const img = print.querySelector('img');
      out.push({qid: idEl.value, text: lines(sent),
                src: img ? img.src : ''});
    });
  return JSON.stringify(out);
}
"""


def scan_intros(frame) -> dict:
    """화면에서 {문항번호: {"text","src"}} 를 읽는다. 실패하면 빈 표."""
    try:
        rows = json.loads(frame.evaluate(INTRO_SCAN_JS))
    except Exception:  # noqa: BLE001 - 지문을 못 읽어도 이수를 막지 않는다
        return {}
    return {str(r.get("qid")): {"text": str(r.get("text") or ""),
                               "src": str(r.get("src") or "")}
            for r in (rows or []) if r.get("qid")}


def fetch_image(requester, src) -> bytes:
    """브라우저 쿠키 그대로 지문 그림을 받아 온다(실패하면 빈 바이트).

    화면 촬영이 아니라 주소로 받는다 — 지금 보이지 않는 문항(다른 번호를 누르면
    나오는 문항)의 지문도 받을 수 있어야 한다.
    """
    if not src:
        return b""
    try:
        resp = requester.get(src)
        if getattr(resp, "status", 0) != 200:
            return b""
        return resp.body()
    except Exception:  # noqa: BLE001
        return b""


def download_intros(frame, questions, quiz_dir, course, seq,
                    requester=None, on_event=None) -> int:
    """화면의 지문을 문항에 담고 그림은 파일로 남긴다 → 채운 문항 수.

    questions 는 제자리에서 고쳐진다(캡처 직후 저장되는 목록이라 그 편이 맞다).
    """
    def log(m):
        if on_event:
            on_event(m)

    found = scan_intros(frame)
    if not found:
        return 0
    req = requester if requester is not None else getattr(frame, "request", None)
    n = 0
    for i, q in enumerate(questions or []):
        got = found.get(str(q.get("qid")))
        if not got or has_intro(q):
            continue
        name = ""
        if got.get("src"):
            data = fetch_image(req, got["src"]) if req is not None else b""
            if data:
                name = image_name(course, seq, q.get("qid"))
                save_image(quiz_dir, name, data)
        if not got.get("text") and not name:
            continue
        questions[i] = apply_intro(q, got.get("text"), name)
        n += 1
    if n:
        log(f"지문 {n}개 담음")
    return n


def store_intros(quiz_dir, bank, mapping, force: bool = False) -> int:
    """지문을 은행 JSON 에 써넣는다 → 써넣은 문항 수.

    mapping = {문항번호: {"text": 글, "image": 그림파일명}}

    ⚠️ 임시 파일에 쓴 뒤 바꿔치기한다 — 문항이 든 파일이라 도중에 멈춰
    반쪽짜리가 남으면 그 회차를 통째로 잃는다.
    """
    from quiz_explain import bank_file

    mapping = {str(k): v for k, v in (mapping or {}).items() if v}
    if not mapping:
        return 0
    p = bank_file(quiz_dir, bank)
    if p is None:
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    qs = data.get("questions") or []
    hit = 0
    for i, q in enumerate(qs):
        got = mapping.get(str(q.get("qid")))
        if not got:
            continue
        new = apply_intro(q, got.get("text"), got.get("image"), force)
        if new != q:
            qs[i] = new
            hit += 1
    if not hit:
        return 0
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        return 0
    return hit
