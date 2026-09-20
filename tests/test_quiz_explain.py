"""quiz_explain 단위테스트 — 해설은 한 번만 만들고 은행에 남긴다.

기출은 정답표에서 번호만 오므로 '왜 그게 답인지' 가 없다. [설명 보기] 를
누르면 그 자리에서 만들고, 만든 것은 은행 JSON 에 저장해 다음부터 다시 쓴다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quiz_explain as qe  # noqa: E402


def _q(**over):
    d = {"qid": "2019-1-07", "question": "실행결과로 올바른 것은?",
         "code": "#include <stdio.h>\nint main(void){return 0;}",
         "intro": "※ (7~8) 다음 프로그램을 보고 답하시오.",
         "options": [{"no": 1, "text": "a = 20  b = 21"},
                     {"no": 2, "text": "a = 2  b = 9"}],
         "answer_no": 1, "answer_text": "a = 20  b = 21", "explanation": ""}
    d.update(over)
    return d


def _bank_dir(tmp_path, *questions, course="C프로그래밍", seq=20191):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / "b.json").write_text(json.dumps(
        {"course": course, "seq": seq, "name": "2019",
         "questions": list(questions)}, ensure_ascii=False), encoding="utf-8")
    return d


# --- 이미 있는가 ------------------------------------------------------------
def test_has_explanation_reads_real_content():
    assert qe.has_explanation(_q(explanation="이래서 그렇습니다"))
    assert not qe.has_explanation(_q())
    assert not qe.has_explanation(_q(explanation="   "))   # 공백뿐이면 없는 것
    assert not qe.has_explanation({})


# --- 지시문 -----------------------------------------------------------------
def test_prompt_pins_the_confirmed_answer():
    """정답은 정답표에서 온 확정값이다 — 모델이 뒤집으면 안 된다."""
    p = qe.explain_prompt(_q())
    assert "1번이다" in p and "다른 답을 주장하지 마라" in p


def test_prompt_carries_question_code_and_options():
    p = qe.explain_prompt(_q())
    assert "실행결과로 올바른" in p
    assert "#include" in p
    assert "a = 20  b = 21" in p
    assert "다음 프로그램을 보고" in p            # 공유 지문도 담는다


def test_prompt_works_without_code_or_intro():
    p = qe.explain_prompt(_q(code="", intro=""))
    assert "[코드]" not in p and "실행결과로 올바른" in p


# --- 응답 다듬기 ------------------------------------------------------------
def test_clean_strips_a_code_fence():
    assert qe.clean_explanation("```\n설명입니다\n```") == "설명입니다"


def test_clean_strips_a_lead_in():
    assert qe.clean_explanation("네, 해설: 이렇습니다") == "이렇습니다"
    assert qe.clean_explanation("알겠습니다. 정답은 1번입니다") == "정답은 1번입니다"


def test_clean_squeezes_blank_lines():
    assert qe.clean_explanation("가\n\n\n\n나") == "가\n\n나"


def test_clean_handles_nothing():
    assert qe.clean_explanation("") == "" and qe.clean_explanation(None) == ""


# --- 생성 -------------------------------------------------------------------
class _Resp:
    def __init__(self, text):
        self.text = text


class _Client:
    def __init__(self, text="한 줄씩 따라가면 …"):
        self.text = text
        self.calls = 0

        class _M:
            def generate_content(_s, **kw):
                self.calls += 1
                return _Resp(self.text)
        self.models = _M()


def test_make_explanation_returns_clean_text():
    c = _Client("```\n이래서 1번입니다\n```")
    assert qe.make_explanation(c, _q()) == "이래서 1번입니다"
    assert c.calls == 1


def test_make_explanation_skips_a_question_without_an_answer():
    """정답을 모르는 문항은 설명할 기준이 없다 — API 를 부르지도 않는다."""
    c = _Client()
    assert qe.make_explanation(c, _q(answer_no=0)) == ""
    assert c.calls == 0


def test_make_explanation_survives_an_api_error():
    class _Bad:
        class models:
            @staticmethod
            def generate_content(**kw):
                raise RuntimeError("끊김")
    assert qe.make_explanation(_Bad(), _q()) == ""


# --- 저장 -------------------------------------------------------------------
def test_store_writes_into_the_right_question(tmp_path):
    d = _bank_dir(tmp_path, _q(qid="a"), _q(qid="b"))
    bank = {"course": "C프로그래밍", "seq": 20191}
    assert qe.store_explanation(d, bank, "b", "b 의 해설") is True
    data = json.loads((d / "b.json").read_text(encoding="utf-8"))
    got = {q["qid"]: q["explanation"] for q in data["questions"]}
    assert got == {"a": "", "b": "b 의 해설"}


def test_store_survives_being_called_twice(tmp_path):
    d = _bank_dir(tmp_path, _q(qid="a"))
    bank = {"course": "C프로그래밍", "seq": 20191}
    qe.store_explanation(d, bank, "a", "처음")
    qe.store_explanation(d, bank, "a", "나중")
    data = json.loads((d / "b.json").read_text(encoding="utf-8"))
    assert data["questions"][0]["explanation"] == "나중"
    assert not list(d.glob("*.tmp"))       # 임시 파일이 남지 않는다


def test_store_refuses_empty_text(tmp_path):
    d = _bank_dir(tmp_path, _q(qid="a"))
    assert qe.store_explanation(d, {"course": "C프로그래밍", "seq": 20191},
                                "a", "   ") is False


def test_store_says_no_when_the_question_is_missing(tmp_path):
    d = _bank_dir(tmp_path, _q(qid="a"))
    assert qe.store_explanation(d, {"course": "C프로그래밍", "seq": 20191},
                                "없는문항", "해설") is False


def test_store_says_no_when_the_bank_is_missing(tmp_path):
    d = _bank_dir(tmp_path, _q(qid="a"))
    assert qe.store_explanation(d, {"course": "없는과목", "seq": 1},
                                "a", "해설") is False


def test_bank_file_matches_course_and_seq(tmp_path):
    d = _bank_dir(tmp_path, _q())
    assert qe.bank_file(d, {"course": "C프로그래밍", "seq": 20191}).name == "b.json"
    assert qe.bank_file(d, {"course": "C프로그래밍", "seq": 8}) is None
    assert qe.bank_file(tmp_path / "없음", {"course": "x", "seq": 1}) is None


# --- 화면과 이어 붙였을 때 --------------------------------------------------
import flet as ft  # noqa: E402


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _reveal(view):
    """[정답 보기] 를 눌러 해설 칸을 연다."""
    btn = next(c for c in _walk(view) if isinstance(c, ft.TextButton)
               and c.content == "정답 보기")
    btn.on_click(None)


def test_the_button_appears_when_there_is_no_explanation(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_bank_dir(tmp_path, _q()))
    _reveal(v)
    labels = [c.content for c in _walk(v) if isinstance(c, ft.TextButton)]
    assert any("설명 보기" in str(x) for x in labels)


def test_a_stored_explanation_is_shown_without_a_button(tmp_path):
    """이미 만든 해설은 곧바로 보인다 — 다시 만들지 않는다."""
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_bank_dir(
        tmp_path, _q(explanation="저장된 해설입니다")))
    _reveal(v)
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    labels = [str(c.content) for c in _walk(v) if isinstance(c, ft.TextButton)]
    assert any("저장된 해설입니다" in t for t in texts)
    assert not any("설명 보기" in x for x in labels)


def test_no_button_when_the_answer_is_unknown(tmp_path):
    """정답을 모르는 문항(정답표에 글자가 있던 자리)은 설명할 기준이 없다."""
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_bank_dir(tmp_path, _q(answer_no=0)))
    _reveal(v)
    labels = [str(c.content) for c in _walk(v) if isinstance(c, ft.TextButton)]
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    assert not any("설명 보기" in x for x in labels)
    assert any("정답을 몰라" in t for t in texts)
