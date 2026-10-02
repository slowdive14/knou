"""[exam_verify] 기출 문항이 시험지와 맞는지 확인하고 바로잡는다.

기출은 시험지를 AI 가 **읽어** 만들었다. 실측 — 2015-2 컴퓨터구조는 1·2번에
2014-2 의 문제가 들어가 있었고 3번부터는 한 칸씩 밀려 있었다. 해마다 문제가
비슷해 보이니 모델이 지면을 읽는 대신 기억으로 채운 것이다.

정답표는 실제 시험지와 정확히 맞았다(1~6번 모두). 그래서 엉뚱한 문항에
엉뚱한 정답이 붙어, 맞게 풀어도 오답으로 채점되고 있었다.

판단의 근거는 둘이다:
  - **시험지 지면**이 문항 내용의 근거다
  - **정답표**가 정답의 근거다 — 문항이 맞다면 정답표 번호가 말이 되어야 한다

순수 로직(단위테스트 대상):
  - norm(text) / signature(q) : 비교용으로 다듬기(띄어쓰기·기호 차이를 지운다)
  - similar(a, b)             : 두 문항이 얼마나 같은가(0~1)
  - align(old, new)           : 번호로 짝짓기
  - conflicts(banks)          : 회차를 넘어 똑같은 문항인데 정답이 다른 것
  - judge_prompt / parse_judge: 지면을 보여 주고 어느 쪽이 맞는지
  - solve_prompt / parse_solve: 정답을 모르는 채로 풀게 한다
  - apply_fix(q, new)         : 내용을 바꾸고 낡은 것(해설·대화·강)을 걷는다

IO:
  - reread(client, pdf, course) : {번호: (쪽, 새 문항)}
  - judge(client, pdf, page, …) : {번호: '옛'|'새'|'둘다'|'둘다아님'}
  - solve(client, questions, …) : {번호: 모델이 고른 답}
"""
from __future__ import annotations

import difflib
import json
import re

# 이만큼 같으면 같은 문항으로 본다. 띄어쓰기·첨자·화살표 모양 같은 옮겨 적기
# 차이는 norm 이 지우므로, 여기 걸리는 것은 낱말·숫자가 다른 것이다.
SAME = 0.9

# 원래 지시문에 더하는 것 — 이번 오류가 정확히 이 자리였다.
STRICT_RULES = """
7. **이 지면에 보이는 글자만** 옮겨라. 비슷한 다른 해 시험 문제가 떠올라도 그것으로
   채우지 마라. 해마다 문제가 비슷해 보여도 상자 안 명령어·숫자·보기가 다르다.
8. 문제 번호는 **지면에 적힌 번호**를 그대로 쓴다. 차례대로 세어 붙이지 마라."""

_SYMBOLS = str.maketrans({
    "←": "<-", "→": "->", "×": "*", "⊕": "+", "－": "-", "～": "~", "∼": "~",
    "₀": "0", "₁": "1", "₂": "2", "₃": "3", "₄": "4",
    "⁰": "0", "¹": "1", "²": "2", "³": "3",
    "，": ",", "．": ".", "：": ":", "；": ";", "（": "(", "）": ")",
    "‘": "'", "’": "'", "“": '"', "”": '"',
})


# 보기 번호 표시 — '1.5' 같은 숫자 보기를 깎지 않도록, 숫자 표시는 뒤에
# 빈칸이 있을 때만 떼어 낸다.
_OPT_MARK = re.compile(r"^\s*(?:[①②③④⑤]\s*|\(?[1-5]\)\s+|[1-5]\.\s+)")
_STEM_NO = re.compile(r"^\s*\d{1,2}\s*[.．]\s+")


def tidy(q) -> dict:
    """옮겨 적을 때 붙는 군더더기를 걷어낸 **새 dict**.

    다시 읽은 쪽이 보기 글 앞에 '③' 을, 물음 앞에 '21.' 을 붙여 오는 일이
    잦았다. 내용은 맞아도 화면에 '3  ③ A' 처럼 번호가 두 번 보이고, 견줄 때
    멀쩡한 문항을 '다르다' 고 하게 만든다.
    """
    q = dict(q or {})
    q["question"] = _STEM_NO.sub("", str(q.get("question") or ""), count=1)
    q["options"] = [dict(o, text=_OPT_MARK.sub("", str(o.get("text") or ""),
                                                count=1))
                    for o in (q.get("options") or [])]
    return q


