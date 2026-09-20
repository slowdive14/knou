"""[quiz_variant] 기출 변형 문제 — 같은 개념, 다른 숫자·코드.

기출을 여러 번 풀면 **답을 외워 버린다.** 그래서 개념은 그대로 두고 숫자·변수명·
코드만 바꾼 문제를 만든다.

⚠️ **C 기출은 '이 코드의 출력은?' 이 태반인데, AI 는 코드 실행 결과를 자주
   틀린다.** 그래서 생성한 코드를 **실제로 컴파일·실행해** 나온 출력을 정답으로
   삼는다. 보기 중 실제 출력과 맞는 것이 없으면 그 문항은 버린다 — 틀린 정답으로
   외우느니 문제가 하나 없는 편이 낫다.

컴파일러가 없으면 코드 문항은 만들지 않는다(검증할 길이 없다). 개념 문항만
만들고, 화면에는 출처가 '기출변형' 으로 붙는다.

순수 로직(단위테스트 대상):
  - needs_run(q)             : 이 문항은 코드를 돌려 봐야 하는가
  - variant_prompt(q)        : 변형 요청 지시문
  - parse_variant(raw)       : 모델 응답 → 변형 문항
  - normalize_output(s)      : 출력 비교용 정규화(공백·따옴표 차이 무시)
  - match_option(out, opts)  : 실행 출력과 맞는 보기 번호(없으면 0)
  - build_variant(원본, 변형, 정답번호) : 은행에 넣을 문항

IO(수동 검증):
  - find_compiler()          : gcc/clang/cl 찾기(없으면 None)
  - run_c(code)              : 컴파일·실행 → {"ok","out","err"}
  - make_variants(client, …) : 기출 문항들 → 검증된 변형 문항들
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from proc_util import run_hidden

# 실행 결과를 묻는 문항인지 알아보는 말들(실측한 기출 문구에서 뽑았다)
_RUN_WORDS = ("실행결과", "출력결과", "결과로", "출력하면", "화면에 출력")

# 컴파일·실행이 멈추지 않게 하는 상한. 기출 코드는 몇 ms 면 끝난다.
BUILD_TIMEOUT = 20
RUN_TIMEOUT = 5


def needs_run(q) -> bool:
    """이 문항은 코드를 돌려 봐야 정답을 확신할 수 있는가."""
    q = q or {}
    if not str(q.get("code") or "").strip():
        return False
    text = str(q.get("question") or "")
    return any(w in text for w in _RUN_WORDS)


VARIANT_PROMPT = """아래는 한국방송통신대학교 '{course}' 기말시험 기출문제 하나다.
이 문제와 **같은 개념을 묻되 숫자·변수명·코드가 다른** 새 문제를 1개 만들어라.

[원본 문제]
{question}
{code_block}
보기:
{options}

지켜야 할 것:
1. **묻는 개념은 그대로.** 원본이 연산자 우선순위를 물으면 새 문제도 그것을 묻는다.
   다른 주제로 넘어가지 마라.
2. **숫자·변수명·연산자를 바꿔라.** 원본을 그대로 베끼면 쓸모가 없다.
3. 코드가 있으면 **반드시 컴파일되는 완전한 C 코드**로 써라. `#include` 부터
   `main` 의 닫는 괄호까지 빠짐없이. 표준 C 로만 쓰고 한글 주석을 넣지 마라.
4. 보기는 4개, 그중 **정답은 하나**. 나머지 셋은 그럴듯한 오답으로(흔한 실수를
   반영하되 정답과 헷갈리게 같은 형식으로 적어라).
5. 출력 형식 문제라면 보기는 **프로그램이 실제로 출력하는 글자 그대로** 적어라.
   `a=20 b=21` 처럼 공백까지 맞춘다.
6. `explanation` 에 왜 그 답인지 두세 문장으로 적어라.

