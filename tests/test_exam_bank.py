"""exam_bank 단위테스트 — 기출문제 은행 만들기.

실측 자료(C프로그래밍 자료실, 2015~2019 기말시험)에서 확인한 형식을 그대로
기대값으로 쓴다. Gemini 비전 호출은 수동 검증이다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from exam_bank import (  # noqa: E402
    attach_answers,
    bank_filename,
    exam_name,
    exam_seq,
    make_bank,
    normalize_questions,
    parse_answer_lines,
    parse_exam_title,
    term_label,
    valid_question,
    _clean_json,
)


# --- 글 제목에서 연도·학기 읽기 --------------------------------------------
def test_parse_title_handles_every_real_shape():
    """자료실 제목은 해마다 표기가 다르다 — 실측한 다섯 형식을 모두 읽는다."""
    cases = {
        "[2019-1학기] 기말시험 기출문제": (2019, 1),
        "[2017.1학기] 기말시험": (2017, 1),
        "[2015학년도 1학기] 기말시험": (2015, 1),
        "[2014.1학기 기말시험] C프로그래밍": (2014, 1),
        "[2009.2학기 기말시험]C프로그래밍": (2009, 2),
    }
    for title, want in cases.items():
        assert parse_exam_title(title) == want, title


def test_parse_title_marks_a_winter_session():
    """계절수업은 학기가 없다 — 0 으로 구분한다."""
    assert parse_exam_title("[2017 동계계절수업시험] C프로그래밍") == (2017, 0)
    assert parse_exam_title("[2011학년도 동계계절수업시험] C프로그래밍") == (2011, 0)


def test_parse_title_reads_a_year_glued_to_the_term():
    """'학기' 글자 없이 연도에 학기를 붙여 적기도 한다.

    실측: 정답표 압축 안의 '3. 2014-1기말시험정답표(최종).hwp' 를 못 읽어
    2014 회차가 통째로 빠져 있었다.
    """
    assert parse_exam_title("3. 2014-1기말시험정답표(최종).hwp") == (2014, 1)
    assert parse_exam_title("2014-2기말시험정답표(전학년) 최종.hwp") == (2014, 2)
    assert parse_exam_title("[2004.2]기말시험/C프로그래밍") == (2004, 2)


def test_parse_title_only_reads_a_term_glued_to_the_year():
    """아무 데나 있는 1·2 를 학기로 읽으면 엉뚱한 회차가 된다."""
    assert parse_exam_title("2016 기출문제 1차 배포") is None
    assert parse_exam_title("붙임1_2018. 1학기 기말시험 정답표") == (2018, 1)


def test_parse_title_gives_up_without_a_year():
    assert parse_exam_title("기출문제") is None
    assert parse_exam_title("") is None


# --- 식별·이름 --------------------------------------------------------------
def test_exam_seq_never_collides_with_a_lecture():
    """강의 차시는 1~15 다. 기출 seq 가 그 범위에 들면 같은 폴더에서 섞인다."""
    for year in (2009, 2015, 2019):
        for term in (0, 1, 2):
            assert exam_seq(year, term) > 100


def test_exam_seq_sorts_by_time():
    assert exam_seq(2015, 1) < exam_seq(2016, 1) < exam_seq(2019, 1)
    assert exam_seq(2019, 0) < exam_seq(2019, 1)     # 동계가 먼저


def test_names_read_naturally():
    assert term_label(1) == "1학기" and term_label(0) == "동계"
    assert exam_name(2019, 1) == "2019학년도 1학기 기말시험"
    assert exam_name(2017, 0).startswith("2017학년도 동계")


def test_bank_filename_is_distinct_from_lecture_banks():
    """강의 퀴즈는 'C프로그래밍_8강.json' 이다 — 한눈에 구분돼야 한다."""
    n = bank_filename("C프로그래밍", 2019, 1)
    assert n == "C프로그래밍_기출2019-1.json"
    assert "강.json" not in n


# --- 정답표 읽기 ------------------------------------------------------------
# 실측 구조: 과목명 줄 아래 5개씩 묶인 숫자, 과목 끝에 구분자 '1' 이 붙는다.
_TABLE = [
    "한국현대문학의이해와감상", "24431", "22131", "22324", "33133", "21341", "1",
    "C프로그래밍", "14142", "31312", "43234", "13343", "23122", "1",
    "데이터정보처리입문", "13322", "43242", "41441", "24243", "11111", "1",
]


def test_parse_answers_reads_the_real_table():
    """자리마다 **정답 번호들**이다 — 중복정답이면 여럿이라 목록으로 온다."""
    got = parse_answer_lines(_TABLE, "C프로그래밍")
    assert got == [[1], [4], [1], [4], [2], [3], [1], [3], [1], [2], [4], [3],
                   [2], [3], [4], [1], [3], [3], [4], [3], [2], [3], [1], [2],
                   [2]]
    assert len(got) == 25


def test_parse_answers_stops_at_the_next_course():
    """다음 과목 정답을 물고 오면 안 된다."""
    got = parse_answer_lines(_TABLE, "한국현대문학의이해와감상")
    assert len(got) == 25
    assert got[:5] == [[2], [4], [4], [3], [1]]


def test_parse_answers_ignores_the_separator():
    """과목 끝의 '1' 은 구분자이지 26번 정답이 아니다."""
    got = parse_answer_lines(_TABLE, "데이터정보처리입문")
    assert len(got) == 25 and got[-5:] == [[1], [1], [1], [1], [1]]


def test_parse_answers_ignores_spacing_in_the_name():
    assert parse_answer_lines(_TABLE, "C 프로그래밍") == \
        parse_answer_lines(_TABLE, "C프로그래밍")


def test_parse_answers_returns_nothing_for_a_missing_course():
    assert parse_answer_lines(_TABLE, "없는과목") == []
    assert parse_answer_lines([], "C프로그래밍") == []


# --- 정답 붙이기 ------------------------------------------------------------
def _q(no, n_opts=4):
    return {"qid": f"x-{no}", "question": f"문항 {no}",
            "options": [{"no": i + 1, "text": f"보기{i + 1}"}
                        for i in range(n_opts)],
            "answer_no": 0, "answer_text": ""}


def test_attach_answers_fills_number_and_text():
    qs, warn = attach_answers([_q(1), _q(2)], [3, 1])
    assert warn == []
    assert qs[0]["answer_no"] == 3 and qs[0]["answer_text"] == "보기3"
    assert qs[1]["answer_no"] == 1 and qs[1]["answer_text"] == "보기1"


def test_attach_answers_refuses_when_counts_differ():
    """한 칸 밀린 정답으로 외우는 것이 정답 없이 푸는 것보다 나쁘다."""
    qs, warn = attach_answers([_q(1), _q(2), _q(3)], [3, 1])
    assert warn and "붙이지" in warn[0]
    assert all(q["answer_no"] == 0 for q in qs)     # 아무것도 채우지 않았다


def test_attach_answers_says_when_the_table_is_missing():
    qs, warn = attach_answers([_q(1)], [])
    assert warn and "찾지 못" in warn[0]
    assert qs[0]["answer_no"] == 0


def test_attach_answers_does_not_mutate_the_input():
    src = [_q(1)]
    attach_answers(src, [2])
    assert src[0]["answer_no"] == 0     # 원본은 그대로


# --- 모델 응답 다듬기 -------------------------------------------------------
def test_clean_json_survives_a_code_fence():
    assert _clean_json('```json\n[{"a":1}]\n```') == [{"a": 1}]
    assert _clean_json('여기 있습니다:\n[{"a":2}]\n이상입니다') == [{"a": 2}]


def test_clean_json_returns_empty_on_junk():
    assert _clean_json("읽지 못했습니다") == []
    assert _clean_json("") == [] and _clean_json(None) == []
    assert _clean_json('{"not":"a list"}') == []


def test_valid_question_needs_number_text_and_options():
    assert valid_question({"no": 3, "question": "?",
                           "options": [{"no": 1, "text": "a"},
                                       {"no": 2, "text": "b"}]})
    assert not valid_question({"question": "?", "options": []})       # 번호 없음
    assert not valid_question({"no": 1, "question": "", "options": []})
    assert not valid_question({"no": 1, "question": "?",
                               "options": [{"no": 1, "text": ""}]})   # 빈 보기
    assert not valid_question("문항이 아님")


def test_normalize_sorts_and_drops_duplicates():
    """쪽 경계에서 같은 문항이 두 번 올 수 있다 — 먼저 읽은 것을 남긴다."""
    items = [{"no": 7, "question": "나중", "options": [{"no": 1, "text": "a"},
                                                      {"no": 2, "text": "b"}]},
             {"no": 3, "question": "먼저", "options": [{"no": 1, "text": "a"},
                                                      {"no": 2, "text": "b"}]},
             {"no": 7, "question": "겹침", "options": [{"no": 1, "text": "a"},
                                                      {"no": 2, "text": "b"}]},
             {"no": None, "question": "버림", "options": []}]
    got = normalize_questions(items, 2019, 1)
    assert [q["qid"] for q in got] == ["2019-1-03", "2019-1-07"]
    assert got[1]["question"] == "나중"          # 먼저 읽은 쪽이 남는다


def test_normalize_marks_the_source_and_leaves_answers_empty():
    got = normalize_questions(
        [{"no": 1, "question": "?", "points": 3,
          "options": [{"no": 1, "text": "a"}, {"no": 2, "text": "b"}]}],
        2019, 1)
    assert got[0]["source"] == "기출" and got[0]["points"] == 3
    assert got[0]["answer_no"] == 0      # 정답은 정답표에서만 온다


# --- 은행 모양 --------------------------------------------------------------
def test_make_bank_matches_what_the_quiz_screen_reads():
    b = make_bank("C프로그래밍", 2019, 1, [_q(1)])
    assert set(b) >= {"course", "seq", "name", "questions", "exam"}
    assert b["exam"] == {"year": 2019, "term": 1, "kind": "기말시험"}


def test_quiz_screen_titles_an_exam_bank_readably():
    """'20191강' 같은 엉뚱한 표기가 나오면 안 된다."""
    from app.views.quiz_view import bank_title
    t = bank_title(make_bank("C프로그래밍", 2019, 1, [_q(1)]))
    assert "기출" in t and "2019학년도 1학기" in t
    assert "20191강" not in t


def test_quiz_screen_still_titles_a_lecture_bank():
    from app.views.quiz_view import bank_title
    t = bank_title({"course": "C프로그래밍", "seq": 8, "name": "배열과 포인터"})
    assert t == "C프로그래밍 · 8강 · 배열과 포인터"


def test_lecture_banks_come_before_exam_banks(tmp_path):
    import json

    from quiz_page import collect_banks
    (tmp_path / "a.json").write_text(json.dumps(
        make_bank("C프로그래밍", 2019, 1, [_q(1)]), ensure_ascii=False),
        encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(
        {"course": "C프로그래밍", "seq": 8, "name": "배열", "questions": [_q(1)]},
        ensure_ascii=False), encoding="utf-8")
    got = collect_banks(tmp_path)
    assert [b.get("seq") for b in got] == [8, 20191]


# --- 정답표에 숫자가 아닌 표기가 섞인 경우 ---------------------------------
# 실측: 2018 '2241C', 2016 '1212K', 2015 '33CD1'. 원본에 그렇게 적혀 있다.
# 그 자리만 비우고 나머지는 살린다 — 한 회차를 통째로 버리면 멀쩡한 24문항까지
# 정답 없이 풀게 된다.
_MIXED = ["C프로그래밍", "41231", "12133", "13124", "32432", "2241C", "1",
          "데이터정보처리입문", "11111"]


def test_parse_answers_keeps_going_past_a_letter():
    """글자는 오류가 아니라 **중복정답 표기**다(정답표 첫머리의 대조표)."""
    got = parse_answer_lines(_MIXED, "C프로그래밍")
    assert len(got) == 25
    assert got[:5] == [[4], [1], [2], [3], [1]]
    assert got[24] == [1, 4]       # 'C' = 1번과 4번 둘 다 정답


def test_parse_answers_still_stops_at_the_next_course():
    """글자를 허용하더라도 과목명 줄에서는 멈춰야 한다."""
    got = parse_answer_lines(_MIXED, "C프로그래밍")
    assert got[25:] == []          # 다음 과목 정답을 물고 오지 않았다


def test_attach_answers_blanks_only_the_unknown_ones():
    qs = [_q(i) for i in range(1, 4)]
    got, warn = attach_answers(qs, [2, 0, 3])
    assert got[0]["answer_no"] == 2 and got[2]["answer_no"] == 3
    assert got[1]["answer_no"] == 0          # 모르는 것만 비었다
    assert warn and "비웠습니다" in warn[0]


def test_attach_answers_is_quiet_when_everything_is_known():
    got, warn = attach_answers([_q(1), _q(2)], [1, 2])
    assert warn == [] and all(q["answer_no"] for q in got)


# --- 중복정답 대조표 --------------------------------------------------------
# 정답표 첫머리에 '중복정답 대조표' 가 있다: A=1,2 … K=1,2,3,4(전항정답).
# 이걸 모르고 글자 자리를 비워 두는 바람에 다섯 문항이 '정답을 몰라 설명을
# 만들 수 없습니다' 로 남아 있었다.
def test_the_multi_answer_table_is_read_as_written():
    from exam_bank import answer_codes
    assert answer_codes("C") == [1, 4]
    assert answer_codes("D") == [2, 3]
    assert answer_codes("K") == [1, 2, 3, 4]      # 전항정답
    assert answer_codes("3") == [3]
    assert answer_codes("Z") == [] and answer_codes("") == []
    assert answer_codes("0") == []


def test_attach_marks_a_multi_answer_question():
    from exam_bank import attach_answers
    q = {"qid": "a", "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"},
                                 {"no": 3, "text": "다"}, {"no": 4, "text": "라"}]}
    got, warn = attach_answers([q], [[1, 4]])
    assert got[0]["answer_no"] == 1               # 예전 코드가 보는 자리
    assert got[0]["answer_nos"] == [1, 4]         # 진짜 정답은 둘
    assert got[0]["answer_text"] == "가 · 라"
    assert any("중복정답" in w for w in warn)


def test_attach_leaves_an_unreadable_mark_empty():
    from exam_bank import attach_answers
    got, warn = attach_answers([{"qid": "a", "options": []}], [[]])
    assert not got[0].get("answer_no")
    assert any("비웠습니다" in w for w in warn)
