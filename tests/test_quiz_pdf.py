"""quiz_pdf 순수 로직 — 실제 PDF 인쇄(Chromium)는 수동 검증."""
from __future__ import annotations

import datetime as dt

import quiz_pdf as qp


def _q(qid, lec, question="물음?", answer=2, **kw):
    q = {"qid": qid, "lecture": lec, "question": question, "answer_no": answer,
         "options": [{"no": i, "text": f"보기{i}"} for i in range(1, 5)]}
    q.update(kw)
    return q


BANKS = [{"course": "C프로그래밍", "seq": 1, "name": "개요",
          "questions": [_q("a", 1, "Q1 다음 중 옳은 것은?"),
                        _q("b", 3, code="int x = 1;",
                           explanation="x 는 1 이다.")]},
         {"course": "자료구조", "seq": 1, "name": "배열",
          "questions": [_q("c", 1)]}]


def test_options_are_numbered_with_circles():
    assert qp.mark(1) == "①" and qp.mark(4) == "④"
    assert qp.mark(25) == "(25)"


def test_the_file_name_lists_the_lectures():
    assert qp.pdf_name("C프로그래밍", [5, 3]) == "C프로그래밍_3·5강_퀴즈.pdf"
    assert "문제만" in qp.pdf_name("C프로그래밍", [3], answers=False)
    many = qp.pdf_name("C프로그래밍", range(1, 10))
    assert "1강 외 8개 강" in many


def test_only_the_chosen_lectures_of_that_course_are_taken():
    secs = qp.sections(BANKS, "C프로그래밍", [3, 1, 9])
    assert [n for n, _name, _qs in secs] == [1, 3]       # 문항 없는 9강은 뺀다
    assert [q["qid"] for q in secs[0][2]] == ["a"]       # 다른 과목은 섞지 않는다


def test_a_leading_q_number_is_not_doubled():
    assert qp.stem({"question": "Q12. 다음 중 옳은 것은?"}) == "다음 중 옳은 것은?"
    assert qp.stem({"question": "Q값이 큰 것은?"}) == "Q값이 큰 것은?"


def test_the_answer_uses_the_same_marks_as_the_options():
    assert qp.answer_line(_q("a", 1)) == "정답 ② 보기2"
    both = qp.answer_line(_q("a", 1, answer_nos=[1, 4]))
    assert both.startswith("정답(중복정답)") and "①" in both and "④" in both


def test_the_answers_start_on_a_new_page_after_the_questions():
    secs = qp.sections(BANKS, "C프로그래밍", [1, 3])
    html = qp.build_html("C프로그래밍", secs, today=dt.date(2026, 11, 5))
    assert "C프로그래밍 퀴즈 — 1·3강" in html and "2문항" in html
    assert html.index("다음 중 옳은 것은?") < html.index('class="answers"')
    assert "int x = 1;" in html and "x 는 1 이다." in html
    assert "Q1 다음" not in html


def test_the_answers_can_be_left_out():
    secs = qp.sections(BANKS, "C프로그래밍", [3])
    html = qp.build_html("C프로그래밍", secs, answers=False)
    assert 'class="answers"' not in html and "x 는 1 이다." not in html


def test_text_is_escaped():
    secs = [(1, "", [_q("a", 1, "a < b && c > d ?")])]
    assert "a &lt; b &amp;&amp; c &gt; d" in qp.build_html("C", secs)


def test_an_intro_picture_is_embedded(tmp_path):
    img = tmp_path / "그림.png"
    img.write_bytes(b"\x89PNG fake")
    secs = [(1, "", [_q("a", 1, intro_path=str(img))])]
    assert "data:image/png;base64," in qp.build_html("C", secs)


def test_no_questions_means_no_pdf(tmp_path):
    import pytest
    with pytest.raises(ValueError):
        qp.make_quiz_pdf(BANKS, "C프로그래밍", [9], tmp_path / "퀴즈")


def test_an_ai_answer_is_labelled_in_the_pdf():
    assert qp.answer_line(_q("a", 1, answer_by="AI")).startswith(
        "AI 풀이 답(공식 정답 아님) ②")
