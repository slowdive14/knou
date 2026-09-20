"""quiz_lecture 단위테스트 — 문항이 몇 강인지 가리고, 그 강만 모아 본다.

기출은 회차로만 묶여 있어서 '3강까지 들었으니 3강 문제만' 이 안 됐다. 문항
마다 강을 가려 두고, 회차를 가로질러 그 강의 문항을 한 자리에 모은다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quiz_lecture as ql  # noqa: E402
import quiz_progress as qp  # noqa: E402


def _q(**over):
    d = {"qid": "2019-1-07", "source": "기출", "question": "실행결과는?",
         "code": "", "intro": "", "options": [{"no": 1, "text": "가"},
                                              {"no": 2, "text": "나"}],
         "answer_no": 1, "answer_text": "가", "explanation": ""}
    d.update(over)
    return d


def _lec_bank(seq, name, *qs, course="C프로그래밍"):
    return {"course": course, "seq": seq, "name": name, "questions": list(qs)}


def _exam_bank(*qs, course="C프로그래밍", seq=20191, kind="기말시험"):
    return {"course": course, "seq": seq, "name": "2019학년도 1학기 기말시험",
            "exam": {"year": 2019, "term": 1, "kind": kind},
            "questions": list(qs)}


# --- 읽기와 표기 ------------------------------------------------------------
def test_lecture_no_reads_a_tag():
    assert ql.lecture_no(_q(lecture=3)) == 3
    assert ql.lecture_no(_q(lecture="5")) == 5      # 문자열로 들어와도
    assert ql.lecture_no(_q()) == 0
    assert ql.lecture_no(_q(lecture=0)) == 0
    assert ql.lecture_no(_q(lecture="셋")) == 0     # 못 읽으면 안 가린 것
    assert ql.lecture_no(None) == 0


def test_lecture_label_is_blank_when_untagged():
    """안 가린 문항에 '0강' 이 붙으면 안 된다 — 아무것도 붙이지 않는다."""
    assert ql.lecture_label(3) == "3강"
    assert ql.lecture_label(0) == "" and ql.lecture_label(None) == ""


def test_untagged_keeps_only_what_is_left():
    qs = [_q(qid="a", lecture=1), _q(qid="b")]
    assert [q["qid"] for q in ql.untagged(qs)] == ["b"]


# --- 강의 목차 --------------------------------------------------------------
def test_catalog_comes_from_lecture_banks_only():
    """기출 은행의 seq 는 정렬용 큰 수(20191)라 목차가 될 수 없다."""
    banks = [_exam_bank(_q()), _lec_bank(3, "입.출력"), _lec_bank(1, "개요")]
    assert ql.catalog(banks) == [(1, "개요"), (3, "입.출력")]


def test_catalog_keeps_one_course():
    banks = [_lec_bank(1, "개요"), _lec_bank(1, "자료구조", course="자료구조")]
    assert ql.catalog(banks, "자료구조") == [(1, "자료구조")]


def test_catalog_text_carries_hints():
    text = ql.catalog_text([(6, "함수(1)"), (7, "함수(2)")],
                           {7: "변수의 유효범위"})
    assert "6강. 함수(1)" in text and "7강. 함수(2) — 변수의 유효범위" in text


def test_topic_hints_prefer_the_meatiest_questions():
    """'위 프로그램의 출력은?' 은 그 강의 범위를 알려주지 못한다."""
    b = _lec_bank(7, "함수와 기억 클래스(2)",
                  _q(qid="a", question="위 프로그램의 출력은?"),
                  _q(qid="b", question="다음 중 변수의 유효범위와 존속기간에 "
                                       "대한 설명으로 옳은 것은?"))
    got = ql.topic_hints([b], per=1)
    assert "유효범위" in got[7]


def test_topic_hints_ignore_exam_banks():
    assert ql.topic_hints([_exam_bank(_q())]) == {}


# --- 분류 지시문 ------------------------------------------------------------
def test_question_brief_carries_what_decides_the_unit():
    q = _q(intro="※ 다음 프로그램", code="int a;\nchar *p;", question="결과는?")
    brief = ql.question_brief(q)
    assert "다음 프로그램" in brief and "char *p" in brief
    assert "1) 가" in brief


def test_question_brief_trims_a_long_code():
    q = _q(code="\n".join(f"line{i};" for i in range(40)))
    brief = ql.question_brief(q, code_lines=5)
    assert "line4;" in brief and "line9;" not in brief and "…" in brief


def test_prompt_carries_the_catalog_and_every_qid():
    p = ql.classify_prompt([_q(qid="a"), _q(qid="b")],
                           [(1, "개요"), (2, "자료형")], "C프로그래밍")
    assert "1강. 개요" in p and "--- a" in p and "--- b" in p
    assert "목차에 있는 번호 중 하나" in p


# --- 응답 읽기 --------------------------------------------------------------
def test_parse_reads_the_usual_shapes():
    raw = "2019-1-01=3\n2019-1-02 : 5\n- 2019-1-03: 7"
    got = ql.parse_lectures(raw, ["2019-1-01", "2019-1-02", "2019-1-03"],
                            [(n, "") for n in range(1, 16)])
    assert got == {"2019-1-01": 3, "2019-1-02": 5, "2019-1-03": 7}


def test_parse_drops_a_number_outside_the_catalog():
    """15강짜리 과목에 '17강' 이 붙으면 그 문항은 어디에도 안 나온다."""
    got = ql.parse_lectures("a=17\nb=3", ["a", "b"],
                            [(n, "") for n in range(1, 16)])
    assert got == {"b": 3}


def test_parse_drops_a_qid_we_did_not_ask_about():
    got = ql.parse_lectures("a=3\nz=4", ["a"], [(3, ""), (4, "")])
    assert got == {"a": 3}


def test_parse_survives_an_empty_answer():
    assert ql.parse_lectures("", ["a"], [(1, "")]) == {}
    assert ql.parse_lectures(None, ["a"], [(1, "")]) == {}


# --- 변형은 물려받는다 ------------------------------------------------------
def test_variants_inherit_from_their_origin():
    """개념이 같은데 따로 가리면 같은 개념이 두 군데로 흩어진다."""
    v = [_q(qid="a-v1", origin="a"), _q(qid="b-v1", origin="없는원본")]
    assert ql.inherit_map(v, {"a": 8}) == {"a-v1": 8}


def test_inheriting_leaves_a_tagged_variant_alone():
    v = [_q(qid="a-v1", origin="a", lecture=2)]
    assert ql.inherit_map(v, {"a": 8}) == {}


def test_force_makes_a_variant_follow_its_origin_again():
    """기출을 다시 가린 뒤에는 변형도 따라가야 어긋나지 않는다."""
    v = [_q(qid="a-v1", origin="a", lecture=2)]
    assert ql.inherit_map(v, {"a": 8}, force=True) == {"a-v1": 8}


# --- 화면에 올릴 때 붙이는 표시 ---------------------------------------------
def test_stamp_gives_a_lecture_bank_question_its_own_seq():
    """강의 퀴즈는 은행의 차시가 곧 강이라 가릴 것이 없다."""
    banks = [_lec_bank(3, "입.출력", _q(qid="x"))]
    ql.stamp_origins(banks)
    assert ql.lecture_no(banks[0]["questions"][0]) == 3


def test_stamp_does_not_invent_a_lecture_for_an_exam_question():
    banks = [_exam_bank(_q(qid="x"))]
    ql.stamp_origins(banks)
    assert ql.lecture_no(banks[0]["questions"][0]) == 0


def test_stamp_records_where_the_question_came_from():
    banks = [_exam_bank(_q(qid="x"))]
    ql.stamp_origins(banks)
    q = banks[0]["questions"][0]
    assert q["bank_key"] == "C프로그래밍|20191|x"
    assert q["bank_name"] == "2019학년도 1학기 기말시험"


def test_stamp_never_writes_to_the_bank_file(tmp_path):
    """표시는 화면에서만 쓴다 — 파일에 새면 은행이 지저분해진다."""
    p = tmp_path / "b.json"
    p.write_text(json.dumps(_lec_bank(3, "입.출력", _q(qid="x")),
                            ensure_ascii=False), encoding="utf-8")
    banks = [json.loads(p.read_text(encoding="utf-8"))]
    ql.stamp_origins(banks)
    assert "bank_key" not in p.read_text(encoding="utf-8")


# --- 모아 보기 --------------------------------------------------------------
def _three_banks():
    return [_lec_bank(3, "입.출력 함수와 연산자(1)", _q(qid="형성1")),
            _exam_bank(_q(qid="2019-1-03", lecture=3),
                       _q(qid="2019-1-09", lecture=8)),
            _exam_bank(_q(qid="2017-1-05", lecture=3), seq=20171)]


def test_lecture_numbers_lists_only_what_has_questions():
    assert ql.lecture_numbers(ql.stamp_origins(_three_banks())) == [3, 8]


def test_gather_collects_one_lecture_across_every_round():
    banks = ql.stamp_origins(_three_banks())
    got = ql.gather(banks, "C프로그래밍", 3)
    assert [q["qid"] for q in got["questions"]] == ["형성1", "2019-1-03",
                                                    "2017-1-05"]
    assert got["lecture_pick"] == 3
    assert got["name"] == "입.출력 함수와 연산자(1)"      # 목차에서 가져온 제목


def test_gather_leaves_another_course_out():
    banks = ql.stamp_origins(_three_banks() +
                             [_lec_bank(3, "다른 3강", _q(qid="딴과목"),
                                        course="자료구조")])
    got = ql.gather(banks, "C프로그래밍", 3)
    assert "딴과목" not in [q["qid"] for q in got["questions"]]


def test_gathered_questions_keep_their_own_record_key():
    """모아 봐도 기록은 제 은행으로 간다 — 회차별 기록과 갈라지면 안 된다."""
    banks = ql.stamp_origins(_three_banks())
    got = ql.gather(banks, "C프로그래밍", 3)
    keys = [qp.key_for(got, q) for q in got["questions"]]
    assert "C프로그래밍|20191|2019-1-03" in keys
    assert not any(k.startswith("C프로그래밍|3|2019") for k in keys)


def test_gather_hands_back_the_same_question_objects():
    """복사해 넘기면 방금 만든 해설이 화면을 바꿀 때 사라진다."""
    banks = ql.stamp_origins(_three_banks())
    got = ql.gather(banks, "C프로그래밍", 3)
    assert got["questions"][1] is banks[1]["questions"][0]


# --- 파일에 써넣기 ----------------------------------------------------------
def _write(tmp_path, bank, name="b.json"):
    p = tmp_path / name
    p.write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")
    return p


def test_write_lectures_tags_the_right_questions(tmp_path):
    p = _write(tmp_path, _exam_bank(_q(qid="a"), _q(qid="b")))
    assert ql.write_lectures(p, {"a": 3, "b": 8}) == 2
    data = json.loads(p.read_text(encoding="utf-8"))
    assert {q["qid"]: q["lecture"] for q in data["questions"]} == {"a": 3,
                                                                  "b": 8}
    assert not list(tmp_path.glob("*.tmp"))     # 임시 파일이 남지 않는다


def test_write_lectures_skips_what_is_already_right(tmp_path):
    p = _write(tmp_path, _exam_bank(_q(qid="a", lecture=3)))
    assert ql.write_lectures(p, {"a": 3}) == 0


def test_write_lectures_refuses_junk(tmp_path):
    p = _write(tmp_path, _exam_bank(_q(qid="a")))
    assert ql.write_lectures(p, {"a": 0}) == 0
    assert ql.write_lectures(p, {}) == 0
    assert ql.write_lectures(tmp_path / "없음.json", {"a": 3}) == 0


def test_store_lectures_finds_the_bank_by_course_and_round(tmp_path):
    _write(tmp_path, _exam_bank(_q(qid="a")), "x.json")
    n = ql.store_lectures(tmp_path, {"course": "C프로그래밍", "seq": 20191},
                          {"a": 5})
    assert n == 1
    assert ql.store_lectures(tmp_path, {"course": "없는과목", "seq": 1},
                             {"a": 5}) == 0


# --- 생성(모형 클라이언트) --------------------------------------------------
class _Client:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.prompts = []

        class _M:
            def generate_content(_s, **kw):
                self.prompts.append(kw.get("contents")[0])
                t = self.texts.pop(0)
                if isinstance(t, Exception):
                    raise t

                class _R:
                    text = t
                return _R()
        self.models = _M()


def test_make_lectures_asks_in_batches():
    """한 문항씩 물으면 호출이 125번 든다 — 묶어서 보낸다."""
    c = _Client("a=1\nb=2", "c=3")
    qs = [_q(qid="a"), _q(qid="b"), _q(qid="c")]
    got = ql.make_lectures(c, qs, [(1, ""), (2, ""), (3, "")], chunk=2)
    assert got == {"a": 1, "b": 2, "c": 3}
    assert len(c.prompts) == 2


def test_make_lectures_keeps_going_after_a_failed_batch():
    c = _Client(RuntimeError("끊김"), "c=3")
    got = ql.make_lectures(c, [_q(qid="a"), _q(qid="c")], [(3, "")], chunk=1)
    assert got == {"c": 3}


def test_make_lectures_passes_the_hints_along():
    c = _Client("a=7")
    ql.make_lectures(c, [_q(qid="a")], [(7, "함수(2)")],
                     hints={7: "변수의 유효범위"})
    assert "변수의 유효범위" in c.prompts[0]


# --- 목차는 강의 목록에서 -----------------------------------------------------
# 실측: 퀴즈 은행에서 목차를 만들면 형성평가를 담은 차시까지만 잡힌다. 자료구조는
# 1~4강뿐이고 컴퓨터구조는 아예 없어서, 그대로 분류를 돌리면 5~15강 문항이
# 1~4강에 억지로 배정된다. lectures.json 에는 15강 목차가 제목까지 들어 있다.
_LIST = {"courses": [
    {"name": "자료구조", "lectures": [{"seq": 1, "name": "자료구조란 무엇인가?"},
                                      {"seq": 2, "name": "배열"},
                                      {"seq": 15, "name": "정렬"}]},
    {"name": "C프로그래밍", "lectures": [{"seq": 1, "name": "C 언어의 개요"}]}]}


def test_the_catalog_comes_from_the_lecture_list():
    got = ql.catalog_from_list(_LIST, "자료구조")
    assert got == [(1, "자료구조란 무엇인가?"), (2, "배열"), (15, "정렬")]


def test_the_catalog_keeps_one_course():
    assert ql.catalog_from_list(_LIST, "C프로그래밍") == [(1, "C 언어의 개요")]
    assert ql.catalog_from_list(_LIST, "없는과목") == []


def test_the_catalog_survives_junk():
    assert ql.catalog_from_list({}, "자료구조") == []
    assert ql.catalog_from_list(None) == []
    assert ql.catalog_from_list({"courses": [{"name": "x", "lectures": [
        {"seq": "둘"}, {"seq": 0}]}]}, "x") == []


def test_loading_prefers_the_lecture_list(tmp_path):
    import json
    p = tmp_path / "lectures.json"
    p.write_text(json.dumps(_LIST, ensure_ascii=False), encoding="utf-8")
    banks = [_lec_bank(1, "은행에서 온 제목", course="자료구조")]
    got = ql.load_catalog("자료구조", banks, p)
    assert len(got) == 3 and got[0][1] == "자료구조란 무엇인가?"


def test_loading_falls_back_to_the_banks(tmp_path):
    """강의 목록이 없으면 예전처럼 퀴즈 은행에서 만든다."""
    banks = [_lec_bank(3, "입.출력")]
    got = ql.load_catalog("C프로그래밍", banks, tmp_path / "없음.json")
    assert got == [(3, "입.출력")]