def norm(text) -> str:
    """비교용으로 다듬는다 — 띄어쓰기와 기호 모양 차이를 지운다.

    'AC ← M[A]' 와 'AC←M[A]', 'S₀' 와 'S0' 는 같은 것이다. 이런 차이로
    '다르다' 고 하면 멀쩡한 문항을 건드리게 된다.
    """
    s = str(text or "").translate(_SYMBOLS).lower()
    return re.sub(r"\s+", "", s)


def signature(q) -> str:
    """물음 + 코드 + 보기를 한 덩어리로 — 이것이 같으면 같은 문항이다.

    지문(intro)은 넣지 않는다. 여러 문항이 함께 쓰는 지문은 어느 문항에
    붙여 적었는지가 읽을 때마다 달라서, 넣으면 멀쩡한 문항도 다르다고 나온다.
    """
    q = q or {}
    opts = "|".join(norm(o.get("text")) for o in (q.get("options") or []))
    return f"{norm(q.get('question'))}#{norm(q.get('code'))}#{opts}"


def _ratio(x, y) -> float:
    x, y = norm(x), norm(y)
    if x == y:
        return 1.0
    return difflib.SequenceMatcher(None, x, y).ratio()


def similar(a, b) -> float:
    """두 문항이 얼마나 같은가(0~1) — 물음·상자·보기 가운데 **가장 다른 것**.

    ⚠️ 통째로 견주면 안 된다. 'ADD X' 와 'AND R1, R2, R3' 처럼 상자 안
       명령어만 다른 문항은, 보기 네 줄이 길고 똑같아서 전체로는 95% 같다고
       나온다. 바로 이번 오류를 놓치게 된다. 그래서 칸마다 따로 견주고
       가장 낮은 값을 쓴다 — 보기도 한 줄씩 따로 본다('400, 618' 과
       '400, 300' 은 다른 보기다).
    """
    a, b = tidy(a), tidy(b)
    parts = [_ratio(a.get("question"), b.get("question")),
             _ratio(a.get("code"), b.get("code"))]
    oa = [o.get("text") for o in (a.get("options") or [])]
    ob = [o.get("text") for o in (b.get("options") or [])]
    if len(oa) != len(ob):
        return 0.0
    parts += [_ratio(x, y) for x, y in zip(oa, ob)]
    return min(parts)


PROBLEM_SAME = 0.8      # 같은 문제로 볼 물음·보기의 닮음(옮겨 적기 흔들림 허용)


def same_problem(a, b) -> bool:
    """같은 문제를 바로잡는 것인가 — 다른 문제로 바뀐 것인가.

    C프로그래밍에서는 '코드가 아예 빠져 있던' 문항, 'int main' 이 'void main'
    으로 옮겨진 문항, 보기 하나가 '⑧ ⑩' 처럼 깨져 있던 문항이 많았다.
    물음이 같고 보기도 거의 같으면 **같은 문제**다 — 강 번호와 풀이 기록까지
    버릴 까닭이 없다.

    ⚠️ 물음만 보면 안 된다. 2015-2 의 7~9번은 물음이 글자까지 같은데
       기억장치 값이 달라 보기 넷이 모두 달랐다 — 다른 문제다. 그래서 보기가
       둘 이상 다르면 다른 문제로 본다.
    """
    a, b = tidy(a), tidy(b)
    if _ratio(a.get("question"), b.get("question")) < PROBLEM_SAME:
        return False
    oa = [o.get("text") for o in (a.get("options") or [])]
    ob = [o.get("text") for o in (b.get("options") or [])]
    if len(oa) != len(ob):
        return False
    off = sum(1 for x, y in zip(oa, ob) if _ratio(x, y) < PROBLEM_SAME)
    return off <= 1


def q_no(q):
    """'2015-2-07' → 7."""
    m = re.search(r"(\d{1,3})\s*$", str((q or {}).get("qid") or ""))
    return int(m.group(1)) if m else None


