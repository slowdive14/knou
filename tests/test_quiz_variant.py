"""quiz_variant 단위테스트 — 기출 변형 문제.

핵심은 **검증**이다. C 기출은 '이 코드의 출력은?' 이 태반인데 AI 는 실행 결과를
자주 틀리므로, 실제로 돌려 나온 출력을 정답으로 삼고 맞는 보기가 없으면 버린다.
실제 컴파일은 컴파일러가 있을 때만 돌린다(수동 검증).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quiz_variant as qv  # noqa: E402


def _q(qid="2019-1-07", code="int main(void){return 0;}",
       question="다음과 같은 프로그램의 실행결과로서 올바른 것은?", **over):
    d = {"qid": qid, "question": question, "code": code, "points": 3,
         "options": [{"no": i, "text": f"보기{i}"} for i in range(1, 5)],
         "answer_no": 2}
    d.update(over)
    return d


# --- 돌려 봐야 하는 문항인가 ------------------------------------------------
def test_output_questions_need_running():
    for w in ("실행결과", "출력결과", "결과로 올바른", "화면에 출력되는"):
        assert qv.needs_run(_q(question=f"다음 프로그램의 {w} 것은?"))


def test_a_concept_question_does_not_need_running():
    assert not qv.needs_run(_q(question="상수에 대한 설명으로 옳지 않은 것은?",
                               code=""))


def test_no_code_means_no_run():
    """묻는 말이 실행결과라도 코드가 없으면 돌릴 것이 없다."""
    assert not qv.needs_run(_q(code="", question="실행결과로 옳은 것은?"))
    assert not qv.needs_run({})


# --- 지시문 -----------------------------------------------------------------
def test_prompt_carries_the_original():
    """개념이 흔들리지 않게 원본을 그대로 담아야 한다."""
    p = qv.variant_prompt(_q(question="연산자 우선순위를 묻는다",
                             code="int a=1;"))
    assert "연산자 우선순위를 묻는다" in p and "int a=1;" in p
    assert "보기1" in p


def test_prompt_works_without_code():
    p = qv.variant_prompt(_q(code=""))
    assert "[코드]" not in p


# --- 응답 읽기 --------------------------------------------------------------
_GOOD = ('{"question":"?","code":"int main(void){return 0;}",'
         '"options":[{"no":1,"text":"가"},{"no":2,"text":"나"}],'
         '"answer_no":2,"explanation":"그래서"}')


def test_parse_reads_a_plain_object():
    d = qv.parse_variant(_GOOD)
    assert d["answer_no"] == 2 and len(d["options"]) == 2


def test_parse_survives_a_code_fence_and_chatter():
    assert qv.parse_variant("```json\n" + _GOOD + "\n```")["answer_no"] == 2
    assert qv.parse_variant("네, 만들었습니다:\n" + _GOOD)["answer_no"] == 2


def test_parse_refuses_what_cannot_be_solved():
    assert qv.parse_variant("") is None
    assert qv.parse_variant("못 만들겠습니다") is None
    assert qv.parse_variant('{"question":"","options":[]}') is None
    assert qv.parse_variant('{"question":"?","options":[{"no":1,"text":"하나"}]}') \
        is None                                   # 보기가 하나뿐


# --- 출력과 보기 맞추기 -----------------------------------------------------
def test_normalize_ignores_spacing():
    """보기는 'a = 20  b = 21' 인데 프로그램은 'a=20 b=21' 을 찍는다."""
    assert qv.normalize_output("a = 20  b = 21") == qv.normalize_output("a=20 b=21")
    assert qv.normalize_output(" 7\n") == qv.normalize_output("7")


def test_match_finds_the_right_option():
    opts = [{"no": 1, "text": "a = 20  b = 21"}, {"no": 2, "text": "a=2 b=9"}]
    assert qv.match_option("a=20 b=21", opts) == 1
    assert qv.match_option("a=2  b=9", opts) == 2


def test_match_gives_up_when_nothing_fits():
    """맞는 보기가 없으면 버려야 한다 — 억지로 고르면 틀린 답을 외운다."""
    opts = [{"no": 1, "text": "10"}, {"no": 2, "text": "20"}]
    assert qv.match_option("30", opts) == 0
    assert qv.match_option("", opts) == 0


def test_match_gives_up_when_two_options_are_the_same():
    """같은 값이 둘이면 어느 것이 정답인지 정할 수 없다."""
    opts = [{"no": 1, "text": "10"}, {"no": 2, "text": "10"}]
    assert qv.match_option("10", opts) == 0


# --- 은행에 넣을 모양 -------------------------------------------------------
def test_build_keeps_a_trail_back_to_the_original():
    v = qv.build_variant(_q(), {"question": "새 문제", "code": "x",
                               "options": [{"no": 1, "text": "가"},
                                           {"no": 2, "text": "나"}],
                               "explanation": "설명"}, 2, True)
    assert v["source"] == "기출변형" and v["origin"] == "2019-1-07"
    assert v["qid"].startswith("2019-1-07-v")
    assert v["answer_no"] == 2 and v["answer_text"] == "나"
    assert v["verified"] is True and v["points"] == 3


def test_build_marks_an_unverified_variant():
    v = qv.build_variant(_q(), {"question": "?", "options":
                                [{"no": 1, "text": "가"}]}, 1, False)
    assert v["verified"] is False


def test_build_numbers_repeat_variants_apart():
    a = qv.build_variant(_q(), {"question": "?", "options": []}, 1, True, 1)
    b = qv.build_variant(_q(), {"question": "?", "options": []}, 1, True, 2)
    assert a["qid"] != b["qid"]


# --- 실행 검증 --------------------------------------------------------------
def test_verify_says_so_without_a_compiler(monkeypatch):
    monkeypatch.setattr(qv, "find_compiler", lambda: None)
    no, verified, why = qv.verify_variant(
        {"code": "int main(void){return 0;}", "answer_no": 1,
         "options": [{"no": 1, "text": "x"}]})
    assert no == 0 and verified is False and "컴파일러" in why


def test_verify_corrects_a_wrong_answer(monkeypatch):
    """모델이 2번이라 해도 실행 결과가 1번이면 1번이 정답이다."""
    monkeypatch.setattr(qv, "run_c",
                        lambda code, comp=None: {"ok": True, "out": "20",
                                                 "err": ""})
    no, verified, why = qv.verify_variant(
        {"code": "…", "answer_no": 2,
         "options": [{"no": 1, "text": "20"}, {"no": 2, "text": "30"}]},
        compiler=("gcc", "gcc"))
    assert no == 1 and verified is True and "바로잡" not in why
    assert "1번" in why                    # 어긋났다는 사실을 알려준다


def test_verify_is_quiet_when_the_model_was_right(monkeypatch):
    monkeypatch.setattr(qv, "run_c",
                        lambda code, comp=None: {"ok": True, "out": "30",
                                                 "err": ""})
    no, verified, why = qv.verify_variant(
        {"code": "…", "answer_no": 2,
         "options": [{"no": 1, "text": "20"}, {"no": 2, "text": "30"}]},
        compiler=("gcc", "gcc"))
    assert (no, verified, why) == (2, True, "")


def test_verify_drops_a_variant_whose_output_matches_nothing(monkeypatch):
    monkeypatch.setattr(qv, "run_c",
                        lambda code, comp=None: {"ok": True, "out": "999",
                                                 "err": ""})
    no, _v, why = qv.verify_variant(
        {"code": "…", "answer_no": 1,
         "options": [{"no": 1, "text": "20"}, {"no": 2, "text": "30"}]},
        compiler=("gcc", "gcc"))
    assert no == 0 and "맞는 보기가 없" in why


def test_verify_drops_a_variant_that_does_not_compile(monkeypatch):
    monkeypatch.setattr(qv, "run_c",
                        lambda code, comp=None: {"ok": False, "out": "",
                                                 "err": "컴파일 오류: …"})
    no, verified, why = qv.verify_variant(
        {"code": "망가진 코드", "answer_no": 1, "options": []},
        compiler=("gcc", "gcc"))
    assert no == 0 and verified is False and "컴파일 오류" in why


def test_run_c_refuses_empty_code():
    assert qv.run_c("", ("gcc", "gcc"))["ok"] is False
    assert "비어" in qv.run_c("   ", ("gcc", "gcc"))["err"]


# --- 실제 컴파일 (컴파일러가 있을 때만) ------------------------------------
@pytest.mark.skipif(qv.find_compiler() is None,
                    reason="C 컴파일러가 없어 건너뜁니다")
def test_run_c_actually_runs():
    r = qv.run_c('#include <stdio.h>\nint main(void){printf("a=20 b=21");'
                 'return 0;}')
    assert r["ok"] and qv.normalize_output(r["out"]) == \
        qv.normalize_output("a = 20  b = 21")


@pytest.mark.skipif(qv.find_compiler() is None,
                    reason="C 컴파일러가 없어 건너뜁니다")
def test_run_c_reports_a_compile_error():
    r = qv.run_c("int main(void){ 이건 C 가 아니다 }")
    assert not r["ok"] and "컴파일" in r["err"]


# --- 코드가 화면에 보이는가 (안 보이면 아예 못 푼다) ------------------------
import flet as ft  # noqa: E402


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _bank_dir(tmp_path, q):
    import json
    d = tmp_path / "퀴즈"
    d.mkdir()
    (d / "b.json").write_text(json.dumps(
        {"course": "C프로그래밍", "seq": 20191, "name": "2019",
         "exam": {"year": 2019, "term": 1}, "questions": [q]},
        ensure_ascii=False), encoding="utf-8")
    return d


_CODE = "#include <stdio.h>\nint main(void){printf(\"7\");return 0;}"
_WITH_CODE = {"qid": "q1", "source": "기출", "question": "실행결과는?",
              "code": _CODE, "intro": "※ (3~4) 다음 프로그램을 보고 답하시오.",
              "options": [{"no": 1, "text": "7"}, {"no": 2, "text": "8"}],
              "answer_no": 1}


def test_the_app_shows_the_code(tmp_path):
    """코드를 봐야 푸는 문항인데 코드가 안 보이면 풀 수가 없다."""
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_bank_dir(tmp_path, _WITH_CODE))
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    assert any("printf" in t for t in texts), "코드가 화면에 없다"


def test_the_app_shows_the_shared_intro(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_bank_dir(tmp_path, _WITH_CODE))
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    assert any("다음 프로그램을 보고" in t for t in texts)


def test_the_app_warns_about_an_unverified_variant(tmp_path):
    from app.views.quiz_view import build_quiz_view
    q = dict(_WITH_CODE, source="기출변형", verified=False)
    v = build_quiz_view(quiz_dir=_bank_dir(tmp_path, q))
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    assert any("실행으로 확인하지 못한" in t for t in texts)


def test_the_app_is_quiet_about_a_verified_variant(tmp_path):
    from app.views.quiz_view import build_quiz_view
    q = dict(_WITH_CODE, source="기출변형", verified=True)
    v = build_quiz_view(quiz_dir=_bank_dir(tmp_path, q))
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    assert not any("확인하지 못한" in t for t in texts)


def test_the_html_page_shows_the_code():
    from quiz_html import render_quiz_html
    html = render_quiz_html([{"course": "C프로그래밍", "seq": 20191,
                              "name": "2019", "questions": [_WITH_CODE]}])
    assert "printf" in html and "q-code" in html
    assert "다음 프로그램을 보고" in html and "q-intro" in html
