"""exam_figure 단위테스트 — '아래 그림은 …' 인데 그림이 없던 자리.

기출은 시험지 PDF 를 AI 가 읽어 만들었다. 글은 잘 옮겨졌지만 그림은 남지
않아서, 그림을 봐야 풀리는 문항을 아예 풀 수가 없었다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import exam_figure as ef  # noqa: E402

pymupdf = pytest.importorskip("pymupdf")


# --- 문항 머리 읽기 ---------------------------------------------------------
def test_a_question_head_gives_its_number():
    assert ef.head_no("7. 직치 주소지정방식과 직접 주소지정방식을 …") == 7
    assert ef.head_no("21. 다음과 같은 연산을 …") == 21
    assert ef.head_no(" 3. 위의 프로그램은 …") == 3


def test_an_ordinary_line_is_not_a_question_head():
    assert ef.head_no("① 기억장치 주소 혹은 …") is None
    assert ef.head_no("컴퓨터구조, 데이터베이스설계및구현") is None
    assert ef.head_no("") is None


def test_a_shared_intro_gives_its_range():
    """여러 문항이 함께 쓰는 지문이다 — 그림을 그 문항 모두에 붙여야 한다."""
    assert ef.intro_range("※ (3～5) 다음 프로그램을 보고 물음에 답하시오.") == (3, 5)
    assert ef.intro_range("※ (14~16) 아래 그림은 처리장치의 블록도이다.") == (14, 16)
    assert ef.intro_range("※ (18-21) 다음 그림은 …") == (18, 21)


def test_a_backwards_range_is_refused():
    assert ef.intro_range("※ (9～3) 거꾸로 적힌 것") is None
    assert ef.intro_range("※ 다음 물음에 답하시오") is None


def test_the_range_covers_every_question_in_it():
    assert ef.covers(3, 5) == [3, 4, 5]
    assert ef.covers(7, 7) == [7]
    assert ef.covers(5, 3) == []


def test_an_option_line_is_told_apart():
    """그림은 보기 위에 있다 — 보기 줄을 알아야 아래쪽을 잘라낼 수 있다."""
    assert ef.is_option("① 입력 데이터, 출력 데이터")
    assert ef.is_option("  ④ 처리신호, 제어신호")
    assert not ef.is_option("11. 아래 그림은 …")


# --- 네모 합치기 ------------------------------------------------------------
def test_boxes_grow_to_cover_everything():
    box = ef.grow(None, (10, 20, 30, 40))
    box = ef.grow(box, (5, 25, 35, 38))
    assert box == (5, 20, 35, 40)


def test_a_zero_width_line_still_widens_the_box():
    """표는 두께 0 인 선으로 그려진다 — PyMuPDF 의 union 은 그것을 무시한다."""
    box = ef.grow(None, (51.0, 502.9, 51.0, 589.2))     # 세로선
    box = ef.grow(box, (51.0, 502.9, 314.5, 502.9))     # 가로선
    assert box == (51.0, 502.9, 314.5, 589.2)


def test_a_thin_underline_is_not_a_figure():
    assert not ef.big_enough((10, 10, 200, 12))          # 납작하다
    assert not ef.big_enough((10, 10, 25, 60))           # 좁다
    assert not ef.big_enough(None)
    assert ef.big_enough((10, 10, 200, 90))


# --- 문항 번호와 시험지 열쇠 -------------------------------------------------
def test_the_question_number_comes_from_the_qid():
    assert ef.q_no("2014-2-07") == 7
    assert ef.q_no("2016-2-35") == 35
    assert ef.q_no("") is None


def test_the_exam_key_is_read_from_the_header():
    assert ef.exam_key("2014학년도 2 학기 3 학년 3 교시") == (2014, 2)
    assert ef.exam_key("2016학년도  1 학기") == (2016, 1)
    assert ef.exam_key("컴퓨터구조, 데이터베이스설계및구현") is None


# --- 지면 읽기 --------------------------------------------------------------
def _sheet(path, *, two_columns=True, figure=True, text=True):
    """시험지 한 장을 흉내 낸다 — 문항 글 + 그림 상자.

    ⚠️ 한글은 PyMuPDF 의 내장 CJK 폰트(korea)로만 그려진다. 기본 폰트로 쓰면
       글자가 아예 들어가지 않아 '글줄 없는 PDF' 가 된다.
    """
    doc = pymupdf.open()
    page = doc.new_page(width=600, height=800)

    def put(x, y, t):
        page.insert_text((x, y), t, fontsize=10, fontname="korea")

    if text:
        put(40, 60, "1. 첫 번째 물음인가?")
        put(50, 80, "① 하나")
        put(40, 120, "※ (2~3) 아래 그림을 보고 답하시오.")
        if figure:
            page.draw_rect(pymupdf.Rect(60, 150, 260, 260))
        put(40, 300, "2. 두 번째 물음인가?")
        put(50, 320, "① 하나")
        put(40, 360, "3. 세 번째 물음인가?")
        put(50, 380, "① 하나")
        put(40, 420, "4. 네 번째 물음인가?")
        put(50, 440, "① 하나")
        put(40, 480, "5. 다섯 번째 물음인가?")
        put(50, 500, "① 하나")
        put(40, 540, "6. 여섯 번째 물음인가?")
        put(40, 30, "2014학년도 2 학기")
    if two_columns and text:
        for i in range(8):
            put(320, 60 + i * 40, f"{i + 10}. 오른쪽 물음인가?")
    doc.save(path)
    doc.close()
    return path


def test_the_lines_of_a_page_are_read(tmp_path):
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf"))
    lines = ef.page_lines(doc[0])
    doc.close()
    assert any("첫 번째 물음" in ln["text"] for ln in lines)


def test_two_columns_are_split(tmp_path):
    """단을 나누지 않으면 왼쪽 문항에 오른쪽 단의 표가 딸려 들어온다."""
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf"))
    cols = ef.split_columns(doc[0], ef.page_lines(doc[0]))
    doc.close()
    assert len(cols) == 2
    assert all(ln["x"] < 300 for ln in cols[0])


def test_a_single_column_page_is_left_whole(tmp_path):
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf", two_columns=False))
    cols = ef.split_columns(doc[0], ef.page_lines(doc[0]))
    doc.close()
    assert len(cols) == 1


def test_the_marks_come_out_in_order(tmp_path):
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf"))
    col = ef.split_columns(doc[0], ef.page_lines(doc[0]))[0]
    got = ef.marks(col)
    doc.close()
    kinds = [(m["kind"], m.get("no") or (m["lo"], m["hi"])) for m in got]
    assert kinds[0] == ("q", 1)
    assert ("intro", (2, 3)) in kinds


def test_a_shared_figure_reaches_every_question_of_the_range(tmp_path):
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf"))
    got = ef.page_figures(doc[0])
    doc.close()
    assert 2 in got and 3 in got
    assert got[2] == got[3]


def test_a_question_without_a_figure_gets_nothing(tmp_path):
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf"))
    got = ef.page_figures(doc[0])
    doc.close()
    assert 1 not in got and 5 not in got


def test_a_page_with_no_drawing_gives_no_figure(tmp_path):
    doc = pymupdf.open(_sheet(tmp_path / "s.pdf", figure=False))
    got = ef.page_figures(doc[0])
    doc.close()
    assert got == {}


# --- 시험지 한 벌 -----------------------------------------------------------
def test_a_text_sheet_is_usable(tmp_path):
    assert ef.has_text_layer(_sheet(tmp_path / "s.pdf"))


def test_a_sheet_without_a_text_layer_is_refused(tmp_path):
    """한글 배포용 문서를 '인쇄' 로 변환하면 글자까지 벡터가 된다."""
    assert not ef.has_text_layer(_sheet(tmp_path / "s.pdf", text=False))
    assert not ef.has_text_layer(tmp_path / "없다.pdf")


def test_the_sheet_tells_its_year_and_term(tmp_path):
    assert ef.pdf_key(_sheet(tmp_path / "s.pdf")) == (2014, 2)
    assert ef.pdf_key(tmp_path / "없다.pdf") is None


def test_the_figures_of_a_sheet_carry_their_page(tmp_path):
    got = ef.pdf_figures(_sheet(tmp_path / "s.pdf"))
    assert 2 in got
    page_no, box = got[2]
    assert page_no == 0
    assert ef.big_enough(box)


def test_rendering_gives_a_png(tmp_path):
    p = _sheet(tmp_path / "s.pdf")
    _page, box = ef.pdf_figures(p)[2]
    data = ef.render(p, 0, box)
    assert data[:8] == b"\x89PNG\r\n\x1a\n"


def test_rendering_a_missing_file_is_not_an_error(tmp_path):
    assert ef.render(tmp_path / "없다.pdf", 0, (1, 1, 50, 50)) == b""
    assert ef.render(tmp_path / "없다.pdf", 0, None) == b""


def test_sheets_are_found_by_the_course_name(tmp_path):
    _sheet(tmp_path / "238-컴퓨터구조-3학년.pdf")
    _sheet(tmp_path / "242-C프로그래밍-1학년.pdf")
    got = [p.name for p in ef.find_pdfs(tmp_path, "컴퓨터구조")]
    assert got == ["238-컴퓨터구조-3학년.pdf"]
    assert ef.find_pdfs(tmp_path / "없다", "컴퓨터구조") == []
