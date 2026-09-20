"""중복정답과 '정답 모름' — 채점이 사람을 속이지 않게.

방송대 정답표는 중복정답을 A~K 로 적는다(C=1,4 / K=전항정답 …). 그 글자를
'읽을 수 없는 표기' 로 보고 비워 두는 바람에 다섯 문항이 '정답을 몰라 설명을
만들 수 없습니다' 로 남았고, 그 문항에서 무엇을 고르든 **빨간색(오답)** 으로
칠해졌다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

from app.views.quiz_view import answer_text, option_tone  # noqa: E402
from quizbank import correct_nos, is_correct  # noqa: E402


def _q(**over):
    d = {"qid": "2015-1-04", "source": "기출", "question": "올바른 것은?",
         "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"},
                     {"no": 3, "text": "다"}, {"no": 4, "text": "라"}],
         "answer_no": 2, "answer_text": "나", "explanation": ""}
    d.update(over)
    return d


# --- 정답이 몇 개인가 --------------------------------------------------------
def test_correct_nos_reads_one_or_many():
    assert correct_nos(_q()) == [2]
    assert correct_nos(_q(answer_no=2, answer_nos=[2, 3])) == [2, 3]
    assert correct_nos(_q(answer_no=0)) == []
    assert correct_nos({}) == [] and correct_nos(None) == []


def test_correct_nos_ignores_junk():
    assert correct_nos(_q(answer_nos=["2", 3])) == [2, 3]
    assert correct_nos(_q(answer_nos=[])) == [2]      # 빈 목록이면 단일 정답
    assert correct_nos(_q(answer_no="셋")) == []


def test_is_correct_accepts_any_of_the_answers():
    q = _q(answer_no=2, answer_nos=[2, 3])
    assert is_correct(q, 2) and is_correct(q, 3)
    assert not is_correct(q, 1) and not is_correct(q, 4)
    assert not is_correct(_q(answer_no=0), 1)         # 모르면 맞다고 하지 않는다


# --- 보기 색 ----------------------------------------------------------------
def test_an_unknown_answer_never_paints_a_choice_red():
    """정답을 모르는 문항에서 빨간색은 거짓말이다."""
    assert option_tone(1, 1, 0) == "selected"
    assert option_tone(1, 1, None) == "selected"
    assert option_tone(1, 1, "") == "selected"


def test_both_answers_of_a_multi_question_are_green():
    assert option_tone(2, 2, 2, [2, 3]) == "correct"
    assert option_tone(3, 3, 2, [2, 3]) == "correct"
    assert option_tone(1, 1, 2, [2, 3]) == "wrong"


def test_a_single_answer_still_works():
    assert option_tone(2, 2, 2) == "correct"
    assert option_tone(1, 1, 2) == "wrong"
    assert option_tone(1, 2, 2) == "plain"       # 고르지 않은 보기


# --- 정답 줄 문구 ------------------------------------------------------------
def test_the_answer_line_lists_every_correct_choice():
    """'정답: 2번' 만 보이면 3을 고르고 맞힌 사람이 틀린 줄 안다."""
    got = answer_text(_q(answer_no=2, answer_nos=[2, 3]))
    assert "중복정답" in got and "2. 나" in got and "3. 다" in got


def test_the_answer_line_stays_simple_for_one_answer():
    assert answer_text(_q()) == "정답: 2. 나"


def test_the_answer_line_says_so_when_it_is_unknown():
    assert answer_text(_q(answer_no=0, answer_text="")) == "정답 정보 없음"


# --- 화면에 이어 붙였을 때 ---------------------------------------------------
def _dir(tmp_path, *qs, course="C프로그래밍", seq=20151):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / "b.json").write_text(json.dumps(
        {"course": course, "seq": seq, "name": "2015학년도 1학기 기말시험",
         "exam": {"year": 2015, "term": 1}, "questions": list(qs)},
        ensure_ascii=False), encoding="utf-8")
    return d


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _choose(view, n=0):
    """n 번째 보기를 고른다(보기는 on_click 이 달린 Container 다)."""
    opts = [c for c in _walk(view) if isinstance(c, ft.Container)
            and getattr(c, "on_click", None)]
    opts[n].on_click(None)


def test_choosing_the_other_correct_answer_is_marked_right(tmp_path):
    from app.views.quiz_view import build_quiz_view
    d = _dir(tmp_path, _q(answer_no=2, answer_nos=[2, 3]))
    v = build_quiz_view(quiz_dir=d)
    _choose(v, 2)                                  # 3번 보기
    rec = json.loads((d / "_풀이기록.json").read_text(encoding="utf-8"))
    assert list(rec.values())[0]["last_ok"] is True


def test_an_unknown_answer_is_not_graded_at_all(tmp_path):
    """정답을 모르는 문항을 오답으로 기록하면 '틀린 것부터 다시' 가 더럽혀진다."""
    from app.views.quiz_view import build_quiz_view
    d = _dir(tmp_path, _q(answer_no=0, answer_text=""))
    v = build_quiz_view(quiz_dir=d)
    _choose(v, 0)
    assert not (d / "_풀이기록.json").exists() or \
        json.loads((d / "_풀이기록.json").read_text(encoding="utf-8")) == {}


# --- 복습 HTML --------------------------------------------------------------
def test_the_html_card_carries_every_answer():
    from quiz_html import render_quiz_html
    html = render_quiz_html([{"course": "C프로그래밍", "seq": 20151,
                              "name": "2015",
                              "questions": [_q(answer_no=2,
                                               answer_nos=[2, 3])]}])
    assert 'data-answer-nos="2,3"' in html
    assert "중복정답" in html


def test_the_html_leaves_an_unknown_answer_blank():
    from quiz_html import render_quiz_html
    html = render_quiz_html([{"course": "C프로그래밍", "seq": 20151,
                              "name": "2015",
                              "questions": [_q(answer_no=0, answer_text="")]}])
    assert 'data-answer-nos=""' in html
    assert "정답 정보 없음" in html


def test_the_html_script_grades_against_the_list():
    from quiz_html import _JS
    assert "data-answer-nos" in _JS


# --- 걸러낸 변형은 화면에 올리지 않는다 --------------------------------------
def test_a_suspect_question_is_kept_out_of_the_quiz(tmp_path):
    """물음과 답이 어긋난 문항은 풀수록 잘못 외운다(check_variants.py)."""
    from quiz_page import collect_banks
    d = _dir(tmp_path, _q(qid="좋은문항"),
             _q(qid="어긋난문항", suspect="검토에서는 3번이 답입니다"))
    banks = collect_banks(d)
    assert [q["qid"] for q in banks[0]["questions"]] == ["좋은문항"]


def test_dropping_suspects_leaves_a_clean_bank_alone():
    from quiz_page import drop_suspect
    bank = {"questions": [_q(qid="a")]}
    assert drop_suspect(bank) is bank        # 손댈 것이 없으면 그대로