이 JSON 하나만 출력하라(코드펜스·설명 없이):
{{
  "question": "...",
  "code": "#include <stdio.h>\\nint main(void) {{ ... return 0; }}",
  "options": [{{"no": 1, "text": "..."}}, {{"no": 2, "text": "..."}},
              {{"no": 3, "text": "..."}}, {{"no": 4, "text": "..."}}],
  "answer_no": 2,
  "explanation": "..."
}}"""


def variant_prompt(q, course: str = "C프로그래밍") -> str:
    """변형 요청 지시문 — 원본을 그대로 담아 개념이 흔들리지 않게 한다."""
    q = q or {}
    code = str(q.get("code") or "").strip()
    opts = "\n".join(f"{o.get('no')}. {o.get('text')}"
                     for o in (q.get("options") or []))
    return VARIANT_PROMPT.format(
        course=course,
        question=str(q.get("question") or "").strip(),
        code_block=f"\n[코드]\n{code}\n" if code else "",
        options=opts or "(보기 없음)")


def parse_variant(raw):
    """모델 응답 → 변형 문항 dict. 못 읽으면 None."""
    s = str(raw or "").strip()
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    if not s.startswith("{"):
        i, j = s.find("{"), s.rfind("}")
        if i < 0 or j <= i:
            return None
        s = s[i:j + 1]
    try:
        d = json.loads(s)
    except (ValueError, TypeError):
        return None
    if not isinstance(d, dict):
        return None
    opts = d.get("options") or []
    if not str(d.get("question") or "").strip() or len(opts) < 2:
        return None
    return d


def normalize_output(text) -> str:
    """출력 비교용 — 공백과 따옴표 차이를 지운다.

    보기는 `a = 20  b = 21` 인데 프로그램은 `a=20 b=21` 을 찍는다. 사람 눈에는
    같은 답이므로 그 차이로 버리면 멀쩡한 문항을 잃는다.
    """
    s = str(text or "")
    s = s.replace("“", "\"").replace("”", "\"").replace("’", "'")
    return re.sub(r"\s+", "", s).strip()


def match_option(output, options) -> int:
    """실행 출력과 맞는 보기 번호. 없으면 0.

    같은 값이 여러 보기에 있으면 0 — 어느 것이 정답인지 정할 수 없다.
    """
    want = normalize_output(output)
    if not want:
        return 0
    hits = [int(o.get("no") or 0) for o in (options or [])
            if normalize_output(o.get("text")) == want]
    return hits[0] if len(hits) == 1 else 0


def build_variant(origin, data, answer_no: int, verified: bool,
                  index: int = 1) -> dict:
    """은행에 넣을 변형 문항.

    `origin` 에 원본 문항 번호를 남겨 둔다 — 틀렸을 때 원본을 찾아볼 수 있다.
    `verified` 는 코드를 실제로 돌려 확인했는지다.
    """
    origin = origin or {}
    opts = [{"no": int(o.get("no") or i + 1),
             "text": str(o.get("text") or "").strip()}
            for i, o in enumerate(data.get("options") or [])]
    pick = next((o["text"] for o in opts if o["no"] == int(answer_no)), "")
    return {
        "qid": f"{origin.get('qid', '?')}-v{int(index)}",
        "source": "기출변형",
        "qtype": "객관식",
        "origin": origin.get("qid", ""),
        "verified": bool(verified),
        "question": str(data.get("question") or "").strip(),
        "code": str(data.get("code") or "").strip(),
        "intro": "",
        "points": int(origin.get("points") or 0),
        "options": opts,
        "answer_no": int(answer_no),
        "answer_text": pick,
        "explanation": str(data.get("explanation") or "").strip(),
    }


# ---------------------------------------------------------------------------
# 코드 실행 (IO)
# ---------------------------------------------------------------------------
def find_compiler():
    """쓸 수 있는 C 컴파일러 → (이름, 경로). 없으면 None."""
    for name in ("gcc", "clang", "cc"):
        path = shutil.which(name)
        if path:
            return (name, path)
    return None


def run_c(code: str, compiler=None, timeout: int = RUN_TIMEOUT) -> dict:
    """C 코드를 컴파일·실행 → {"ok","out","err"}.

    컴파일러가 없으면 ok=False 에 이유를 담아 돌려준다(예외를 내지 않는다).
    """
    comp = compiler or find_compiler()
    if comp is None:
        return {"ok": False, "out": "", "err": "C 컴파일러가 없습니다"}
    src = str(code or "").strip()
    if not src:
        return {"ok": False, "out": "", "err": "코드가 비어 있습니다"}

    with tempfile.TemporaryDirectory(prefix="knou_c_") as tmp:
        d = Path(tmp)
        cf, exe = d / "a.c", d / "a.exe"
        cf.write_text(src, encoding="utf-8")
        try:
            b = run_hidden([comp[1], str(cf), "-o", str(exe)],
                           capture_output=True, text=True,
                           timeout=BUILD_TIMEOUT)
        except (subprocess.TimeoutExpired, OSError) as e:
            return {"ok": False, "out": "", "err": f"컴파일 실패: {str(e)[:120]}"}
        if b.returncode != 0 or not exe.exists():
            return {"ok": False, "out": "",
                    "err": f"컴파일 오류: {(b.stderr or '')[:200]}"}
        try:
            r = run_hidden([str(exe)], capture_output=True, text=True,
                           timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "out": "", "err": "실행이 끝나지 않았습니다"}
        except OSError as e:
            return {"ok": False, "out": "", "err": f"실행 실패: {str(e)[:120]}"}
        return {"ok": True, "out": r.stdout or "", "err": r.stderr or ""}


def make_variants(client, questions, course: str = "C프로그래밍",
                  per: int = 1, model: str | None = None,
                  allow_unverified: bool = False,
                  on_event=lambda m: None) -> list:
    """기출 문항들 → **검증을 통과한** 변형 문항들.

    코드를 돌려 봐야 하는 문항인데 컴파일러가 없으면 건너뛴다 — 검증할 길이
    없는 코드 문제를 내면 틀린 답을 외우게 된다. `allow_unverified` 를 켜면
    그런 문항도 담되 `verified=False` 로 표시한다.
    """
    from google.genai import types

    from summarize import DEFAULT_MODEL, MAX_OUTPUT_TOKENS, _resp_text

    model = model or DEFAULT_MODEL
    comp = find_compiler()
    if comp is None:
        on_event("C 컴파일러가 없어 코드 문항은 건너뜁니다 "
                 "(설치하면 실행으로 정답을 확인합니다)")
    else:
        on_event(f"컴파일러: {comp[0]} — 코드를 돌려 정답을 확인합니다")

    out: list = []
    for q in questions or []:
        run_needed = needs_run(q)
        if run_needed and comp is None and not allow_unverified:
            continue
        for i in range(1, max(1, int(per)) + 1):
            try:
                resp = client.models.generate_content(
                    model=model, contents=[variant_prompt(q, course)],
                    config=types.GenerateContentConfig(
                        max_output_tokens=MAX_OUTPUT_TOKENS,
                        thinking_config=types.ThinkingConfig(
                            thinking_budget=0)))
                data = parse_variant(_resp_text(resp))
            except Exception as e:  # noqa: BLE001 - 문항 단위 격리
                on_event(f"  {q.get('qid')}: 생성 실패 — {str(e)[:90]}")
                continue
            if data is None:
                on_event(f"  {q.get('qid')}: 응답을 읽지 못했습니다")
                continue

            if run_needed and comp is not None:
                no, verified, why = verify_variant(data, comp)
                if not no:
                    on_event(f"  {q.get('qid')}: 버림 — {why}")
                    continue
                if why:
                    on_event(f"  {q.get('qid')}: 정답 바로잡음 — {why}")
            else:
                no = int(data.get("answer_no") or 0)
                verified = False
                if not no:
                    on_event(f"  {q.get('qid')}: 정답이 없어 버립니다")
                    continue
            out.append(build_variant(q, data, no, verified, i))
    return out


def verify_variant(data, compiler=None) -> tuple[int, bool, str]:
    """변형 문항의 정답을 확정한다 → (정답번호, 검증했는가, 사유).

    코드를 돌려 나온 출력과 맞는 보기를 정답으로 삼는다. 맞는 보기가 없거나
    여럿이면 **정답번호 0** 을 돌려준다(=버릴 문항).
    """
    data = data or {}
    code = str(data.get("code") or "").strip()
    said = int(data.get("answer_no") or 0)
    if not code:
        return (said, False, "코드가 없어 실행으로 확인하지 못했습니다")
    res = run_c(code, compiler)
    if not res["ok"]:
        return (0, False, res["err"])
    no = match_option(res["out"], data.get("options"))
    if not no:
        return (0, True, f"실행 출력 {res['out'].strip()[:60]!r} 과 맞는 보기가 "
                         f"없습니다")
    return (no, True, "" if no == said else
            f"모델이 {said}번이라 했지만 실행 결과는 {no}번입니다")
