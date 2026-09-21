"""[quiz_chat] 문항별 후속 질문 — 해설을 읽고도 막히면 그 자리에서 되묻는다.

해설(quiz_explain)은 한 번에 한 편만 쓰인다. 읽는 사람이 어디서 막히는지는
글을 쓸 때 알 수 없다. '왜 20 이 되는지' 가 걸리는 사람도 있고 '이 보기는 왜
틀렸는지' 가 걸리는 사람도 있다.

그래서 정답 상자 안에서 바로 물을 수 있게 한다. 물음과 답은 **은행 JSON 에
남긴다** — 같은 문항을 다시 열면 지난 대화가 그대로 보인다(다시 물어보느라
같은 답을 또 만들지 않아도 된다).

순수 로직(단위테스트 대상):
  - chat_turns(q)              : 저장된 대화(형식이 깨졌으면 빈 목록)
  - add_turn(turns, 역할, 글)  : 대화 한 마디 덧붙이기
  - trim(turns, 최대)          : 길어지면 앞을 자른다(보내는 양을 묶는다)
  - history_text(turns)        : 지시문에 넣을 지난 대화
  - chat_prompt(q, 과목, turns, 물음)
  - clean_answer(raw)          : 모델 응답 다듬기

IO:
  - ask(client, q, …)          : 답 한 마디 생성
  - store_chat(quiz_dir, bank, qid, turns) : 은행 JSON 에 써넣기

⚠️ 해설과 같은 규칙을 따른다 — **정답 번호는 정답표에서 온 확정값**이다.
   사용자가 다른 답을 주장하거나 모델이 다르게 계산해도 정답은 바꾸지 않는다.
"""
from __future__ import annotations

import re

from quiz_explain import clean_explanation, store_field
from quizbank import correct_nos

CHAT_FIELD = "chat"
ROLE_USER = "user"
ROLE_BOT = "model"

# 대화가 길어지면 지시문이 부풀어 답이 느려지고 돈도 더 든다. 뒤쪽 이만큼만
# 보낸다(앞의 물음은 이미 답을 받아 화면에 남아 있다).
MAX_TURNS = 12
MAX_ASK = 500          # 한 번에 물을 수 있는 글자 수


def chat_turns(q) -> list:
    """저장된 대화 — [{"role": …, "text": …}, …]. 없거나 깨졌으면 빈 목록.

    은행 JSON 은 손으로 고칠 수 있는 파일이라 엉뚱한 값이 들어 있을 수 있다.
    그래도 문항을 못 열게 하지는 않는다.
    """
    got = (q or {}).get(CHAT_FIELD)
    if not isinstance(got, (list, tuple)):
        return []
    out = []
    for t in got:
        if not isinstance(t, dict):
            continue
        text = str(t.get("text") or "").strip()
        if not text:
            continue
        role = ROLE_USER if str(t.get("role")) == ROLE_USER else ROLE_BOT
        out.append({"role": role, "text": text})
    return out


def add_turn(turns, role: str, text) -> list:
    """대화 한 마디를 덧붙인 **새 목록**(빈 글은 그냥 넘긴다)."""
    text = str(text or "").strip()
    base = list(turns or [])
    if not text:
        return base
    role = ROLE_USER if str(role) == ROLE_USER else ROLE_BOT
    return base + [{"role": role, "text": text}]


def trim(turns, limit: int = MAX_TURNS) -> list:
    """뒤쪽 limit 마디만 남긴다 — 모델에 보내는 양을 묶는다."""
    turns = list(turns or [])
    n = int(limit or 0)
    return turns[-n:] if n > 0 and len(turns) > n else turns


def history_text(turns) -> str:
    """지시문에 넣을 지난 대화 — 없으면 빈 문자열."""
    lines = []
    for t in turns or []:
        who = "학생" if t.get("role") == ROLE_USER else "도우미"
        lines.append(f"{who}: {str(t.get('text') or '').strip()}")
    return "\n".join(lines)


CHAT_PROMPT = """너는 한국방송통신대학교 '{course}' 과목의 학습 도우미다.
학생이 아래 기출문제의 해설을 읽고도 막힌 곳을 묻고 있다. 그 물음에 답하라.

[문제]
{intro}{question}
{code_block}
[보기]
{options}

[정답] {answer}

[이미 준 해설]
{explanation}
{history_block}
[학생의 물음]
{ask}

지켜야 할 것:
1. {answer_rule}
2. 학생이 물은 것에 **곧바로** 답하라. 해설 전체를 다시 쓰지 마라.
3. 코드를 묻거든 그 줄만 짚어 값이 어떻게 변하는지 보여라.
   `a*=(b-1)` 이면 'a 는 10 에 2 를 곱해 20 이 된다' 처럼 구체적으로.
4. 이제 막 배우는 사람이 읽는다. 어려운 말은 풀어 쓰고 군더더기는 뺀다.
5. **두세 문단 안**으로 짧게. 인사말도, '답변드리겠습니다' 같은 머리말도,
   물음을 되풀이하는 첫 줄도 쓰지 마라. **첫 문장부터 곧바로 답**한다.
6. 마크다운을 쓰지 마라 — 제목(#)도, 굵게(**)도, 번호·점 목록도, 코드펜스도
   쓰지 않는다. **줄글**로 쓰고 식이나 변수는 그냥 본문에 적어라.
7. 이 과목과 상관없는 물음이면, 짧게 선을 긋고 문제로 돌아오게 하라.

답만 출력하라."""

