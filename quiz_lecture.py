"""[quiz_lecture] 이 문항은 몇 강의 내용인가 — 한 번 가려 은행에 남긴다.

기출은 회차(2019-1) 로만 묶여 있어서 **'3강을 배웠으니 3강 문제만 풀어보자'**
가 안 된다. 강의를 듣고 바로 그 범위를 확인하는 것이 복습에서 가장 효과가 큰데,
지금은 25문항을 훑으며 눈으로 골라내야 한다.

그래서 문항마다 차시를 가려 `lecture` 에 적어 둔다. 출처는 셋이다.

  1. 강의 퀴즈(돌발퀴즈·형성평가)는 **자기 은행의 차시가 곧 강**이다 —
     물어볼 것도 없다(stamp_origins 가 화면에서 붙인다).
  2. 기출은 강의 목차를 놓고 **한 번만** 가려서 은행 JSON 에 써 둔다
     (같은 문항을 열 때마다 API 를 부르면 느리고 돈이 든다).
  3. 기출변형은 원본 기출의 강을 그대로 **물려받는다** — 개념이 같으므로
     다시 물어볼 이유가 없다(API 호출 0회).

순수 로직(단위테스트 대상):
  - lecture_no(q) / has_lecture(q) / lecture_label(n) : 읽기와 표기
  - catalog(banks, 과목)        : 강의 목차 [(차시, 제목), …]
  - topic_hints(banks, 과목)    : 강마다 대표 문항 — 이어지는 단원을 가른다
  - question_brief(q)           : 분류에 쓸 문항 요약
  - classify_prompt(…)          : 여러 문항을 한 번에 묻는 지시문
  - parse_lectures(raw, …)      : 응답 → {문항번호: 강}
  - inherit_map(변형, {기출:강}) : 원본에서 물려받을 것
  - lecture_numbers(banks, 과목) : 화면 드롭다운에 올릴 강 목록
  - gather(banks, 과목, 강)      : 여러 은행에서 그 강만 모은 가상 은행

IO:
  - make_lectures(client, …)          : 묶음으로 분류(기본 20문항씩)
  - write_lectures(path, mapping)     : 은행 파일 한 장에 써넣기
  - store_lectures(quiz_dir, bank, …) : 과목·회차로 파일을 찾아 써넣기

⚠️ 분류는 **추정**이다. 정답·해설과 달리 틀려도 학습을 망치지는 않지만,
   목차에 없는 번호는 받지 않는다(15강짜리 과목에 '17강' 이 붙으면 그 문항은
   어느 모아보기에도 안 나온다).
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import quiz_progress as qp

LECTURE_FIELD = "lecture"
CHUNK = 20              # 한 번에 물어보는 문항 수
CODE_LINES = 14         # 지시문에 담을 코드 줄 수(앞부분만으로 충분하다)


# ---------------------------------------------------------------------------
# 읽기와 표기
# ---------------------------------------------------------------------------
def lecture_no(q) -> int:
    """이 문항이 몇 강인가. 아직 안 가렸으면 0."""
    try:
        n = int((q or {}).get(LECTURE_FIELD) or 0)
    except (TypeError, ValueError):
        return 0
    return n if n > 0 else 0


def has_lecture(q) -> bool:
    return lecture_no(q) > 0


def lecture_label(n) -> str:
    """3 → '3강'. 안 가린 것은 빈 문자열(화면에 아무것도 붙이지 않는다)."""
    try:
        n = int(n or 0)
    except (TypeError, ValueError):
        return ""
    return f"{n}강" if n > 0 else ""


def untagged(questions) -> list:
    """아직 강을 안 가린 문항만."""
    return [q for q in (questions or []) if not has_lecture(q)]


def lecture_index(banks) -> dict:
    """{문항번호: 강} — 이미 가려 둔 것을 모은다(변형이 물려받을 때 쓴다)."""
    out = {}
    for b in banks or []:
        for q in b.get("questions") or []:
            if has_lecture(q):
                out[str(q.get("qid"))] = lecture_no(q)
    return out


# ---------------------------------------------------------------------------
# 강의 목차
# ---------------------------------------------------------------------------
def _seq_of(bank) -> int:
    try:
        return int((bank or {}).get("seq") or 0)
    except (TypeError, ValueError):
        return 0


def is_lecture_bank(bank) -> bool:
    """강의 퀴즈 은행인가(기출·변형·모아보기가 아닌 것)."""
    b = bank or {}
    return not b.get("exam") and not b.get("lecture_pick")


def catalog(banks, course=None) -> list:
    """강의 목차 [(차시, 제목), …] — 강의 퀴즈 은행에서 끌어온다.

    기출 은행의 seq 는 정렬용으로 쓰는 큰 수(20191)라 목차가 될 수 없다.
    """
    out = {}
    for b in banks or []:
        if not is_lecture_bank(b):
            continue
        if course and str(b.get("course") or "") != str(course):
            continue
        seq = _seq_of(b)
        if seq > 0 and seq not in out:
            out[seq] = str(b.get("name") or "")
    return [(n, out[n]) for n in sorted(out)]


def lecture_name(lectures, n) -> str:
    """목차에서 그 강의 제목을 찾는다(없으면 빈 문자열)."""
    for seq, name in (lectures or []):
        if int(seq) == int(n or 0):
            return name
    return ""


HINT_PER = 3            # 한 강에 붙일 대표 문항 수
HINT_WIDTH = 46         # 대표 문항을 이만큼만 잘라 쓴다


def topic_hints(banks, course=None, per: int = HINT_PER,
                width: int = HINT_WIDTH) -> dict:
    """{차시: '대표 문항; 대표 문항'} — 그 강의 퀴즈가 범위를 알려준다.

    목차 제목만으로는 '함수와 기억 클래스(1)' 과 '(2)' 를 가를 수 없어서 앞
    단원에 문항이 몰린다. 그 강의 형성평가가 **무엇을 묻는지** 보여 주면
    경계가 분명해진다(강의 퀴즈는 이미 강마다 나뉘어 있다).
    """
    out = {}
    for b in banks or []:
        if not is_lecture_bank(b):
            continue
        if course and str(b.get("course") or "") != str(course):
            continue
        seq = _seq_of(b)
        if seq <= 0:
            continue
        # '위 프로그램의 출력은?' 같은 문항은 범위를 알려주지 못한다 — 내용어가
        # 많은(= 긴) 문항부터 고르면 그 강이 무엇을 다루는지 잘 드러난다.
        stems = sorted((" ".join(str(q.get("question") or "").split())
                        for q in b.get("questions") or []),
                       key=len, reverse=True)
        out[seq] = [t[:int(width)] for t in stems[:int(per)] if t]
    return {n: "; ".join(v) for n, v in out.items() if v}


def catalog_text(lectures, hints=None) -> str:
    """지시문에 넣을 목차 — '1강. C 언어의 개요 — 대표 문항; …' 을 줄마다."""
    h = hints or {}
    rows = []
    for n, name in (lectures or []):
        tip = str(h.get(n) or "").strip()
        rows.append(f"{n}강. {name}" + (f" — {tip}" if tip else ""))
    return "\n".join(rows)


# ---------------------------------------------------------------------------
# 분류 지시문
# ---------------------------------------------------------------------------
def question_brief(q, code_lines: int = CODE_LINES) -> str:
    """분류에 쓸 문항 요약 — 지문·문제·코드 앞부분·보기.

    코드는 앞부분만으로도 어느 단원인지 가릴 수 있다(포인터인지 구조체인지는
    첫 줄들에서 드러난다). 전부 실으면 한 번에 묶을 수 있는 문항이 줄어든다.
    """
    q = q or {}
    parts = []
    intro = str(q.get("intro") or "").strip()
    if intro:
        parts.append(intro)
    parts.append(str(q.get("question") or "").strip())
    code = str(q.get("code") or "").strip()
    if code:
        lines = code.splitlines()
        cut = lines[:int(code_lines)]
        if len(lines) > int(code_lines):
            cut.append("…")
        parts.append("[코드]\n" + "\n".join(cut))
    opts = " / ".join(f"{o.get('no')}) {o.get('text')}"
                      for o in (q.get("options") or []))
    if opts:
        parts.append("보기: " + opts)
    return "\n".join(p for p in parts if p)


CLASSIFY_PROMPT = """너는 한국방송통신대학교 '{course}' 과목의 조교다.
아래 문항이 각각 **몇 강에서 배운 내용인지** 가려라.

