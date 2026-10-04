"""기출 원본 — 회차마다 시험지와 정답표 파일을 짝짓는다.

파일 이름으로는 회차를 알 수 없다(2015-2 와 2017-2 컴퓨터구조 시험지가 같은
이름이었다). 정답표는 한 파일에 여러 회차가 들 수 있어, 회차 구간 안에서만
과목 줄을 찾아야 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import fitz  # noqa: E402
import pytest  # noqa: E402

import exam_bank as eb  # noqa: E402
import exam_figure as ef  # noqa: E402
import exam_files as xf  # noqa: E402


# --- 회차 머리줄 -------------------------------------------------------------
def test_a_header_line_names_its_term():
    assert xf.section_key("2015학년도 2학기 기말시험 정답표(전학년)") == (2015, 2)
    assert xf.section_key("2018학년도 1 학기 기말시험 정답표(1,2학년)") == (2018, 1)


def test_a_title_spanning_years_is_not_a_term():
    """'2014~2020 모음' 같은 묶음 제목에서 구간을 열면 첫 해에 다 몰린다."""
    assert xf.section_key("2014학년도 1학기 ~ 2020학년도 2학기 정답 모음") is None


def test_ordinary_lines_are_not_headers():
    assert xf.section_key("컴퓨터구조") is None
    assert xf.section_key("41424") is None
    assert xf.section_key("") is None


# --- 구간 나누기 -------------------------------------------------------------
YEARS = ["2014~2016 정답 모음",
         "2014학년도 2학기 기말시험 정답표", "3", "컴퓨터구조", "11111", "1",
         "2015학년도 2학기 기말시험 정답표", "3", "컴퓨터구조", "22222", "1",
         "2015학년도 2학기 기말시험 정답표",            # 쪽마다 되풀이되는 머리말
         "자료구조", "33333",
         "2016학년도 2학기 기말시험 정답표", "3", "컴퓨터구조", "44444"]


def test_a_file_with_several_years_is_cut_into_terms():
    secs = xf.split_sections(YEARS)
    assert [s["key"] for s in secs] == [(2014, 2), (2015, 2), (2016, 2)]


def test_a_repeated_page_header_stays_in_one_term():
    secs = {s["key"]: s for s in xf.split_sections(YEARS)}
    s = secs[(2015, 2)]
    assert "자료구조" in YEARS[s["start"]:s["end"]]


def test_each_term_finds_its_own_row():
    """파일 전체에서 첫 줄을 집으면 늘 2014 답이 나온다."""
    secs = {s["key"]: s for s in xf.split_sections(YEARS)}
    for key, want in (((2014, 2), 1), ((2015, 2), 2), ((2016, 2), 4)):
        s = secs[key]
        got = eb.answer_span(YEARS, "컴퓨터구조", 0, s["start"], s["end"])
        assert got[2] == [[want]] * 5


def test_a_file_without_headers_takes_its_name():
    secs = xf.split_sections(["컴퓨터구조", "12341"], fallback=(2017, 2))
    assert secs == [{"key": (2017, 2), "start": 0, "end": 2}]


def test_a_file_without_headers_or_name_has_no_terms():
    assert xf.split_sections(["컴퓨터구조", "12341"]) == []


def test_the_answer_span_stops_at_the_end_of_its_term():
    """구간 끝을 넘어 다음 해 답까지 이어 붙이면 안 된다."""
    lines = ["컴퓨터구조", "11", "2016학년도 2학기", "22"]
    assert eb.answer_span(lines, "컴퓨터구조", 0, 0, 2)[2] == [[1], [1]]


def test_the_old_answer_reader_still_takes_the_first_row():
    assert eb.parse_answer_lines(["자료구조", "12", "컴퓨터구조", "34"],
                                 "컴퓨터구조", 0) == [[3], [4]]


# --- 문구 -------------------------------------------------------------------
def test_the_term_label_is_short():
    assert xf.term_label((2015, 2)) == "2015-2"


def test_an_excerpt_says_which_page_was_opened():
    spot = {"key": (2020, 1), "pages": [11]}
    assert xf.answer_hint(spot, "컴퓨터구조") == \
        "2020학년도 1학기 정답표에서 컴퓨터구조 줄이 있는 12쪽만 열었습니다(노란 표시)"


def test_a_whole_file_says_what_to_look_for():
    spot = {"key": (2015, 2), "pages": []}
    assert xf.answer_hint(spot, "컴퓨터구조") == \
        "2015학년도 2학기 정답표를 열었습니다 '컴퓨터구조' 줄을 찾으세요(Ctrl+F)"


def test_a_whole_file_with_several_years_names_the_term():
    spot = {"key": (2015, 2), "pages": [], "many": True}
    assert "여러 해가 든 파일이니 이 학기 구간에서" in \
        xf.answer_hint(spot, "컴퓨터구조")


# --- 회차표 -----------------------------------------------------------------
def _pdf(path, text="시험지"):
    doc = fitz.open()
    doc.new_page().insert_text((50, 72), text, fontname="korea")
    doc.save(path)
    doc.close()
    return path


def test_a_remembered_sheet_is_not_read_again(tmp_path, monkeypatch):
    p = _pdf(tmp_path / "240-컴퓨터구조.pdf")
    xf.remember(tmp_path, p, (2015, 2))
    monkeypatch.setattr(ef, "has_text_layer", lambda _p: pytest.fail("읽었다"))
    assert xf.sheet_key(p, idx=xf.load_index(tmp_path), work=tmp_path) == \
        (2015, 2)


def test_a_changed_file_is_read_again(tmp_path, monkeypatch):
    """같은 이름에 다른 시험지가 덮이면 예전 회차를 믿으면 안 된다."""
    p = _pdf(tmp_path / "240-컴퓨터구조.pdf")
    xf.remember(tmp_path, p, (2015, 2))
    _pdf(p, "2017학년도 2학기 기말시험 문제지 — 더 긴 글")
    monkeypatch.setattr(ef, "has_text_layer", lambda _p: True)
    monkeypatch.setattr(ef, "pdf_key", lambda _p: (2017, 2))
    assert xf.sheet_key(p, idx=xf.load_index(tmp_path), work=tmp_path) == \
        (2017, 2)


def test_a_sheet_without_text_waits_for_the_ai(tmp_path, monkeypatch):
    p = _pdf(tmp_path / "248-컴퓨터구조.pdf")
    monkeypatch.setattr(ef, "has_text_layer", lambda _p: False)
    assert xf.sheet_key(p, client=None, idx={}, work=tmp_path) is None
    monkeypatch.setattr(ef, "ai_pdf_key", lambda _c, _p, _l=None: (2019, 2))
    idx = {}
    assert xf.sheet_key(p, client=object(), idx=idx, work=tmp_path) == (2019, 2)
    assert idx["sheets"]["248-컴퓨터구조.pdf"]["key"] == [2019, 2]


def test_a_failed_read_is_not_written_down(tmp_path, monkeypatch):
    """AI 가 잠깐 바빠 못 읽은 것을 '모른다' 로 굳히면 다시 묻지 않게 된다."""
    p = _pdf(tmp_path / "248-컴퓨터구조.pdf")
    monkeypatch.setattr(ef, "has_text_layer", lambda _p: False)
    monkeypatch.setattr(ef, "ai_pdf_key", lambda _c, _p, _l=None: None)
    idx = {}
    assert xf.sheet_key(p, client=object(), idx=idx, work=tmp_path) is None
    assert not (idx.get("sheets") or {})


def test_a_hand_made_pdf_tells_its_term_by_name(tmp_path, monkeypatch):
    d = tmp_path / xf.MANUAL_DIR
    d.mkdir()
    p = _pdf(d / "컴퓨터구조_2015-2.pdf")
    monkeypatch.setattr(ef, "has_text_layer", lambda _p: pytest.fail("읽었다"))
    assert xf.sheet_key(p, idx={}, work=tmp_path) == (2015, 2)


def test_sheet_files_group_by_term_and_save_what_they_read(tmp_path,
                                                           monkeypatch):
    _pdf(tmp_path / "238-컴퓨터구조.pdf")
    _pdf(tmp_path / "239-컴퓨터구조.pdf")
    _pdf(tmp_path / "242-자료구조.pdf")
    keys = {"238-컴퓨터구조.pdf": (2014, 2), "239-컴퓨터구조.pdf": (2016, 2)}
    monkeypatch.setattr(ef, "has_text_layer", lambda _p: True)
    monkeypatch.setattr(ef, "pdf_key", lambda p: keys.get(Path(p).name))
    got = xf.sheet_files(tmp_path, "컴퓨터구조")
    assert {k: [p.name for p in v] for k, v in got.items()} == {
        (2014, 2): ["238-컴퓨터구조.pdf"], (2016, 2): ["239-컴퓨터구조.pdf"]}
    saved = json.loads(xf.index_path(tmp_path).read_text(encoding="utf-8"))
    assert set(saved["sheets"]) == {"238-컴퓨터구조.pdf", "239-컴퓨터구조.pdf"}


# --- 정답표 속 과목 자리 -----------------------------------------------------
def _answers_pdf(path, pages):
    """쪽마다 줄 목록을 적은 정답표 PDF."""
    doc = fitz.open()
    for lines in pages:
        page = doc.new_page()
        for i, line in enumerate(lines):
            page.insert_text((50, 60 + 18 * i), line, fontname="korea")
    doc.save(path)
    doc.close()
    return path


def _answer_dir(tmp_path):
    d = tmp_path / xf.ANSWER_DIR / "모음"
    d.mkdir(parents=True)
    return d


def test_a_multi_year_pdf_points_each_term_at_its_own_page(tmp_path):
    d = _answer_dir(tmp_path)
    _answers_pdf(d / "정답 모음.pdf", [
        ["2014학년도 2학기 기말시험 정답표", "자료구조", "12341"],
        ["2015학년도 2학기 기말시험 정답표", "자료구조", "43214"],
        ["2015학년도 2학기 기말시험 정답표", "컴퓨터구조", "22222"]])
    spots = xf.answer_spots(tmp_path, "자료구조")
    assert spots[(2014, 2)]["pages"] == [0]
    assert spots[(2015, 2)]["pages"] == [1]
    assert spots[(2015, 2)]["many"] is True
    assert xf.answer_spots(tmp_path, "컴퓨터구조")[(2015, 2)]["pages"] == [2]


def test_a_term_split_by_grade_picks_the_file_with_the_course(tmp_path,
                                                              monkeypatch):
    """2018-1 은 1·2학년과 3·4학년 파일로 나뉘어 있었다."""
    d = _answer_dir(tmp_path)
    (d / "붙임1_2018. 1학기 정답표(1 2학년).hwp").write_bytes(b"x")
    (d / "붙임2_2018. 1학기 정답표(3 4학년).hwp").write_bytes(b"y")
    texts = {"붙임1_2018. 1학기 정답표(1 2학년).hwp":
             ["2018학년도 1학기 기말시험 정답표(1,2학년)", "C프로그래밍", "1234"],
             "붙임2_2018. 1학기 정답표(3 4학년).hwp":
             ["2018학년도 1학기 기말시험 정답표(3,4학년)", "컴퓨터구조", "4321"]}
    monkeypatch.setattr(eb, "hwp_text", lambda p: texts[Path(p).name])
    xf._doc_lines.cache_clear()
    got = xf.answer_spots(tmp_path, "컴퓨터구조")[(2018, 1)]
    assert got["file"].name.startswith("붙임2")
    assert got["pages"] == []                    # HWP 는 쪽을 모른다


def test_the_zip_itself_is_never_a_target(tmp_path):
    d = tmp_path / xf.ANSWER_DIR
    d.mkdir()
    (d / "기말시험 정답표(2014~2020).zip").write_bytes(b"PK")
    assert xf.answer_docs(tmp_path) == []


def test_an_excerpt_holds_only_the_course_page_and_marks_the_row(tmp_path):
    d = _answer_dir(tmp_path)
    src = _answers_pdf(d / "정답 모음.pdf", [
        ["2014학년도 2학기 기말시험 정답표", "자료구조", "12341"],
        ["2015학년도 2학기 기말시험 정답표", "자료구조", "43214"]])
    spot = xf.answer_spots(tmp_path, "자료구조")[(2015, 2)]
    out = xf.answer_target(spot, "자료구조")
    assert out != src and out.parent.name == xf.EXCERPT_DIR
    doc = fitz.open(out)
    try:
        assert doc.page_count == 1
        assert "2015학년도" in doc[0].get_text()
        assert [a.type[1] for a in doc[0].annots()] == ["Highlight"]
    finally:
        doc.close()


def test_the_excerpts_are_not_mistaken_for_answer_sheets(tmp_path):
    d = _answer_dir(tmp_path)
    _answers_pdf(d / "정답 모음.pdf", [
        ["2015학년도 2학기 기말시험 정답표", "자료구조", "43214"]])
    xf.answer_target(xf.answer_spots(tmp_path, "자료구조")[(2015, 2)],
                     "자료구조")
    assert [p.name for p in xf.answer_docs(tmp_path)] == ["정답 모음.pdf"]


def test_a_hwp_answer_sheet_is_opened_whole(tmp_path):
    spot = {"key": (2015, 2), "file": tmp_path / "정답표.hwp", "pages": []}
    assert xf.answer_target(spot, "컴퓨터구조") == tmp_path / "정답표.hwp"


def test_course_terms_join_sheets_and_answers(tmp_path, monkeypatch):
    monkeypatch.setattr(xf, "sheet_files",
                        lambda _w, _c: {(2016, 2): [Path("239.pdf")]})
    monkeypatch.setattr(xf, "answer_spots",
                        lambda _w, _c: {(2015, 2): {"file": Path("a.hwp")},
                                        (2016, 2): {"file": Path("b.hwp")}})
    got = xf.course_terms(tmp_path, "컴퓨터구조")
    assert [(t["label"], bool(t["sheets"]), bool(t["answer"])) for t in got] \
        == [("2015-2", False, True), ("2016-2", True, True)]
