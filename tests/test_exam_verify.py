"""exam_verify 단위테스트 — 기출 문항이 시험지와 맞는지 확인한다.

2015-2 컴퓨터구조는 1·2번에 2014-2 의 문제가 들어가 있었고 3번부터 한 칸씩
밀려 있었다. 정답표는 실제 시험지와 맞아서, 엉뚱한 문항에 엉뚱한 정답이
붙어 맞게 풀어도 오답이 되었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import exam_verify as ev  # noqa: E402
import verify_exams as vx  # noqa: E402

OPTS = ["2-주소 컴퓨터 명령어이다.", "데이터 전송을 위한 컴퓨터 명령어이다.",
        "컴퓨터의 내부구조로 볼 때 누산기를 이용하는 컴퓨터 명령어이다.",
        "컴퓨터의 내부구조로 볼 때 다중 레지스터를 이용하는 컴퓨터 명령어이다."]


def _q(no=3, code="AND R1, R2, R3", answer=4, **over):
    d = {"qid": f"2015-2-{no:02d}",
         "question": "다음 컴퓨터 명령어에 관한 설명으로 적절한 것은?",
         "code": code,
         "options": [{"no": i + 1, "text": t} for i, t in enumerate(OPTS)],
         "answer_no": answer, "answer_text": OPTS[answer - 1]}
    d.update(over)
    return d


# --- 비교용으로 다듬기 -------------------------------------------------------
def test_spacing_and_symbol_shapes_do_not_count():
    """'AC ← M[A]' 와 'AC←M[A]' 는 같은 것이다."""
    assert ev.norm("AC ← M[A]") == ev.norm("AC←M[A]")
    assert ev.norm("S₀ 와 S₁") == ev.norm("S0와S1")
    assert ev.norm("AC ← AC × M[X]") == ev.norm("AC<-AC*M[X]")


def test_a_different_instruction_is_a_different_question():
    """상자 안 명령어 하나가 다르면 다른 문제다 — 이번 오류가 바로 이것이었다.

    보기 네 줄이 길고 똑같아서, 통째로 견주면 95% 같다고 나와 놓친다.
    """
    assert ev.similar(_q(code="AND R1, R2, R3"), _q(code="ADD X")) < ev.SAME


def test_one_different_option_makes_a_different_question():
    """'400, 618' 과 '400, 300' 은 다른 보기다."""
    a = _q(options=[{"no": 1, "text": "400, 618"}, {"no": 2, "text": "500"}])
    b = _q(options=[{"no": 1, "text": "400, 300"}, {"no": 2, "text": "500"}])
    assert ev.similar(a, b) < ev.SAME


def test_a_different_stem_makes_a_different_question():
    a = _q(question="다음 중 컴퓨터 명령을 구성하는 대표적인 필드가 아닌 것은?")
    b = _q(question="다음 중 컴퓨터 명령어를 구성하는 연산코드 필드에 대한 "
                    "설명으로 가장 적절한 것은?")
    assert ev.similar(a, b) < ev.SAME


def test_a_missing_option_makes_a_different_question():
    a = _q()
    b = _q(options=a["options"][:3])
    assert ev.similar(a, b) == 0.0


def test_the_same_question_written_a_little_differently_is_the_same():
    a = _q(code="AND  R1, R2, R3")
    b = _q(code="AND R1,R2,R3", question="다음 컴퓨터 명령어에 관한 설명으로 "
                                         "적절한 것은 ?")
    assert ev.similar(a, b) >= ev.SAME


def test_a_shared_intro_is_left_out_of_the_comparison():
    """지문을 어느 문항에 붙여 적었는지는 읽을 때마다 다르다."""
    assert ev.similar(_q(intro="※ (7~9) 아래 그림은 …"), _q(intro="")) >= ev.SAME


def test_the_number_comes_from_the_qid():
    assert ev.q_no({"qid": "2015-2-07"}) == 7
    assert ev.q_no({}) is None


# --- 번호로 짝짓기 ----------------------------------------------------------
def test_old_and_new_are_paired_by_number():
    got = ev.align([_q(1), _q(2)], [_q(2), _q(3)])
    assert [(n, bool(o), bool(w)) for n, o, w in got] == [
        (1, True, False), (2, True, True), (3, False, True)]


# --- 회차를 넘어 같은 문항 ---------------------------------------------------
def test_the_same_question_with_different_answers_is_a_conflict():
    """글자까지 같은 문제의 정답이 해마다 바뀌지는 않는다."""
    a = {"name": "2014-2", "questions": [_q(2, code="ADD X", answer=3)]}
    b = {"name": "2015-2", "questions": [_q(2, code="ADD X", answer=1)]}
    got = ev.conflicts([a, b])
    assert len(got) == 1
    assert {x[0] for x in got[0]} == {"2014-2", "2015-2"}


def test_a_reused_question_with_the_same_answer_is_fine():
    """해마다 같은 문제를 다시 내는 일은 흔하다."""
    a = {"name": "2014-2", "questions": [_q(2, code="ADD X", answer=3)]}
    b = {"name": "2017-2", "questions": [_q(5, code="ADD X", answer=3)]}
    assert ev.conflicts([a, b]) == []


# --- 지면을 보여 주고 고르게 하기 ---------------------------------------------
def test_the_judge_prompt_shows_both_versions():
    p = ev.judge_prompt([(3, _q(code="ADD X"), _q(code="AND R1, R2, R3"))],
                        "컴퓨터구조")
    assert "[3번]" in p and "(가)" in p and "(나)" in p
    assert "ADD X" in p and "AND R1, R2, R3" in p
    assert "컴퓨터구조" in p


def test_the_judge_answer_is_read():
    raw = ('```json\n[{"no": 3, "pick": "나", "why": "상자가 AND 다"},'
           ' {"no": 4, "pick": "둘 다", "why": ""},'
           ' {"no": 5, "pick": "둘다아님"}, {"no": "몰라", "pick": "가"}]\n```')
    got = ev.parse_judge(raw)
    assert got[3]["pick"] == "new" and got[3]["why"] == "상자가 AND 다"
    assert got[4]["pick"] == "both"
    assert got[5]["pick"] == "neither"
    assert len(got) == 3


def test_a_neither_verdict_brings_the_page_version_along():
    """두 쪽 다 틀렸다면 지면대로 고쳐 적은 것을 함께 받는다."""
    raw = ('[{"no": 3, "pick": "둘다아님", "fixed": {"question": "적절한 것은?",'
           ' "code": "AND R1, R2, R3", "options": ["가", "나", "다", "라"]}}]')
    got = ev.parse_judge(raw)[3]["fixed"]
    assert got["code"] == "AND R1, R2, R3"
    assert [o["no"] for o in got["options"]] == [1, 2, 3, 4]
    assert got["options"][3]["text"] == "라"


def test_a_half_written_fix_is_not_used():
    """보기가 비었거나 물음이 없으면 고쳐 적은 것을 믿지 않는다."""
    raw = ('[{"no": 3, "pick": "둘다아님", "fixed": {"question": "",'
           ' "options": ["가", "나"]}}, {"no": 4, "pick": "둘다아님",'
           ' "fixed": {"question": "물음", "options": ["가", ""]}}]')
    got = ev.parse_judge(raw)
    assert got[3]["fixed"] is None and got[4]["fixed"] is None


def test_an_unreadable_judge_answer_gives_nothing():
    assert ev.parse_judge("모르겠습니다") == {}


# --- 정답을 모르는 채로 풀게 하기 --------------------------------------------
def test_the_solve_prompt_never_leaks_the_answer():
    """정답을 넣으면 맞춰 보는 의미가 없다."""
    p = ev.solve_prompt([_q(answer=4)], "컴퓨터구조")
    assert "정답: 4" not in p and "answer_no" not in p
    assert "AND R1, R2, R3" in p


def test_the_solve_answer_is_read():
    assert ev.parse_solve('[{"no": 3, "answer": 4}, {"no": 2}]') == {3: 4}


def test_a_picked_answer_is_checked_against_the_answer_table():
    assert ev.fits(_q(answer=4), 4) is True
    assert ev.fits(_q(answer=4), 3) is False
    assert ev.fits(_q(answer=4), None) is None          # 못 풀었다
    assert ev.fits(_q(answer=0), 3) is None             # 정답을 모른다


def test_any_of_multiple_answers_fits():
    assert ev.fits(_q(answer=2, answer_nos=[2, 4]), 4) is True


# --- 바로잡기 ---------------------------------------------------------------
def test_fixing_takes_the_sheet_content_and_keeps_the_answer_number():
    """정답 번호는 정답표에서 번호로 붙여 처음부터 맞았다."""
    old = _q(code="ADD X", answer=4, explanation="ADD X 는 1-주소 …",
             chat=[{"role": "user", "text": "왜?"}], lecture=3)
    got = ev.apply_fix(old, _q(code="AND R1, R2, R3"))
    assert got["code"] == "AND R1, R2, R3"
    assert got["answer_no"] == 4
    assert got["qid"] == "2015-2-03"


def test_fixing_drops_what_was_made_for_the_wrong_question():
    """다른 문제의 해설이 바뀐 문제 아래에 붙어 있으면 안 된다."""
    old = _q(code="ADD X", explanation="ADD X 는 …",
             chat=[{"role": "user", "text": "왜?"}], lecture=3,
             suspect="이상함")
    got = ev.apply_fix(old, _q())
    assert got["explanation"] == ""
    assert "chat" not in got and "lecture" not in got and "suspect" not in got


def test_fixing_rewrites_the_answer_text_from_the_new_options():
    old = _q(answer=2)
    new = _q(options=[{"no": i, "text": f"새 보기 {i}"} for i in range(1, 5)])
    assert ev.apply_fix(old, new)["answer_text"] == "새 보기 2"


def test_fixing_keeps_the_figure():
    """그림은 실제 시험지에서 번호로 잘라 붙였다 — 처음부터 맞다."""
    got = ev.apply_fix(_q(intro_image="a.png"), _q())
    assert got["intro_image"] == "a.png"


# --- 무엇을 할지 정하기 -----------------------------------------------------
def _pairs(old, new):
    return ev.align(old, new)


def test_an_identical_question_is_kept():
    plan = vx.decide(_pairs([_q()], [_q()]), {}, {})
    assert plan[3][0] == "keep"


def _j(pick, why="", fixed=None):
    return {"pick": pick, "why": why, "fixed": fixed}


def test_a_question_the_page_sides_with_the_new_reading_is_fixed():
    new = _q()
    plan = vx.decide(_pairs([_q(code="ADD X")], [new]), {},
                     {3: _j("new", "상자가 AND 다")})
    assert plan[3][0] == "fix" and plan[3][1] == "상자가 AND 다"
    assert plan[3][2]["code"] == "AND R1, R2, R3"


def test_when_both_are_wrong_the_page_version_is_used():
    """2015-2 의 3번 — 옛것은 'ADD X', 새로 읽은 것은 보기 한 낱말이 틀렸다."""
    fixed = {"question": "다음 컴퓨터 명령어에 관한 설명으로 적절한 것은?",
             "code": "AND R1, R2, R3",
             "options": [{"no": i + 1, "text": t} for i, t in enumerate(OPTS)]}
    plan = vx.decide(_pairs([_q(code="ADD X")], [_q(code="AND R1,R2,R")]),
                     {}, {3: _j("neither", "보기 4 가 다르다", fixed)})
    assert plan[3][0] == "fix"
    assert plan[3][2] is fixed


def test_when_the_page_sides_with_the_old_one_nothing_changes():
    """다시 읽은 쪽이 틀렸을 수도 있다 — 지면이 판정한다."""
    plan = vx.decide(_pairs([_q()], [_q(code="ADD X")]), {},
                     {3: _j("old")})
    assert plan[3][0] == "keep"


def test_when_neither_matches_a_person_must_look():
    plan = vx.decide(_pairs([_q(code="ADD X")], [_q(code="OR A")]), {},
                     {3: _j("neither")})
    assert plan[3][0] == "flag"


def test_without_a_verdict_nothing_is_changed():
    plan = vx.decide(_pairs([_q(code="ADD X")], [_q()]), {}, {})
    assert plan[3][0] == "flag"


def test_a_question_that_could_not_be_reread_is_not_touched():
    plan = vx.decide(_pairs([_q()], []), {}, {})
    assert plan[3][0] == "unread"


def test_a_question_missing_from_the_bank_is_reported():
    plan = vx.decide(_pairs([], [_q()]), {}, {})
    assert plan[3][0] == "extra"


def test_variant_banks_are_not_checked_against_a_sheet():
    """변형문제는 시험지를 옮긴 것이 아니라 만든 것이다."""
    assert vx.is_variant({"exam": {"kind": "변형문제"}})
    assert not vx.is_variant({"exam": {"kind": "기말시험"}})
