"""fetch_exam_figures 단위테스트 — 어느 문항에 그림을 붙일지 가린다.

시험지의 상자를 그림으로 또 얹으면 같은 내용이 두 번 나온다. 글이 그림보다
읽기 좋으므로, 글로 이미 들어온 자료는 건드리지 않는다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fetch_exam_figures as fx  # noqa: E402
import quiz_intro as qi  # noqa: E402

GUIDE = "※ (14~16) 아래 그림은 처리장치의 블록도이다. 다음 물음에 답하시오."
WITH_CODE = ("※ (3~5) 다음 프로그램을 보고 물음에 답하시오.\n"
             "LOAD   A ;   AC ← M[A]  (a)\n"
             "SUB    B ;   AC ← AC - M[B]  (b)\n"
             "STORE  X ;   (     )  (c)")
LONG_GUIDE = ("※ (7~9) 아래 그림은 어느 순간의 기억장치와 PC, 레지스터를 "
              "나타내고 있다. PC의 현재 내용이 156이므로 이제 곧 156번지에 "
              "있는 컴퓨터 명령어를 수행하게 될 것이다.")


def _q(**over):
    d = {"qid": "2014-2-14", "question": "위 그림에서 ㈏와 ㈐는 무엇인가?",
         "intro": GUIDE, "options": [{"no": 1, "text": "가"}]}
    d.update(over)
    return d


# --- 자료가 이미 글로 들어왔는가 --------------------------------------------
def test_a_guide_line_alone_is_not_the_material():
    """'아래 그림은 …' 한 줄은 안내문일 뿐 — 그림이 있어야 풀린다."""
    assert not fx.written_out(GUIDE)


def test_a_long_guide_in_one_line_is_still_a_guide():
    """줄바꿈 없이 길게 적힌 안내문도 자료가 아니다."""
    assert not fx.written_out(LONG_GUIDE)


def test_a_program_under_the_guide_is_the_material():
    assert fx.written_out(WITH_CODE)


def test_a_short_second_line_is_not_the_material():
    assert not fx.written_out("다음 그림은 제어단어의 각 필드를 나타내고 있다.\n"
                              "물음에 답하시오.")


def test_an_empty_text_holds_nothing():
    assert not fx.written_out("")
    assert not fx.written_out(None)


# --- 붙일 문항 가리기 -------------------------------------------------------
def test_a_figure_question_wants_one():
    assert fx.wants_figure(_q())


def test_a_question_with_the_code_already_written_does_not():
    """C프로그래밍 기출은 20문항이 모두 이런 경우였다."""
    assert not fx.wants_figure(_q(code="int main(void){ return 0; }"))


def test_a_question_whose_intro_holds_the_material_does_not():
    assert not fx.wants_figure(_q(intro=WITH_CODE))


def test_a_question_that_carries_the_material_in_its_own_stem_does_not():
    """물음 안에 T₀ : MAR ← IR(adrs) 가 적혀 있으면 그림은 겹친다."""
    assert not fx.wants_figure(_q(
        intro="",
        question="다음과 같은 일련의 마이크로연산은 무엇을 수행하는 것인가?\n"
                 "T₀ : MAR ← IR(adrs)\nT₁ : MBR ← M[MAR]"))


def test_a_question_that_already_has_a_figure_is_left_alone():
    assert not fx.wants_figure(_q(intro_image="이미.png"))


def test_force_reaches_a_question_that_already_has_one():
    assert fx.wants_figure(_q(intro_image="이미.png"), force=True)


def test_force_still_respects_the_written_material():
    """다시 붙이라고 해도 글로 있는 자료를 겹쳐 놓지는 않는다."""
    assert not fx.wants_figure(_q(intro=WITH_CODE, intro_image="이미.png"),
                               force=True)


# --- 은행 고르기 ------------------------------------------------------------
def _bank_dir(tmp_path):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / "a.json").write_text(json.dumps(
        {"course": "컴퓨터구조", "seq": 20142, "name": "2014학년도 2학기 기말시험",
         "exam": {"year": 2014, "term": 2}, "questions": [_q()]},
        ensure_ascii=False), encoding="utf-8")
    (d / "b.json").write_text(json.dumps(
        {"course": "자료구조", "seq": 8, "name": "8강",
         "questions": [_q(qid="q1")]}, ensure_ascii=False), encoding="utf-8")
    return d


def test_only_exam_banks_are_touched(tmp_path):
    """강의 퀴즈는 LMS 에서 왔다 — 시험지에서 찾을 것이 없다."""
    got = fx.exam_banks(_bank_dir(tmp_path))
    assert [d["course"] for _p, d in got] == ["컴퓨터구조"]


def test_one_course_can_be_picked(tmp_path):
    assert fx.exam_banks(_bank_dir(tmp_path), "자료구조") == []


def test_the_bank_key_matches_the_sheet():
    assert fx.bank_key({"exam": {"year": 2014, "term": 2}}) == (2014, 2)
    assert fx.bank_key({}) == (0, 0)
    assert fx.bank_key({"exam": {"year": "몰라"}}) == (0, 0)


# --- 떼어내기 ---------------------------------------------------------------
def test_stripping_takes_every_figure_off():
    """판정 기준을 고쳤을 때 잘못 붙은 것을 걷어낸다."""
    bank = {"questions": [_q(intro_image="a.png"), _q(intro_image="b.png"),
                          _q()]}
    assert fx.strip_figures(bank) == 2
    assert all(not q.get(qi.INTRO_FIELD) for q in bank["questions"])


def test_stripping_an_empty_bank_is_not_an_error():
    assert fx.strip_figures({}) == 0


# --- 어느 길로 읽을까 -------------------------------------------------------
# 글줄이 있으면 좌표로, 없으면 지면을 보여 주고 묻는다.
def test_a_text_sheet_is_read_by_its_coordinates(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(fx.ef, "pdf_figures", lambda p: called.setdefault(
        "text", True) or {7: (0, (1, 1, 50, 50))})
    monkeypatch.setattr(fx.ef, "ai_pdf_figures",
                        lambda *a, **k: called.setdefault("ai", True) or {})
    got = fx.figures_of(tmp_path / "s.pdf", "text")
    assert got and "text" in called and "ai" not in called


def test_a_sheet_without_text_is_shown_to_the_model(monkeypatch, tmp_path):
    called = {}
    monkeypatch.setattr(fx.ef, "pdf_figures",
                        lambda p: called.setdefault("text", True) or {})
    monkeypatch.setattr(fx.ef, "ai_pdf_figures", lambda *a, **k: (
        called.setdefault("ai", True) or {7: (0, (1, 1, 50, 50))}))
    got = fx.figures_of(tmp_path / "s.pdf", "ai", client=object())
    assert got and "ai" in called and "text" not in called


# --- 한글 시험지 바꾸기 -----------------------------------------------------
# 자료실에서 받은 시험지는 한글 문서인 경우가 많다.
def test_a_hwp_without_a_pdf_is_converted(tmp_path, monkeypatch):
    (tmp_path / "240-컴퓨터구조-3학년.hwp").write_bytes(b"x")
    made = []
    monkeypatch.setattr("hwp_convert.hwp_to_pdf", lambda s, o, **k: (
        made.append(Path(o).name) or {"ok": True, "path": str(o)}))
    assert fx.convert_hwp(tmp_path, "컴퓨터구조") == 1
    assert made == ["240-컴퓨터구조-3학년_한글.pdf"]


def test_the_converted_name_never_overwrites_an_existing_pdf(tmp_path,
                                                             monkeypatch):
    """게시글 번호가 같은데 학년도가 다른 시험지가 실제로 있었다."""
    (tmp_path / "240-컴퓨터구조-3학년.hwp").write_bytes(b"x")
    (tmp_path / "240-컴퓨터구조-3학년.pdf").write_bytes(b"OLD")
    monkeypatch.setattr("hwp_convert.hwp_to_pdf",
                        lambda s, o, **k: {"ok": True, "path": str(o)})
    fx.convert_hwp(tmp_path, "컴퓨터구조")
    assert (tmp_path / "240-컴퓨터구조-3학년.pdf").read_bytes() == b"OLD"


def test_a_hwp_already_converted_is_left_alone(tmp_path, monkeypatch):
    (tmp_path / "a-컴퓨터구조.hwp").write_bytes(b"x")
    (tmp_path / "a-컴퓨터구조_한글.pdf").write_bytes(b"OLD")
    monkeypatch.setattr("hwp_convert.hwp_to_pdf",
                        lambda s, o, **k: {"ok": True, "path": str(o)})
    assert fx.convert_hwp(tmp_path, "컴퓨터구조") == 0


def test_another_courses_hwp_is_not_touched(tmp_path, monkeypatch):
    (tmp_path / "b-자료구조.hwp").write_bytes(b"x")
    monkeypatch.setattr("hwp_convert.hwp_to_pdf",
                        lambda s, o, **k: {"ok": True, "path": str(o)})
    assert fx.convert_hwp(tmp_path, "컴퓨터구조") == 0


def test_a_failed_conversion_is_told_not_counted(tmp_path, monkeypatch):
    (tmp_path / "c-컴퓨터구조.hwp").write_bytes(b"x")
    monkeypatch.setattr("hwp_convert.hwp_to_pdf",
                        lambda s, o, **k: {"ok": False, "why": "한글이 없습니다"})
    said = []
    assert fx.convert_hwp(tmp_path, "컴퓨터구조", said.append) == 0
    assert any("한글이 없습니다" in m for m in said)


# --- 코드와 그림이 함께 있는 문항 ------------------------------------------
# 2018-2-60: 힙 그림 + 삽입 함수. 코드만 글로 옮겨지고 그림이 빠져 풀 수 없었다.
HEAP_Q = {"qid": "2018-2-60", "code": "int insertHeap(...) {}",
          "question": "아래 그림은 최소 힙에 새 노드를 삽입하기 위해 ..."}


def test_a_coded_question_gets_the_picture_beside_its_code():
    assert fx.wants_figure(HEAP_Q, kind="figure")


def test_a_coded_question_never_gets_its_code_box_again():
    assert not fx.wants_figure(HEAP_Q, kind="code")
    assert not fx.wants_figure(HEAP_Q)               # 글줄 시험지는 가리지 못한다


def test_a_coded_question_without_a_picture_word_is_left_alone():
    q = {"qid": "2016-2-57", "code": "printf(...)",
         "question": "다음 10과 3.14를 출력하기 위해 [가]와 [나]에 알맞은 것은?"}
    assert not fx.wants_figure(q, kind="figure")


def test_the_picture_wins_over_the_code_box_of_the_same_question(monkeypatch):
    monkeypatch.setattr(fx.ef, "ai_page_figures", lambda *a, **k: [
        {"nos": [60], "box": (0, 0, 9, 9), "kind": "code"},
        {"nos": [60], "box": (1, 1, 8, 8), "kind": "figure"}])

    class _Doc:
        page_count = 1

        def __getitem__(self, i):
            return type("P", (), {"rect": type("R", (), {"width": 1,
                                                         "height": 1})()})()

        def close(self):
            pass

    monkeypatch.setattr(fx.ef, "_fitz", lambda: type(
        "F", (), {"open": staticmethod(lambda p: _Doc())}))
    got = fx.ef.ai_pdf_figures(object(), __file__)
    assert got[60] == (0, (1, 1, 8, 8), "figure")


def test_an_expression_already_written_out_is_not_pictured_again():
    """'후위 표기식'·'수식으로 표현' 의 '표' 를 그림 표시로 읽었다."""
    for text in ("다음 수식을 후위 표기식으로 바르게 나타낸 것은?",
                 "아래의 문장을 수식으로 표현한 것으로 알맞은 것은?"):
        q = {"qid": "2014-2-05", "code": "A * (B + C) * D", "question": text}
        assert not fx.wants_figure(q, kind="figure")
    q = {"qid": "x", "code": "...", "question": "다음 표에서 (가)에 알맞은 것은?"}
    assert fx.wants_figure(q, kind="figure")


def test_a_question_pointing_at_a_picture_gets_it_even_if_sketched_in_text():
    q = {"qid": "2019-2-54",
         "question": "연결리스트 그림에 대한 설명으로 틀린 것은?\n\nhead ⟶ [30][ ] ⟶ [ ][ ] ⟶ [50][ ]"}
    assert fx.wants_figure(q)


# --- 글자로 흉내 낸 그림 ----------------------------------------------------
# 그림을 붙였는데 코드 칸에 '(N) / \ (R)' 같은 흉내가 남아 두 번 나왔다.
def test_a_drawn_tree_is_dropped_once_the_picture_is_attached():
    q = {"code": "(N)\n     /   \\n   (R)   (C)\n   /\n (K)"}
    fx.tidy_drawn(q)
    assert "code" not in q


def test_the_matrix_after_a_drawn_graph_stays():
    """2012-2-25: 그래프 흉내 뒤에 빈칸을 채울 인접행렬이 이어진다."""
    code = ("(T) ----> (G)\n  ^       |\n  |       v\n (N) <---- (Q)\n\n"
            "    T G N Q\n  T 0 1 1 0\n  G (       )")
    got = fx.strip_drawings(code)
    assert got.startswith("T G N Q")
    assert "---->" not in got


def test_a_described_picture_is_dropped_but_the_program_stays():
    """2018-2-60: '<최소힙그림>(이미지 내용: 루트 5 …)' 뒤에 진짜 코드가 있다."""
    code = ("<최소힙그림>\n(이미지 내용: 루트 5, 왼쪽 15\n15의 자식 20)\n\n"
            "int insertHeap(HeapType *h, int item) {\n    int i;\n}")
    got = fx.strip_drawings(code)
    assert got.startswith("int insertHeap")
    assert "이미지 내용" not in got and "최소힙그림" not in got


def test_a_program_with_slashes_is_not_taken_for_a_drawing():
    assert not fx.drawn("x = a / b;\nprintf(\"%d\", x);")


def test_a_sketch_in_the_question_is_dropped_too():
    q = {"question": "연결리스트 그림에 대한 설명으로 틀린 것은?\n\n"
                     "head ⟶ [30][ ] ⟶ [ ][ ] ⟶ [50][ ]"}
    fx.tidy_drawn(q)
    assert q["question"] == "연결리스트 그림에 대한 설명으로 틀린 것은?"


def test_a_question_marked_without_figure_never_gets_one():
    """글 조각만 잘려 붙어 사람이 뗀 문항(2014-2-03)은 --force 로도 다시 안 붙는다."""
    q = {"qid": "2014-2-03", "question": "다음 그림 …", "no_figure": "Y"}
    assert not fx.wants_figure(q, force=True, kind="figure")