def align(old, new) -> list:
    """번호로 짝짓는다 → [(번호, 옛 문항|None, 새 문항|None)] 번호순."""
    a = {q_no(q): q for q in (old or []) if q_no(q) is not None}
    b = {q_no(q): q for q in (new or []) if q_no(q) is not None}
    return [(n, a.get(n), b.get(n)) for n in sorted(set(a) | set(b))]


def conflicts(banks) -> list:
    """회차를 넘어 **똑같은** 문항인데 정답이 다른 것 — 적어도 하나는 틀렸다.

    물음·코드·보기가 글자까지 같다면 정답도 같아야 한다. 해마다 같은 문제를
    다시 내는 일은 흔하지만, 같은 문제의 정답이 바뀌지는 않는다.
    → [[(은행 이름, qid, 정답), …], …]
    """
    seen: dict[str, list] = {}
    for b in banks or []:
        for q in (b or {}).get("questions") or []:
            seen.setdefault(signature(q), []).append(
                (str(b.get("name") or ""), str(q.get("qid") or ""),
                 q.get("answer_no")))
    return [v for v in seen.values()
            if len(v) > 1 and len({a for _n, _q, a in v}) > 1]


# ---------------------------------------------------------------------------
# 어느 쪽이 맞는가 — 지면을 보여 주고 묻는다
# ---------------------------------------------------------------------------
JUDGE_PROMPT = """이것은 한국방송통신대학교 '{course}' 기말시험 문제지 한 쪽이다.

아래 문항마다 **두 가지로 옮겨 적은 것**(가·나)이 있다. 이 지면과 대조해
**글자 그대로 맞는 쪽**을 골라라. 띄어쓰기나 기호 모양 차이는 따지지 않는다.
하지만 상자 안 명령어·숫자·변수 이름, 물음의 낱말, 보기 내용이 하나라도
다르면 그쪽은 틀린 것이다.

{items}

각 문항마다 이렇게 적는다:
  {{"no": 3, "pick": "가" | "나" | "둘다" | "둘다아님", "why": "한 줄"}}

  · 둘다     — 두 쪽 모두 지면과 맞다(옮겨 적은 모양만 다르다)
  · 둘다아님 — 두 쪽 모두 지면과 다르다. 이때는 **지면 그대로** 고쳐 적은
               것을 덧붙여라:
               "fixed": {{"question": "…", "code": "상자 안 글(없으면 빈칸)",
                          "options": ["①의 글", "②의 글", "③의 글", "④의 글"]}}
  · 그 번호 문항이 이 쪽에 없으면 그 문항은 빼라

JSON 배열만 출력하라."""


def _show(q) -> str:
    """판정용으로 문항 하나를 글로 늘어놓는다."""
    q = q or {}
    lines = [f"물음: {str(q.get('question') or '').strip()}"]
    code = str(q.get("code") or "").strip()
    if code:
        lines.append("상자: " + code.replace("\n", " / "))
    for o in q.get("options") or []:
        lines.append(f"  {o.get('no')}. {str(o.get('text') or '').strip()}")
    return "\n".join(lines)


def judge_prompt(pairs, course: str) -> str:
    """판정 지시문 — pairs 는 [(번호, 옛, 새)]."""
    blocks = []
    for n, old, new in pairs or []:
        blocks.append(f"[{n}번]\n(가)\n{_show(old)}\n(나)\n{_show(new)}")
    return JUDGE_PROMPT.format(course=str(course or "").strip() or "이 과목",
                               items="\n\n".join(blocks))


PICKS = {"가": "old", "나": "new", "둘다": "both", "둘다아님": "neither"}


def _json_list(raw) -> list:
    s = str(raw or "").strip()
    s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
    s = re.sub(r"\n?```$", "", s).strip()
    if not s.startswith("["):
        i, j = s.find("["), s.rfind("]")
        if i >= 0 and j > i:
            s = s[i:j + 1]
    try:
        got = json.loads(s)
    except ValueError:
        return []
    return got if isinstance(got, list) else []


