"""harvest_quiz 순수 로직 — 로그인·페이지 받기는 수동 검증."""
from __future__ import annotations

import harvest_quiz as hq
from quizbank import answer_text, merge_questions, normalize_question


def _q(qid, answer=None, opts=4, **kw):
    q = {"qid": qid, "question": "물음?", "answer_no": answer,
         "options": [{"no": i, "text": f"보기{i}"} for i in range(1, opts + 1)]}
    q.update(kw)
    return q


def test_only_questions_without_any_answer_are_solved():
    qs = [_q("a"), _q("b", 2), _q("c", answer_text="참"), _q("d", opts=0)]
    assert [q["qid"] for q in hq.unanswered(qs)] == ["a"]


def test_ai_answers_are_marked_and_bad_numbers_dropped():
    qs = [_q("a"), _q("b"), _q("c")]
    assert hq.apply_ai_answers(qs, {1: 3, 2: 9}) == 1
    assert qs[0]["answer_no"] == 3 and qs[0]["answer_by"] == "AI"
    assert qs[1]["answer_no"] is None and "answer_by" not in qs[1]


def test_an_ai_answer_says_so_on_screen():
    q = _q("a", 3, answer_by="AI")
    assert answer_text(q).startswith("AI 풀이 답(공식 정답 아님)")
    assert answer_text(_q("a", 3)).startswith("정답:")


def test_the_ai_mark_survives_a_merge_without_a_new_answer():
    old = normalize_question(_q("a", 3, answer_by="AI"))
    got = merge_questions([old], [normalize_question(_q("a"))])[0]
    assert got["answer_no"] == 3 and got["answer_by"] == "AI"


def test_the_school_answer_replaces_the_ai_one():
    """나중에 이수로 풀면 학교 정답이 들어온다 — AI 표시는 떼야 한다."""
    old = normalize_question(_q("a", 3, answer_by="AI"))
    got = merge_questions([old], [normalize_question(_q("a", 2))])[0]
    assert got["answer_no"] == 2 and "answer_by" not in got


def test_solving_renumbers_so_answers_land_on_the_right_question(monkeypatch):
    seen = []

    def fake_solve(client, qs, course, on_event=None, chunk=12):
        seen.append([q["qid"] for q in qs])
        return {1: 2, 2: 4}
    import exam_verify as ev
    monkeypatch.setattr(ev, "solve", fake_solve)
    qs = [_q("74151"), _q("75151", 1), _q("74152")]
    assert hq.solve_with_ai(object(), qs, "자료구조") == 2
    assert seen == [["x-1", "x-2"]]
    assert qs[0]["answer_no"] == 2 and qs[2]["answer_no"] == 4
    assert qs[1]["answer_no"] == 1 and "answer_by" not in qs[1]
