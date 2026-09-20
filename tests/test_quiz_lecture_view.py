"""퀴즈 화면·복습 HTML 의 'N강 모아보기' — 화면에 실제로 붙었는지 본다.

문항마다 '3강' 표지가 보이고, [강 모아보기] 에서 3강을 고르면 회차를 가로질러
3강 문항만 모인다. 그때도 풀이 기록은 **제 은행**으로 가야 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

import quiz_lecture as ql  # noqa: E402


def _q(qid, **over):
    d = {"qid": qid, "source": "기출", "question": f"{qid} 문제",
         "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
         "answer_no": 1, "answer_text": "가", "explanation": ""}
    d.update(over)
    return d


def _quiz_dir(tmp_path):
    """3강 문항이 세 은행(형성평가·2019 기출·2017 기출)에 흩어져 있는 폴더."""
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)

    def put(name, bank):
        (d / name).write_text(json.dumps(bank, ensure_ascii=False),
                              encoding="utf-8")

    put("lec3.json", {"course": "C프로그래밍", "seq": 3,
                      "name": "입.출력 함수와 연산자(1)",
                      "questions": [_q("형성1", source="형성평가")]})
    put("lec8.json", {"course": "C프로그래밍", "seq": 8, "name": "배열과 포인터(1)",
                      "questions": [_q("형성8", source="형성평가")]})
    put("e2019.json", {"course": "C프로그래밍", "seq": 20191,
                       "name": "2019학년도 1학기 기말시험",
                       "exam": {"year": 2019, "term": 1, "kind": "기말시험"},
                       "questions": [_q("2019-1-03", lecture=3),
                                     _q("2019-1-09", lecture=8)]})
    put("e2017.json", {"course": "C프로그래밍", "seq": 20171,
                       "name": "2017학년도 1학기 기말시험",
                       "exam": {"year": 2017, "term": 1, "kind": "기말시험"},
                       "questions": [_q("2017-1-05", lecture=3)]})
    return d


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _texts(view):
    return [str(c.value or "") for c in _walk(view) if isinstance(c, ft.Text)]


def _lec_dropdown(view):
    return next(c for c in _walk(view) if isinstance(c, ft.Dropdown)
                and c.label == "강 모아보기")


def _gather(view, n):
    """[강 모아보기] 에서 N강을 고른다."""
    d = _lec_dropdown(view)
    d.value = str(n)
    d.on_select(None)


# --- 표지 -------------------------------------------------------------------
def test_a_tagged_question_wears_its_lecture(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    _gather(v, 3)
    assert "3강" in _texts(v)


def test_an_untagged_question_wears_nothing():
    """안 가린 문항에 '0강' 이 붙으면 거짓 정보가 된다."""
    from app.views.quiz_view import lecture_chip
    assert lecture_chip({"qid": "x"}) == []
    assert len(lecture_chip({"qid": "x", "lecture": 3})) == 1


# --- 모아 보기 --------------------------------------------------------------
def test_the_dropdown_lists_only_lectures_that_have_questions(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    got = [o.text for o in _lec_dropdown(v).options]
    assert got == ["전체", "3강", "8강"]


def test_gathering_pulls_that_lecture_from_every_round(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    _gather(v, 3)
    t = "\n".join(_texts(v))
    assert "형성1 문제" in t and "2019-1-03 문제" in t and "2017-1-05 문제" in t
    assert "2019-1-09 문제" not in t        # 8강 문항은 끼지 않는다


def test_gathering_shows_where_each_question_came_from(tmp_path):
    """회차가 섞이므로 '2019 기출인지 형성평가인지' 를 알 수 있어야 한다."""
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    _gather(v, 3)
    assert any("2019학년도 1학기 기말시험" in t for t in _texts(v))


def test_the_title_says_it_is_a_gathering(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    _gather(v, 3)
    assert any("3강 모아보기" in t for t in _texts(v))


def test_picking_a_round_again_releases_the_gathering(tmp_path):
    """은행을 직접 고르면 모아보기가 풀린다 — 고른 은행이 안 보이면 이상하다."""
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    _gather(v, 3)
    picker = next(c for c in _walk(v) if isinstance(c, ft.Dropdown)
                  and c.label == "강의")
    picker.value = "1"                      # 8강 강의 퀴즈
    picker.on_select(None)
    t = "\n".join(_texts(v))
    assert "형성8 문제" in t and "2017-1-05 문제" not in t


def test_the_answer_is_recorded_under_the_home_bank(tmp_path):
    """모아 봐도 기록은 제 은행으로 — 회차별로 볼 때와 같은 자리에 쌓인다."""
    from app.views.quiz_view import build_quiz_view
    d = _quiz_dir(tmp_path)
    v = build_quiz_view(quiz_dir=d)
    _gather(v, 3)
    # 첫 문항의 첫 보기를 고른다(보기는 on_click 이 달린 Container 다)
    opt = next(c for c in _walk(v) if isinstance(c, ft.Container)
               and getattr(c, "on_click", None))
    opt.on_click(None)
    prog = json.loads((d / "_풀이기록.json").read_text(encoding="utf-8"))
    assert list(prog) == ["C프로그래밍|3|형성1"]


# --- 복습 HTML --------------------------------------------------------------
def test_the_html_card_carries_the_lecture():
    from quiz_html import render_quiz_html
    html = render_quiz_html([{"course": "C프로그래밍", "seq": 20191,
                              "name": "2019", "exam": {"year": 2019},
                              "questions": [_q("a", lecture=3),
                                            _q("b", lecture=8)]}])
    assert 'data-lecture="3"' in html and '<span class="badge lec">3강<' in html


def test_the_html_page_offers_a_lecture_filter():
    from quiz_html import render_quiz_html
    html = render_quiz_html([{"course": "C프로그래밍", "seq": 20191,
                              "name": "2019",
                              "questions": [_q("a", lecture=3),
                                            _q("b", lecture=8)]}])
    assert 'class="lec-filter"' in html
    assert 'data-lec="3"' in html and 'data-lec="8"' in html


def test_the_html_filter_is_left_out_when_there_is_nothing_to_filter():
    """강이 하나뿐이면 거를 것이 없다 — 빈 칩 줄만 남는다."""
    from quiz_html import lecture_filter
    assert lecture_filter([{"questions": [_q("a", lecture=3)]}]) == ""
    assert lecture_filter([{"questions": [_q("a")]}]) == ""


# 실측 불편: C프로그래밍 3강을 모았더니 자료구조 '스택'(3강) 과 오픈소스 3강
# 문항까지 딸려 나왔다. 차시 번호는 과목마다 따로 도는 번호다.
def test_the_html_filter_keeps_courses_apart():
    from quiz_html import filter_pairs, render_quiz_html
    lecs = [{"course": "C프로그래밍", "seq": 3, "name": "입.출력",
             "questions": [_q("a", lecture=3)]},
            {"course": "자료구조", "seq": 3, "name": "스택",
             "questions": [_q("b", lecture=3)]}]
    assert filter_pairs(lecs) == [("C프로그래밍", 3), ("자료구조", 3)]
    html = render_quiz_html(lecs)
    assert 'data-course="C프로그래밍" data-lec="3"' in html
    assert 'data-course="자료구조" data-lec="3"' in html


def test_the_html_card_says_which_course_it_belongs_to():
    from quiz_html import render_quiz_html
    html = render_quiz_html([{"course": "자료구조", "seq": 3, "name": "스택",
                              "questions": [_q("b", lecture=3)]}])
    assert 'data-course="자료구조"' in html


def test_banks_loaded_for_the_page_carry_their_lecture(tmp_path):
    """강의 퀴즈는 은행의 차시가 곧 강 — 따로 가릴 것이 없다."""
    from quiz_page import collect_banks
    banks = collect_banks(_quiz_dir(tmp_path))
    lec3 = next(b for b in banks if b.get("seq") == 3)
    assert ql.lecture_no(lec3["questions"][0]) == 3