def _fixed(raw):
    """'둘다아님' 에 덧붙인 고쳐 적은 문항 → 은행 모양(못 쓰면 None)."""
    if not isinstance(raw, dict):
        return None
    opts = raw.get("options")
    if not isinstance(opts, list) or len(opts) < 2:
        return None
    texts = [str(o.get("text") if isinstance(o, dict) else o or "").strip()
             for o in opts]
    question = str(raw.get("question") or "").strip()
    if not question or not all(texts):
        return None
    return {"question": question, "code": str(raw.get("code") or "").strip(),
            "options": [{"no": i + 1, "text": t} for i, t in enumerate(texts)]}


def parse_judge(raw) -> dict:
    """판정 응답 → {번호: {"pick", "why", "fixed"}}.

    pick 은 'old'|'new'|'both'|'neither'. fixed 는 '둘다아님' 일 때 지면대로
    고쳐 적은 문항이다(없으면 None).
    """
    out = {}
    for item in _json_list(raw):
        if not isinstance(item, dict):
            continue
        pick = PICKS.get(str(item.get("pick") or "").replace(" ", ""))
        try:
            n = int(item.get("no"))
        except (TypeError, ValueError):
            continue
        if pick:
            out[n] = {"pick": pick, "why": str(item.get("why") or "").strip(),
                      "fixed": _fixed(item.get("fixed"))
                      if pick == "neither" else None}
    return out


# ---------------------------------------------------------------------------
# 정답표와 말이 되는가 — 정답을 모르는 채로 풀게 한다
# ---------------------------------------------------------------------------
SOLVE_PROMPT = """다음은 한국방송통신대학교 '{course}' 객관식 문항들이다.
문항마다 정답 번호를 하나 골라라.

{items}

[{{"no": 3, "answer": 4}}, …] 형식의 JSON 배열만 출력하라."""


def solve_prompt(questions, course: str) -> str:
    """풀이 지시문 — 정답은 넣지 않는다(맞춰 보는 것이 목적이다)."""
    blocks = []
    for q in questions or []:
        intro = str(q.get("intro") or "").strip()
        head = f"[{q_no(q)}번]"
        body = (f"지문: {intro}\n" if intro else "") + _show(q)
        blocks.append(f"{head}\n{body}")
    return SOLVE_PROMPT.format(course=str(course or "").strip() or "이 과목",
                               items="\n\n".join(blocks))


def parse_solve(raw) -> dict:
    """풀이 응답 → {번호: 고른 답}."""
    out = {}
    for item in _json_list(raw):
        if not isinstance(item, dict):
            continue
        try:
            out[int(item.get("no"))] = int(item.get("answer"))
        except (TypeError, ValueError):
            continue
    return out


def fits(q, picked) -> bool | None:
    """모델이 고른 답이 정답표와 맞는가(정답을 모르거나 못 풀었으면 None)."""
    from quizbank import correct_nos

    nos = correct_nos(q)
    if not nos or picked is None:
        return None
    return int(picked) in nos


# ---------------------------------------------------------------------------
# 바로잡기
# ---------------------------------------------------------------------------
# 내용을 바꾸면 **함께 버려야** 하는 것들 — 다른 문항을 두고 만든 것이다.
STALE_KEYS = ("explanation", "chat", "lecture", "suspect")
# 같은 문제(물음·보기가 같고 코드만 바로잡는 것)라도 버려야 하는 것 —
# 해설과 대화는 틀린 코드를 짚어 가며 설명했을 수 있다.
CODE_STALE_KEYS = ("explanation", "chat", "suspect")