ANSWER_RULE_KNOWN = (
    "**정답은 위에 적힌 {label}이다.** 학생이 다른 답을 주장하거나 네 계산이 "
    "달라도 정답은 바꾸지 마라(정답표에서 온 확정값이다). 대신 왜 그것이 "
    "정답인지를 다시 짚어라.")
ANSWER_RULE_UNKNOWN = (
    "이 문항은 **정답표가 없다.** 확실한 듯 단정하지 말고, 어떻게 풀면 되는지 "
    "그 과정을 보여라.")


def chat_prompt(q, course: str, turns=None, ask: str = "") -> str:
    """후속 질문 지시문 — 문제·정답·이미 준 해설·지난 대화를 함께 담는다."""
    q = q or {}
    intro = str(q.get("intro") or "").strip()
    code = str(q.get("code") or "").strip()
    opts = "\n".join(f"{o.get('no')}. {o.get('text')}"
                     for o in (q.get("options") or []))
    nos = correct_nos(q)
    label = ", ".join(f"{n}번" for n in nos) if nos else ""
    ans_text = str(q.get("answer_text") or "").strip()
    hist = history_text(trim(turns))
    expl = str(q.get("explanation") or "").strip()
    return CHAT_PROMPT.format(
        course=str(course or "").strip() or "이 과목",
        intro=f"{intro}\n" if intro else "",
        question=str(q.get("question") or "").strip(),
        code_block=f"\n[코드]\n{code}\n" if code else "",
        options=opts or "(보기 없음)",
        answer=(f"{label} — {ans_text}" if label and ans_text else
                label or "(정답표 없음)"),
        explanation=expl or "(아직 해설이 없다)",
        history_block=f"\n[지금까지 나눈 대화]\n{hist}\n" if hist else "",
        ask=str(ask or "").strip(),
        answer_rule=(ANSWER_RULE_KNOWN.format(label=label) if nos
                     else ANSWER_RULE_UNKNOWN))


# '학생분의 질문에 답변드리겠습니다.' 처럼 첫 줄이 통째로 인사말인 경우.
# 지시문으로도 막지만 그래도 붙어 나와서, 첫 줄일 때만 벗긴다.
_HELLO_RE = re.compile(
    r"^[^\n]{0,30}?(답변|답)(을)?\s*(드리겠습니다|드릴게요|하겠습니다|합니다)"
    r"[.!]?[ \t]*\n+")

# 첫 줄이 물음을 그대로 되풀이한 것뿐이면 읽을 것이 없다. 물음보다 이만큼
# 길어지면 답이 섞였다고 보고 건드리지 않는다.
ECHO_SLACK = 40


def clean_answer(raw, ask: str = "") -> str:
    """모델 응답 다듬기 — 해설과 같은 방식에 군더더기 첫 줄을 더 벗긴다."""
    s = _HELLO_RE.sub("", clean_explanation(raw)).strip()
    ask = str(ask or "").strip()
    if ask and "\n" in s:
        head, rest = s.split("\n", 1)
        if ask[:20] in head and len(head) <= len(ask) + ECHO_SLACK:
            s = rest.strip()
    return s


def ask(client, q, course: str = "", turns=None, question: str = "",
        model: str | None = None) -> str:
    """후속 질문에 답 한 마디. 실패하면 빈 문자열(화면이 멈추지 않게)."""
    from google.genai import types

    from summarize import DEFAULT_MODEL, MAX_OUTPUT_TOKENS, _resp_text

    question = str(question or "").strip()[:MAX_ASK]
    if not question:
        return ""
    try:
        resp = client.models.generate_content(
            model=model or DEFAULT_MODEL,
            contents=[chat_prompt(q, course, turns, question)],
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_budget=0)))
        return clean_answer(_resp_text(resp), question)
    except Exception:  # noqa: BLE001 - 답이 없다고 퀴즈를 막지 않는다
        return ""


def store_chat(quiz_dir, bank, qid, turns) -> bool:
    """나눈 대화를 은행 JSON 에 써넣는다. 저장했으면 True.

    ⚠️ 모아보기 중이라면 지금 은행은 가상이다 — 부르는 쪽에서 **문항이 원래
       있던 은행**(quiz_lecture.origin_bank)을 넘겨야 다음에도 남아 있다.
    """
    return store_field(quiz_dir, bank, qid, CHAT_FIELD, chat_turns(
        {CHAT_FIELD: turns}))
