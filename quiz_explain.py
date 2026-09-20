"""[quiz_explain] 문항 해설 — 한 번 만들면 은행에 남겨 다시 쓴다.

기출은 정답표에서 **번호만** 오므로 '왜 그게 답인지' 가 없다. 풀다 틀렸을 때
이유를 모르면 다음에도 같은 자리에서 틀린다.

그래서 [설명 보기] 를 누르면 그 자리에서 해설을 만들고, **만든 해설은 은행
JSON 에 써 둔다.** 다음부터는 만들지 않고 저장된 것을 보여준다 — 같은 문항을
열 때마다 API 를 부르면 느리고 돈이 든다.

순수 로직(단위테스트 대상):
  - has_explanation(q)       : 이미 해설이 있는가
  - explain_prompt(q, 과목)  : 해설 요청 지시문
  - clean_explanation(raw)   : 모델 응답 다듬기(코드펜스·머리말 제거)

IO:
  - make_explanation(client, q, …) : 해설 한 편 생성
  - store_explanation(quiz_dir, bank, qid, text) : 은행 JSON 에 써넣기

⚠️ 해설을 **정답보다 앞세우지 않는다.** 정답 번호는 정답표에서 온 확정값이고,
   해설은 그 정답을 설명하는 글이다. 모델이 다른 답을 주장해도 정답은 바꾸지
   않는다(정답표가 더 믿을 만하다).
"""
from __future__ import annotations

import json
import re
from pathlib import Path


def has_explanation(q) -> bool:
    """이미 해설이 있는가(공백뿐이면 없는 것으로 본다)."""
    return bool(str((q or {}).get("explanation") or "").strip())


EXPLAIN_PROMPT = """너는 한국방송통신대학교 '{course}' 과목의 학습 도우미다.
아래 기출문제의 **정답이 왜 그것인지** 설명하라.

[문제]
{intro}{question}
{code_block}
[보기]
{options}

[정답] {answer_no}번{answer_text}

지켜야 할 것:
1. **정답은 위에 적힌 {answer_no}번이다.** 다른 답을 주장하지 마라. 네 계산과
   다르더라도 {answer_no}번이 왜 정답인지를 설명하라(정답표에서 온 확정값이다).
2. 코드가 있으면 **한 줄씩 따라가며** 값이 어떻게 변하는지 보여라.
   `a*=(b-1)` 이면 'a 는 10 에 2 를 곱해 20 이 된다' 처럼 구체적으로.
3. **왜 다른 보기가 틀렸는지** 짚어라. 헷갈리기 쉬운 것 한두 개면 충분하다.
4. 이제 막 C 를 배우는 사람이 읽는다. 어려운 말은 풀어 쓰되 군더더기는 빼라.
5. 마크다운 제목(#)이나 코드펜스를 쓰지 마라. **줄글 서너 문단**으로 쓴다.
   식이나 변수는 그냥 본문에 적어라.

설명만 출력하라."""


def explain_prompt(q, course: str = "C프로그래밍") -> str:
    """해설 요청 지시문 — 문제와 확정된 정답을 함께 담는다."""
    q = q or {}
    intro = str(q.get("intro") or "").strip()
    code = str(q.get("code") or "").strip()
    opts = "\n".join(f"{o.get('no')}. {o.get('text')}"
                     for o in (q.get("options") or []))
    ans_text = str(q.get("answer_text") or "").strip()
    return EXPLAIN_PROMPT.format(
        course=course,
        intro=f"{intro}\n" if intro else "",
        question=str(q.get("question") or "").strip(),
        code_block=f"\n[코드]\n{code}\n" if code else "",
        options=opts or "(보기 없음)",
        answer_no=int(q.get("answer_no") or 0),
        answer_text=f" — {ans_text}" if ans_text else "")


_LEAD_RE = re.compile(r"^(네[,.]?\s*|알겠습니다[.,]?\s*|해설[:：]\s*)", re.I)


def clean_explanation(raw) -> str:
    """모델 응답 다듬기 — 코드펜스·머리말을 떼고 빈 줄을 정리한다."""
    s = str(raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    # 머리말이 겹쳐 붙기도 한다('네, 해설: …') — 없어질 때까지 벗긴다
    while True:
        stripped = _LEAD_RE.sub("", s).strip()
        if stripped == s:
            break
        s = stripped
    return re.sub(r"\n{3,}", "\n\n", s)


def make_explanation(client, q, course: str = "C프로그래밍",
                     model: str | None = None) -> str:
    """해설 한 편을 만든다. 실패하면 빈 문자열(화면이 멈추지 않게)."""
    from google.genai import types

    from summarize import DEFAULT_MODEL, MAX_OUTPUT_TOKENS, _resp_text

    if not int((q or {}).get("answer_no") or 0):
        return ""            # 정답을 모르는 문항은 설명할 기준이 없다
    try:
        resp = client.models.generate_content(
            model=model or DEFAULT_MODEL,
            contents=[explain_prompt(q, course)],
            config=types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(thinking_budget=0)))
        return clean_explanation(_resp_text(resp))
    except Exception:  # noqa: BLE001 - 해설이 없다고 퀴즈를 막지 않는다
        return ""


def bank_file(quiz_dir, bank) -> Path | None:
    """이 은행이 담긴 JSON 파일 — 같은 과목·seq 를 가진 것을 찾는다."""
    d = Path(quiz_dir)
    if not d.exists():
        return None
    course = str((bank or {}).get("course") or "")
    seq = str((bank or {}).get("seq") or "")
    for p in sorted(d.glob("*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(data.get("course") or "") == course and \
                str(data.get("seq") or "") == seq:
            return p
    return None


def store_explanation(quiz_dir, bank, qid, text) -> bool:
    """만든 해설을 은행 JSON 에 써넣는다. 저장했으면 True.

    ⚠️ 임시 파일에 쓴 뒤 바꿔치기한다 — 문항이 든 파일이라 도중에 멈춰
    반쪽짜리가 남으면 문제를 통째로 잃는다.
    """
    import os

    text = str(text or "").strip()
    if not text:
        return False
    p = bank_file(quiz_dir, bank)
    if p is None:
        return False
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    hit = False
    for q in data.get("questions") or []:
        if str(q.get("qid")) == str(qid):
            q["explanation"] = text
            hit = True
            break
    if not hit:
        return False
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        return False
    return True