def apply_fix(q, new, same: bool = False) -> dict:
    """문항 내용을 시험지 것으로 바꾼 **새 dict** — qid·정답 번호는 지킨다.

    ⚠️ 해설·되묻기 대화·강 번호는 엉뚱한 문항을 두고 만든 것이라 버린다.
       남겨 두면 바뀐 문제 아래에 다른 문제의 해설이 붙는다.
       다만 same(같은 문제 — 코드·지문만 바로잡는다)이면 강 번호는 지킨다.
    ⚠️ 정답 번호는 그대로 둔다 — 정답표에서 번호로 붙인 것이라 처음부터
       맞았다. 보기 글이 바뀌었으니 정답 글(answer_text)만 다시 맞춘다.
    """
    from quizbank import correct_nos

    out = dict(q or {})
    new = tidy(new)
    for k in ("question", "code", "intro"):
        out[k] = str(new.get(k) or "").strip()
    out["options"] = [{"no": int(o.get("no") or i + 1),
                       "text": str(o.get("text") or "").strip()}
                      for i, o in enumerate(new.get("options") or [])]
    if new.get("points"):
        out["points"] = int(new.get("points"))
    for k in (CODE_STALE_KEYS if same else STALE_KEYS):
        out.pop(k, None)
    opts = {o["no"]: o["text"] for o in out["options"]}
    pick = " · ".join(opts[n] for n in correct_nos(out) if opts.get(n))
    out["answer_text"] = pick
    out["explanation"] = ""
    return out


# ---------------------------------------------------------------------------
# 모델 부르기 (IO)
# ---------------------------------------------------------------------------
def reread(client, pdf, course: str, year: int, term: int,
           on_event=None) -> dict:
    """시험지를 다시 읽는다 → {번호: (쪽, 문항)}.

    처음 읽을 때와 같은 지시문에 **지면 밖 기억으로 채우지 말라**는 규칙을
    더한다. 쪽마다 따로 묻는다 — 판정할 때 그 쪽을 다시 보여줘야 한다.
    """
    from google.genai import types

    from exam_bank import QUESTION_PROMPT, _clean_json, normalize_questions
    from pdf_render import page_count, render_page
    from summarize import MAX_OUTPUT_TOKENS, _resp_text, generate

    log = on_event or (lambda _m: None)
    prompt = (QUESTION_PROMPT.format(course=course)
              .replace("\n\nJSON 배열만", STRICT_RULES + "\n\nJSON 배열만", 1))
    out: dict[int, tuple] = {}
    for i in range(page_count(pdf)):
        img = render_page(pdf, i, 2.4, fmt="png")
        if not img:
            continue
        try:
            resp = generate(
                client, [types.Part.from_bytes(data=img, mime_type="image/png"),
                         prompt],
                on_event=log,
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS))
        except Exception as e:  # noqa: BLE001 - 한 쪽 실패가 전체를 막지 않게
            log(f"   {i + 1}쪽을 읽지 못했습니다 — {str(e)[:70]}")
            continue
        for q in normalize_questions(_clean_json(_resp_text(resp)),
                                     year, term):
            out.setdefault(q_no(q), (i, tidy(q)))
    return out


def judge(client, pdf, page_no, pairs, course: str, on_event=None) -> dict:
    """그 쪽을 보여 주고 어느 쪽이 맞는지 묻는다 → {번호: (판정, 까닭)}."""
    from google.genai import types

    from pdf_render import render_page
    from summarize import MAX_OUTPUT_TOKENS, _resp_text, generate

    if not pairs:
        return {}
    img = render_page(pdf, page_no, 2.4, fmt="png")
    if not img:
        return {}
    try:
        resp = generate(
            client, [types.Part.from_bytes(data=img, mime_type="image/png"),
                     judge_prompt(pairs, course)],
            on_event=on_event,
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS))
    except Exception:  # noqa: BLE001 - 판정을 못 하면 손대지 않는다
        return {}
    return parse_judge(_resp_text(resp))


def solve(client, questions, course: str, on_event=None,
          chunk: int = 12) -> dict:
    """정답을 모르는 채로 풀게 한다 → {번호: 고른 답}."""
    from google.genai import types

    from summarize import MAX_OUTPUT_TOKENS, _resp_text, generate

    qs = list(questions or [])
    out = {}
    for i in range(0, len(qs), max(1, int(chunk))):
        part = qs[i:i + chunk]
        try:
            resp = generate(
                client, [solve_prompt(part, course)], on_event=on_event,
                config=types.GenerateContentConfig(
                    max_output_tokens=MAX_OUTPUT_TOKENS))
        except Exception:  # noqa: BLE001 - 못 풀었으면 판단을 미룬다
            continue
        out.update(parse_solve(_resp_text(resp)))
    return out
