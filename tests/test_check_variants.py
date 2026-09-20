"""변형 문항 검토 — 어긋난 문항을 빼되, **멀쩡한 문항을 빼지 않게**.

실측으로 드러난 것들:
  - 부정형이 사라진 변형('아닌 것은?' → '적절한 것은?')이 정답은 그대로였다.
  - 검토가 4지선다에 answer=8 처럼 **보기 번호 대신 계산값**을 돌려주었다.
  - 컴파일러로 이미 확인한 문항을 모델 말만 듣고 뺄 뻔했다.
  - 한 번의 검토는 흔들린다(answer=1 이라 해 놓고 이유에서는 2번이 맞다고 함).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import check_variants as cv  # noqa: E402
import quiz_variant as qv  # noqa: E402


def _q(**over):
    d = {"qid": "2016-1-02-v1", "source": "기출변형", "origin": "2016-1-02",
         "question": "다음 중 문자를 하나 입력받는 함수로 가장 적절한 것은?",
         "code": "", "options": [{"no": 1, "text": "fgetc()"},
                                 {"no": 2, "text": "getc()"},
                                 {"no": 3, "text": "getchar()"},
                                 {"no": 4, "text": "gets_s()"}],
         "answer_no": 4, "answer_text": "gets_s()"}
    d.update(over)
    return d


# --- 검토 지시문 -------------------------------------------------------------
def test_the_prompt_hides_the_answer():
    """정답을 알려주면 그걸 변호하느라 어긋난 것을 못 잡는다(해설과 정반대다)."""
    p = qv.review_prompt(_q())
    assert "gets_s()" in p              # 보기로는 들어간다
    assert "정답은 알려주지 않았다" in p
    assert "4번이다" not in p


def test_the_prompt_says_how_many_choices_there_are():
    """보기 번호 대신 계산값을 적는 일이 있었다 — 범위를 못 박는다."""
    assert "1~4 중 하나" in qv.review_prompt(_q())


def test_the_prompt_asks_about_negation():
    assert "아닌 것" in qv.review_prompt(_q())


# --- 응답 읽기 ---------------------------------------------------------------
def test_parse_reads_the_number_and_the_reason():
    got, why = qv.parse_review("answer=3\nreason=getchar 가 문자 하나를 읽는다")
    assert got == 3 and "getchar" in why


def test_parse_says_it_could_not_read():
    """0 은 '문항이 성립하지 않는다' 는 뜻이라 '못 읽었다' 와 달라야 한다."""
    assert qv.parse_review("무슨 말인지 모르겠습니다")[0] == -1
    assert qv.parse_review("")[0] == -1
    assert qv.parse_review("answer=0\nreason=정답이 없다")[0] == 0


# --- 판정 -------------------------------------------------------------------
def test_agreement_leaves_the_question_alone():
    assert qv.review_verdict(_q(), 4, "맞다") == ""


def test_disagreement_is_reported():
    got = qv.review_verdict(_q(), 3, "getchar 가 맞다")
    assert "3번" in got and "4번" in got


def test_a_question_that_does_not_hold_is_reported():
    assert "성립하지 않습니다" in qv.review_verdict(_q(), 0, "정답이 없다")


def test_a_number_outside_the_choices_is_not_trusted():
    """4지선다에 8번은 보기 번호가 아니라 계산값이다 — 믿고 빼면 안 된다."""
    assert qv.review_verdict(_q(), 8, "결과는 8이다") == ""


def test_an_unreadable_review_changes_nothing():
    assert qv.review_verdict(_q(), -1, "") == ""


# --- 여러 번 물어 보기 -------------------------------------------------------
class _Client:
    def __init__(self, *texts):
        self.texts = list(texts)
        self.calls = 0

        class _M:
            def generate_content(_s, **kw):
                self.calls += 1
                t = self.texts[min(self.calls - 1, len(self.texts) - 1)]

                class _R:
                    text = t
                return _R()
        self.models = _M()


def test_two_reviews_that_agree_are_used():
    c = _Client("answer=3\nreason=가", "answer=3\nreason=나")
    got, why = cv.review_vote(c, _q(), "C프로그래밍", votes=2)
    assert got == 3 and c.calls == 2


def test_two_reviews_that_disagree_are_thrown_away():
    """검토끼리 갈리는 문항을 빼면 멀쩡한 문항을 잃는다."""
    c = _Client("answer=3\nreason=가", "answer=1\nreason=나")
    assert cv.review_vote(c, _q(), "C프로그래밍", votes=2) == (-1, "")


# --- 실행으로 가리기 ---------------------------------------------------------
def test_running_decides_when_the_output_matches_a_choice(monkeypatch):
    q = _q(code="int main(){}", options=[{"no": 1, "text": "10"},
                                         {"no": 2, "text": "20"}])
    monkeypatch.setattr(qv, "run_c", lambda *a, **k: {"ok": True, "out": "20",
                                                      "err": ""})
    assert cv.run_verdict(q, "gcc") == 2


def test_an_empty_output_decides_nothing(monkeypatch):
    """코드가 지문일 뿐인 문항(㉠㉡ 표시만 있는 것)은 아무것도 출력하지 않는다."""
    q = _q(code="int a = 1;")
    monkeypatch.setattr(qv, "run_c", lambda *a, **k: {"ok": True, "out": "  ",
                                                      "err": ""})
    assert cv.run_verdict(q, "gcc") == 0
    assert cv.run_verdict(q, None) == 0


def test_a_failed_build_decides_nothing(monkeypatch):
    monkeypatch.setattr(qv, "run_c", lambda *a, **k: {"ok": False, "out": "",
                                                      "err": "컴파일 오류"})
    assert cv.run_verdict(_q(code="int main(){"), "gcc") == 0


def test_the_compiler_output_is_read_as_utf8():
    """실측: gcc 의 UTF-8 경고문을 cp949 로 읽다 UnicodeDecodeError 로 죽었다.

    그것도 읽기 스레드 안에서 터져 검증이 조용히 실패했다.
    """
    import inspect
    src = inspect.getsource(qv.run_c)
    # 컴파일과 실행, 두 번의 바깥 명령 모두 인코딩을 못 박아야 한다
    assert src.count('errors="replace"') == 2


# --- 걸러낸 것 적어 두기 -----------------------------------------------------
def _bank(tmp_path, *qs):
    p = tmp_path / "v.json"
    p.write_text(json.dumps({"course": "C프로그래밍", "seq": 20165,
                             "name": "2016 변형", "questions": list(qs)},
                            ensure_ascii=False), encoding="utf-8")
    return p


def test_storing_a_reason_marks_the_question(tmp_path):
    p = _bank(tmp_path, _q(qid="a"), _q(qid="b"))
    assert cv.store_suspects(p, {"a": "검토에서는 3번이 답입니다"}) == 1
    got = json.loads(p.read_text(encoding="utf-8"))["questions"]
    assert got[0]["suspect"].startswith("검토에서는")
    assert "suspect" not in got[1]
    assert not list(tmp_path.glob("*.tmp"))        # 임시 파일이 남지 않는다


def test_storing_the_same_reason_twice_changes_nothing(tmp_path):
    p = _bank(tmp_path, _q(qid="a"))
    cv.store_suspects(p, {"a": "사유"})
    assert cv.store_suspects(p, {"a": "사유"}) == 0


def test_already_marked_questions_are_not_checked_again():
    bank = {"questions": [_q(qid="a"), _q(qid="b", suspect="어긋남")]}
    assert [q["qid"] for q in cv.to_check(bank)] == ["a"]
    assert len(cv.to_check(bank, recheck=True)) == 2


def test_only_variant_banks_are_looked_at(tmp_path):
    """기출의 정답은 학교 정답표에서 왔다 — 모델이 뒤집으면 안 된다."""
    (tmp_path / "C프로그래밍_기출2016-1.json").write_text("{}", encoding="utf-8")
    (tmp_path / "C프로그래밍_변형2016-1.json").write_text(
        json.dumps({"questions": []}), encoding="utf-8")
    got = [p.name for p, _b in cv.variant_banks(tmp_path)]
    assert got == ["C프로그래밍_변형2016-1.json"]


# --- 부정형이 뒤바뀐 변형 ----------------------------------------------------
# 실측: 원본 '~함수가 아닌 것은?' → 변형 '~함수로 가장 적절한 것은?' 인데 정답은
# 여전히 '성질이 다른 하나' 였다. 보기 구조를 두고 물음만 뒤집으면 이렇게 된다.
def test_a_negative_question_is_recognised():
    assert qv.is_negative("다음 중 옳지 않은 것은?")
    assert qv.is_negative("함수가 아닌 것은? (2점)")
    assert qv.is_negative("설명으로 틀린 것은?")
    assert not qv.is_negative("가장 적절한 것은?")
    assert not qv.is_negative("") and not qv.is_negative(None)


def test_a_flipped_negation_is_spotted():
    o = {"question": "다음 중 문자열 입출력 함수가 아닌 것은?"}
    v = {"question": "다음 중 문자를 하나 입력받는 함수로 적절한 것은?"}
    assert qv.negation_flip(o, v)
    assert not qv.negation_flip(o, {"question": "다음 중 옳지 않은 것은?"})
    assert not qv.negation_flip({"question": "옳은 것은?"}, v)


def test_the_origin_index_reads_only_the_real_exams(tmp_path):
    (tmp_path / "C프로그래밍_기출2016-1.json").write_text(json.dumps(
        {"questions": [{"qid": "2016-1-02", "question": "아닌 것은?"}]}),
        encoding="utf-8")
    (tmp_path / "C프로그래밍_변형2016-1.json").write_text(json.dumps(
        {"questions": [{"qid": "2016-1-02-v1", "question": "적절한 것은?"}]}),
        encoding="utf-8")
    got = cv.origin_index(tmp_path)
    assert list(got) == ["2016-1-02"]


# --- 과반으로 가린다 ---------------------------------------------------------
def test_a_majority_decides():
    """같은 문항에 3번·4번·3번이 나왔다 — 과반을 따른다."""
    c = _Client("answer=3\nreason=가", "answer=4\nreason=나", "answer=3\nreason=다")
    got, _why = cv.review_vote(c, _q(), "C프로그래밍", votes=3)
    assert got == 3


def test_no_majority_holds_the_judgement():
    c = _Client("answer=1\nreason=가", "answer=2\nreason=나", "answer=3\nreason=다")
    assert cv.review_vote(c, _q(), "C프로그래밍", votes=3) == (-1, "")


def test_unreadable_reviews_do_not_count():
    c = _Client("무슨 말인지 모르겠습니다", "answer=3\nreason=가")
    got, _why = cv.review_vote(c, _q(), "C프로그래밍", votes=2)
    assert got == 3


def test_every_review_failing_holds_the_judgement():
    c = _Client("엉뚱한 응답", "또 엉뚱한 응답")
    assert cv.review_vote(c, _q(), "C프로그래밍", votes=2) == (-1, "")


# --- 애초에 부정형을 잃지 않게 -----------------------------------------------
def test_the_generator_is_told_to_keep_the_negation():
    assert "부정형을 그대로 지켜라" in qv.VARIANT_PROMPT


# --- 값과 보기 번호를 헷갈릴 때 ----------------------------------------------
# 실측: 'A 는 몇 번 출력되는가?' 에서 프로그램은 24번 출력하고 24가 적힌 보기는
# 2번인데, 검토는 이유에 '총 24번' 이라 적고 answer 에는 3 을 적었다.
def _num_q(**over):
    d = _q(question="'A'는 몇 번 출력되는가?", answer_no=2,
           options=[{"no": 1, "text": "12"}, {"no": 2, "text": "24"},
                    {"no": 3, "text": "36"}, {"no": 4, "text": "48"}])
    d.update(over)
    return d


def test_a_review_that_contradicts_itself_is_not_trusted():
    why = "중첩 루프에서 3 * 4 * 2 = 24번 출력된다"
    assert not qv.review_is_consistent(_num_q(), 3, why)
    assert qv.review_verdict(_num_q(), 3, why) == ""    # 멀쩡한 문항을 지킨다


def test_a_review_that_agrees_with_its_reason_is_trusted():
    why = "모두 36번 출력된다"
    assert qv.review_is_consistent(_num_q(), 3, why)
    assert "3번" in qv.review_verdict(_num_q(), 3, why)


def test_the_check_only_applies_to_number_choices():
    """보기가 글이면 이유에서 값을 찾을 수 없다 — 그대로 믿는다."""
    assert qv.review_is_consistent(_q(), 3, "getchar 가 맞다")


def test_a_number_inside_a_bigger_number_does_not_count():
    q = _num_q(options=[{"no": 1, "text": "2"}, {"no": 2, "text": "24"}])
    assert qv.review_is_consistent(q, 1, "결과는 240 이다")


# --- 되돌리기 ---------------------------------------------------------------
def test_a_question_can_come_back(tmp_path):
    """검토가 흔들려 잘못 뺀 문항은 다시 화면으로 돌아와야 한다."""
    p = _bank(tmp_path, _q(qid="a", suspect="예전 사유"))
    assert cv.store_suspects(p, {}, clear=["a"]) == 1
    got = json.loads(p.read_text(encoding="utf-8"))["questions"]
    assert "suspect" not in got[0]


def test_clearing_something_that_is_not_marked_changes_nothing(tmp_path):
    p = _bank(tmp_path, _q(qid="a"))
    assert cv.store_suspects(p, {}, clear=["a"]) == 0


def test_a_run_confirmed_question_loses_its_warning(tmp_path):
    """실행이 정답을 확인했으면 '확인하지 못했습니다' 경고를 떼야 한다."""
    p = _bank(tmp_path, _q(qid="a"))
    assert cv.store_suspects(p, {}, confirm=["a"]) == 1
    got = json.loads(p.read_text(encoding="utf-8"))["questions"]
    assert got[0]["verified"] is True