[강의 목차]
{catalog}

[문항]
{items}

지켜야 할 것:
1. 문항마다 `문항번호=강번호` 를 **한 줄씩** 출력하라. 예: `{sample}=3`
2. 강번호는 위 목차에 있는 번호 중 하나다. 목차에 없는 번호를 쓰지 마라.
3. 한 문항이 여러 강에 걸치면 **그 문항을 풀려면 반드시 알아야 하는** 개념이
   나오는 강 하나만 고르라. 예를 들어 배열을 훑는 반복문이 들어 있어도 묻는
   것이 배열이면 배열 단원이다.
4. 목차에 `(1)` `(2)` 처럼 이어지는 단원이 있으면 **뒤 단원을 빠뜨리지 마라.**
   각 강 뒤에 붙은 대표 문항이 그 강의 범위를 보여 준다. 앞 단원에 몰아넣지
   말고 대표 문항과 견주어 가리라.
5. 설명·머리말·빈 줄을 쓰지 마라. 출력한 줄 수는 문항 수와 같아야 한다."""


def classify_prompt(questions, lectures, course: str = "C프로그래밍",
                    hints=None) -> str:
    """여러 문항의 강을 한 번에 묻는 지시문."""
    qs = list(questions or [])
    items = "\n\n".join(f"--- {q.get('qid')}\n{question_brief(q)}" for q in qs)
    sample = str(qs[0].get("qid")) if qs else "2019-1-01"
    return CLASSIFY_PROMPT.format(
        course=course,
        catalog=catalog_text(lectures, hints) or "(목차 없음)",
        items=items, sample=sample)


_PAIR_RE = re.compile(r"([0-9A-Za-z][0-9A-Za-z\-_.]*)\s*[=:：]\s*(\d+)")


def parse_lectures(raw, qids, lectures=None) -> dict:
    """응답 → {문항번호: 강}. 모르는 문항번호와 목차 밖 번호는 버린다."""
    want = {str(x) for x in (qids or [])}
    allowed = {int(n) for n, _ in (lectures or [])}
    out = {}
    for line in str(raw or "").splitlines():
        for m in _PAIR_RE.finditer(line):
            qid, no = m.group(1), int(m.group(2))
            if want and qid not in want:
                continue
            if allowed and no not in allowed:
                continue        # 목차에 없는 번호는 안 받는다
            out[qid] = no
    return out


def inherit_map(variants, source_lectures, force: bool = False) -> dict:
    """변형 문항이 원본 기출에서 물려받을 강 — {문항번호: 강}.

    변형은 원본과 같은 개념을 묻는다. 따로 가리면 원본과 다른 강이 붙어 같은
    개념이 두 군데로 흩어질 수 있다.

    force 는 '다시 가리기' 다. 이미 붙어 있는 강도 원본 것으로 덮는다(기출을
    다시 가린 뒤에는 변형도 따라가야 어긋나지 않는다).
    """
    src = {str(k): int(v) for k, v in (source_lectures or {}).items()}
    out = {}
    for q in variants or []:
        if has_lecture(q) and not force:
            continue
        n = int(src.get(str(q.get("origin") or "")) or 0)
        if n > 0:
            out[str(q.get("qid"))] = n
    return out


# ---------------------------------------------------------------------------
# 화면에서 모아 보기
# ---------------------------------------------------------------------------
def stamp_origins(banks) -> list:
    """화면에 올린 은행에 **출처 표시**를 붙인다(파일에는 쓰지 않는다).

    - bank_key : 풀이 기록 키. 여러 은행에서 모아 봐도 기록이 제 은행으로 간다.
    - bank_course/seq/name : 어느 은행에서 왔는지(모아보기에서 회차를 보여준다).
    - lecture  : 강의 퀴즈 문항은 그 은행의 차시가 곧 강이다.

    ⚠️ 메모리에 올린 dict 만 건드린다. 은행 JSON 을 고쳐 쓰는 곳(해설 저장 등)
       은 모두 파일을 다시 읽어 쓰므로 이 표시가 파일로 새지 않는다.
    """
    for b in banks or []:
        seq = _seq_of(b)
        lec_bank = is_lecture_bank(b)
        for q in b.get("questions") or []:
            q["bank_key"] = qp.record_key(b, q.get("qid"))
            q["bank_course"] = str(b.get("course") or "")
            q["bank_seq"] = b.get("seq")
            q["bank_name"] = str(b.get("name") or "")
            if lec_bank and seq > 0 and not has_lecture(q):
                q[LECTURE_FIELD] = seq
    return list(banks or [])


def origin_bank(q, fallback=None) -> dict:
    """이 문항이 원래 있던 은행 — 해설을 저장할 자리를 찾을 때 쓴다."""
    q = q or {}
    if q.get("bank_course") is not None and q.get("bank_seq") is not None:
        return {"course": q.get("bank_course"), "seq": q.get("bank_seq")}
    return fallback or {}


def lecture_numbers(banks, course=None) -> list:
    """모아보기에 올릴 강 목록 — 실제로 문항이 있는 강만."""
    found = set()
    for b in banks or []:
        if b.get("lecture_pick"):
            continue
        if course and str(b.get("course") or "") != str(course):
            continue
        for q in b.get("questions") or []:
            n = lecture_no(q)
            if n > 0:
                found.add(n)
    return sorted(found)


def gather(banks, course, no) -> dict:
    """여러 은행에서 그 강의 문항만 모은 **가상 은행**.

    강의 퀴즈 → 기출 → 변형 순으로 담긴다(banks 가 이미 그 순서로 정렬돼 있다).
    문항 dict 는 원본 그대로 쓴다 — 복사하면 방금 만든 해설이 화면을 바꿀 때
    사라진다.
    """
    n = int(no or 0)
    stamp_origins(banks)            # 기록이 제 은행으로 가게(이미 붙었으면 그대로)
    qs = []
    for b in banks or []:
        if b.get("lecture_pick"):
            continue
        if course and str(b.get("course") or "") != str(course):
            continue
        for q in b.get("questions") or []:
            if lecture_no(q) == n:
                qs.append(q)
    return {"course": str(course or ""), "seq": n,
            "name": lecture_name(catalog(banks, course), n),
            "lecture_pick": n, "questions": qs}


# ---------------------------------------------------------------------------
# 생성 (IO)
# ---------------------------------------------------------------------------
def make_lectures(client, questions, lectures, course: str = "C프로그래밍",
                  model: str | None = None, chunk: int = CHUNK,
                  on_event=None, hints=None) -> dict:
    """문항 묶음의 강을 가린다 → {문항번호: 강}.

    한 문항씩 물으면 호출이 125번 든다 — 목차는 그대로 두고 문항만 바꿔 묻는
    것이라 **묶어서** 보내는 편이 빠르고 싸다.
    """
    from google.genai import types

    from summarize import DEFAULT_MODEL, MAX_OUTPUT_TOKENS, _resp_text

    def log(m):
        if on_event:
            on_event(m)

    qs = [q for q in (questions or []) if q.get("qid")]
    out = {}
    size = max(1, int(chunk or CHUNK))
    for i in range(0, len(qs), size):
        part = qs[i:i + size]
        qids = [str(q.get("qid")) for q in part]
        try:
            resp = client.models.generate_content(
                model=model or DEFAULT_MODEL,
                contents=[classify_prompt(part, lectures, course, hints)],
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS,
                    thinking_config=types.ThinkingConfig(thinking_budget=0)))
            got = parse_lectures(_resp_text(resp), qids, lectures)
        except Exception as ex:  # noqa: BLE001 - 한 묶음이 실패해도 나머지는 간다
            log(f"   ! 분류 실패({qids[0]}…): {str(ex)[:80]}")
            continue
        out.update(got)
        log(f"   {qids[0]}… {len(got)}/{len(part)}문항 분류")
    return out


def write_lectures(path, mapping) -> int:
    """은행 파일 한 장에 강을 써넣는다 → 써넣은 문항 수.

    ⚠️ 임시 파일에 쓴 뒤 바꿔치기한다 — 문항이 든 파일이라 도중에 멈춰
    반쪽짜리가 남으면 기출을 통째로 잃는다.
    """
    m = {}
    for k, v in (mapping or {}).items():
        try:
            n = int(v or 0)
        except (TypeError, ValueError):
            continue
        if n > 0:
            m[str(k)] = n
    if not m:
        return 0
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    hit = 0
    for q in data.get("questions") or []:
        n = m.get(str(q.get("qid")))
        if n and lecture_no(q) != n:
            q[LECTURE_FIELD] = n
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


def store_lectures(quiz_dir, bank, mapping) -> int:
    """과목·회차로 은행 파일을 찾아 강을 써넣는다 → 써넣은 문항 수."""
    from quiz_explain import bank_file

    p = bank_file(quiz_dir, bank)
    return write_lectures(p, mapping) if p is not None else 0
