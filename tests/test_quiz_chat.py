"""quiz_chat 단위테스트 — 해설을 읽고도 막히면 그 자리에서 되묻는다.

해설은 한 번에 한 편만 쓰인다. 읽는 사람이 어디서 막히는지는 글을 쓸 때 알 수
없다. 물음과 답은 은행 JSON 에 남아 같은 문항을 다시 열면 그대로 보인다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quiz_chat as qc  # noqa: E402
import quizbank  # noqa: E402


def _q(**over):
    d = {"qid": "2019-1-07", "question": "실행결과로 올바른 것은?",
         "code": "int a = 10, b = 3;\na *= (b - 1);",
         "intro": "※ (7~8) 다음 프로그램을 보고 답하시오.",
         "options": [{"no": 1, "text": "a = 20"}, {"no": 2, "text": "a = 30"}],
         "answer_no": 1, "answer_text": "a = 20",
         "explanation": "a 는 10 에 2 를 곱해 20 이 됩니다."}
    d.update(over)
    return d


def _bank_dir(tmp_path, *questions, course="C프로그래밍", seq=20191):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / "b.json").write_text(json.dumps(
        {"course": course, "seq": seq, "name": "2019",
         "questions": list(questions)}, ensure_ascii=False), encoding="utf-8")
    return d


# --- 저장된 대화 읽기 -------------------------------------------------------
def test_chat_turns_reads_what_was_saved():
    turns = [{"role": "user", "text": "왜 20 인가요?"},
             {"role": "model", "text": "10 에 2 를 곱해서입니다."}]
    assert qc.chat_turns(_q(chat=turns)) == turns


def test_chat_turns_is_empty_when_there_was_no_talk():
    assert qc.chat_turns(_q()) == []
    assert qc.chat_turns({}) == []
    assert qc.chat_turns(None) == []


def test_a_broken_chat_field_does_not_break_the_question():
    """은행 JSON 은 손으로 고칠 수 있다 — 엉뚱한 값이 들어와도 문항은 열린다."""
    assert qc.chat_turns(_q(chat="대화")) == []
    assert qc.chat_turns(_q(chat=["글자만", 7, None])) == []
    assert qc.chat_turns(_q(chat=[{"role": "user", "text": "  "}])) == []


def test_an_unknown_role_is_read_as_the_helper():
    """역할이 'user' 가 아니면 도우미 말로 본다 — 학생 말로 오해하지 않게."""
    got = qc.chat_turns(_q(chat=[{"role": "assistant", "text": "답"}]))
    assert got == [{"role": "model", "text": "답"}]


# --- 한 마디 덧붙이기 -------------------------------------------------------
def test_add_turn_appends_without_touching_the_original():
    base = [{"role": "user", "text": "왜?"}]
    got = qc.add_turn(base, "model", "이래서입니다")
    assert len(base) == 1                      # 원본은 그대로
    assert got[-1] == {"role": "model", "text": "이래서입니다"}


def test_an_empty_question_is_not_added():
    base = [{"role": "user", "text": "왜?"}]
    assert qc.add_turn(base, "user", "   ") == base
    assert qc.add_turn(base, "user", None) == base


def test_add_turn_trims_the_surrounding_blanks():
    got = qc.add_turn([], "user", "  왜 20 인가요?  ")
    assert got == [{"role": "user", "text": "왜 20 인가요?"}]


# --- 길어진 대화 자르기 -----------------------------------------------------
def test_trim_keeps_the_latest_turns():
    turns = [{"role": "user", "text": str(i)} for i in range(20)]
    got = qc.trim(turns, 4)
    assert [t["text"] for t in got] == ["16", "17", "18", "19"]


def test_a_short_talk_is_not_trimmed():
    turns = [{"role": "user", "text": "왜?"}]
    assert qc.trim(turns, 12) == turns
    assert qc.trim([], 12) == []


# --- 지시문 -----------------------------------------------------------------
def test_the_prompt_carries_the_question_and_the_code():
    p = qc.chat_prompt(_q(), "C프로그래밍", [], "왜 20 인가요?")
    assert "실행결과로 올바른 것은?" in p
    assert "a *= (b - 1);" in p                # 코드가 없으면 물어볼 수가 없다
    assert "※ (7~8)" in p                      # 여러 문항이 함께 쓰는 지문
    assert "1. a = 20" in p
    assert "왜 20 인가요?" in p
    assert "C프로그래밍" in p


def test_the_prompt_carries_the_explanation_already_given():
    """이미 준 해설을 모르면 같은 말을 되풀이한다."""
    p = qc.chat_prompt(_q(), "C프로그래밍", [], "더 쉽게요")
    assert "a 는 10 에 2 를 곱해 20 이 됩니다." in p


def test_the_prompt_says_the_answer_is_settled():
    """정답은 정답표에서 온 확정값이다 — 모델이 뒤집으면 안 된다."""
    p = qc.chat_prompt(_q(), "C프로그래밍", [], "2번 아닌가요?")
    assert "1번" in p
    assert "정답표에서 온 확정값" in p


def test_multiple_answers_are_all_named():
    p = qc.chat_prompt(_q(answer_nos=[1, 4]), "C프로그래밍", [], "왜요?")
    assert "1번, 4번" in p


def test_without_an_answer_table_the_prompt_says_so():
    """정답을 모르는 문항도 '어떻게 푸는지' 는 물어볼 수 있다."""
    p = qc.chat_prompt(_q(answer_no=None, answer_text=""), "C프로그래밍",
                       [], "어떻게 푸나요?")
    assert "정답표가 없다" in p
    assert "정답표에서 온 확정값" not in p


def test_the_prompt_carries_the_earlier_talk():
    turns = [{"role": "user", "text": "왜 20 인가요?"},
             {"role": "model", "text": "10 에 2 를 곱해서입니다."}]
    p = qc.chat_prompt(_q(), "C프로그래밍", turns, "그럼 b 는요?")
    assert "학생: 왜 20 인가요?" in p
    assert "도우미: 10 에 2 를 곱해서입니다." in p
    assert p.index("학생: 왜 20") < p.index("그럼 b 는요?")


def test_the_first_question_has_no_talk_block():
    p = qc.chat_prompt(_q(), "C프로그래밍", [], "왜 20 인가요?")
    assert "지금까지 나눈 대화" not in p


def test_a_long_talk_is_trimmed_before_it_goes_out():
    """대화가 길어지면 지시문이 부풀어 답이 느려지고 돈도 더 든다."""
    turns = [{"role": "user", "text": f"물음{i}"} for i in range(40)]
    p = qc.chat_prompt(_q(), "C프로그래밍", turns, "마지막")
    assert "물음39" in p
    assert "물음0\n" not in p


def test_a_question_without_a_code_block_skips_it():
    p = qc.chat_prompt(_q(code=""), "C프로그래밍", [], "왜요?")
    assert "[코드]" not in p


def test_an_empty_course_still_makes_a_prompt():
    p = qc.chat_prompt(_q(), "", [], "왜요?")
    assert "이 과목" in p


# --- 응답 다듬기 ------------------------------------------------------------
def test_the_answer_loses_its_code_fence_and_lead():
    assert qc.clean_answer("```\n이래서입니다\n```") == "이래서입니다"
    assert qc.clean_answer("네, 이래서입니다") == "이래서입니다"
    assert qc.clean_answer(None) == ""


def test_a_greeting_line_is_stripped():
    """'학생분의 질문에 답변드리겠습니다' 한 줄은 읽을 것이 없다."""
    got = qc.clean_answer("학생분의 질문에 답변드리겠습니다.\n\n10 에 2 를 곱합니다.")
    assert got == "10 에 2 를 곱합니다."


def test_a_real_sentence_about_an_answer_is_kept():
    """'답' 이 들어갔다고 본문을 지우면 안 된다."""
    body = "이 문제의 답은 1번입니다. 10 에 2 를 곱하기 때문입니다."
    assert qc.clean_answer(body) == body


def test_a_line_that_only_repeats_the_question_is_dropped():
    """'물어본 …에 대해 설명해 드릴게요' 한 줄에는 읽을 것이 없다."""
    ask = "왜 20 인가요?"
    got = qc.clean_answer(
        f'학생분이 물어본 "{ask}" 에 대해 설명해 드릴게요.\n\n10 에 2 를 곱합니다.',
        ask)
    assert got == "10 에 2 를 곱합니다."


def test_a_first_line_that_already_answers_is_kept():
    """되풀이인 줄 알고 답을 지우면 알맹이가 사라진다."""
    ask = "왜 20 인가요?"
    body = (f"{ask} 10 에 2 를 곱해 20 이 되고, 그래서 1번이 정답입니다. "
            "다른 보기는 곱셈을 거치지 않은 값입니다.\n\n두 번째 문단입니다.")
    assert qc.clean_answer(body, ask) == body


def test_the_echo_rule_needs_the_question():
    """물음을 모르면 첫 줄을 건드리지 않는다."""
    body = '학생분이 물어본 "왜 20 인가요?" 입니다.\n\n본문'
    assert qc.clean_answer(body) == body


def test_markdown_marks_are_taken_off():
    """화면은 마크다운을 그리지 않는다 — 별표가 남으면 글자로 보인다."""
    assert qc.clean_answer("**문법 오류**가 납니다") == "문법 오류가 납니다"
    assert qc.clean_answer("가\n* 나\n- 다") == "가\n· 나\n· 다"


def test_multiplication_in_the_answer_survives():
    """코드의 곱셈 별표까지 건드리면 설명이 틀어진다."""
    assert qc.clean_answer("a *= (b - 1) 은 a = a * (b - 1) 입니다") == \
        "a *= (b - 1) 은 a = a * (b - 1) 입니다"


# --- 저장 -------------------------------------------------------------------
def test_store_chat_writes_into_the_bank(tmp_path):
    d = _bank_dir(tmp_path, _q())
    bank = {"course": "C프로그래밍", "seq": 20191}
    turns = [{"role": "user", "text": "왜 20 인가요?"},
             {"role": "model", "text": "10 에 2 를 곱해서입니다."}]
    assert qc.store_chat(d, bank, "2019-1-07", turns)
    data = json.loads((d / "b.json").read_text(encoding="utf-8"))
    assert data["questions"][0]["chat"] == turns


def test_store_chat_keeps_the_explanation(tmp_path):
    """대화를 남기느라 해설을 잃으면 안 된다."""
    d = _bank_dir(tmp_path, _q())
    qc.store_chat(d, {"course": "C프로그래밍", "seq": 20191}, "2019-1-07",
                  [{"role": "user", "text": "왜?"}])
    data = json.loads((d / "b.json").read_text(encoding="utf-8"))
    assert data["questions"][0]["explanation"].startswith("a 는 10")


def test_an_empty_talk_is_not_stored(tmp_path):
    d = _bank_dir(tmp_path, _q())
    assert not qc.store_chat(d, {"course": "C프로그래밍", "seq": 20191},
                             "2019-1-07", [])


def test_storing_into_a_missing_question_fails_quietly(tmp_path):
    d = _bank_dir(tmp_path, _q())
    assert not qc.store_chat(d, {"course": "C프로그래밍", "seq": 20191},
                             "없는문항", [{"role": "user", "text": "왜?"}])


def test_the_stored_talk_survives_a_reimport(tmp_path):
    """같은 차시를 다시 담아도 나눈 대화는 남아야 한다."""
    turns = [{"role": "user", "text": "왜 20 인가요?"}]
    old = quizbank.normalize_question(_q(chat=turns))
    fresh = {"qid": "2019-1-07", "question": "실행결과로 올바른 것은?"}
    merged = quizbank.merge_questions([old], [fresh])
    assert qc.chat_turns(merged[0]) == turns


# --- 답 만들기(모델 없이) ---------------------------------------------------
class _Fake:
    """genai 클라이언트 흉내 — 지시문을 받아 정해진 답을 돌려준다."""

    def __init__(self, text="이래서입니다"):
        self.text, self.seen = text, []
        self.models = self

    def generate_content(self, model=None, contents=None, config=None):
        self.seen.append(contents[0])
        return type("R", (), {"text": self.text})()


def test_ask_returns_the_cleaned_answer():
    c = _Fake("```\n네, 이래서입니다\n```")
    assert qc.ask(c, _q(), "C프로그래밍", [], "왜 20 인가요?") == "이래서입니다"
    assert "왜 20 인가요?" in c.seen[0]


def test_an_empty_question_never_calls_the_model():
    """빈 칸으로 보내기를 눌러도 돈을 쓰지 않는다."""
    c = _Fake()
    assert qc.ask(c, _q(), "C프로그래밍", [], "   ") == ""
    assert c.seen == []


def test_a_failing_model_does_not_break_the_screen():
    class Boom:
        def __init__(self):
            self.models = self

        def generate_content(self, **_kw):
            raise RuntimeError("끊김")

    assert qc.ask(Boom(), _q(), "C프로그래밍", [], "왜요?") == ""


def test_a_very_long_question_is_cut_before_it_goes_out():
    c = _Fake()
    qc.ask(c, _q(), "C프로그래밍", [], "가" * 5000)
    assert c.seen[0].count("가") <= qc.MAX_ASK
