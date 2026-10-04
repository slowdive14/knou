"""퀴즈 화면의 '기출 원본' 줄 — 회차마다 시험지·정답표를 눌러 연다.

문항이 이상해 보이면 원래 지면과 정답표를 곧바로 대 볼 수 있어야 한다
(2015-2 컴퓨터구조는 다른 해 시험지로 만들어져 있었다).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

import exam_files as xf  # noqa: E402
import open_target  # noqa: E402
from app.views.quiz_view import (  # noqa: E402
    MINT_BG, answer_tip, bank_term, build_quiz_view, sheet_tip)

COURSE = "컴퓨터구조"


def _bank(d, year, term):
    (d / f"{COURSE}_기출{year}-{term}.json").write_text(json.dumps(
        {"course": COURSE, "seq": year * 10 + term,
         "name": f"{year}학년도 {term}학기 기말시험",
         "exam": {"year": year, "term": term, "kind": "기말시험"},
         "questions": [{"qid": f"{year}-{term}-1", "source": "기출",
                        "question": "옳은 것은?",
                        "options": [{"no": 1, "text": "가"},
                                    {"no": 2, "text": "나"}],
                        "answer_no": 1}]},
        ensure_ascii=False), encoding="utf-8")


def _quiz(tmp_path):
    d = tmp_path / "퀴즈"
    d.mkdir()
    _bank(d, 2015, 2)
    return d


def _terms(tmp_path):
    hwp = tmp_path / "2015. 2학기 기말시험 정답표.hwp"
    return [
        {"key": (2014, 2), "label": "2014-2", "sheets": [],
         "answer": {"key": (2014, 2), "file": tmp_path / "2014.hwp",
                    "pages": []}},
        {"key": (2015, 2), "label": "2015-2",
         "sheets": [tmp_path / "240b-컴퓨터구조.pdf"],
         "answer": {"key": (2015, 2), "file": hwp, "pages": []}},
        {"key": (2016, 2), "label": "2016-2",
         "sheets": [tmp_path / "239-컴퓨터구조.pdf"], "answer": None}]


def _view(tmp_path, monkeypatch, opened=None):
    monkeypatch.setattr(xf, "course_terms", lambda _w, _c: _terms(tmp_path))

    def fake_open(path, prefer_obsidian=True):
        if opened is not None:
            opened.append(Path(path))
        return {"ok": True, "how": "external", "path": str(path)}
    monkeypatch.setattr(open_target, "open_path", fake_open)
    return build_quiz_view(quiz_dir=_quiz(tmp_path), exam_dir=tmp_path)


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _texts(view) -> list:
    return [str(t.value or "") for t in _walk(view) if isinstance(t, ft.Text)]


def _group(view, label):
    """회차 한 묶음 — '2015-2' 글자와 단추 둘."""
    for c in _walk(view):
        if isinstance(c, ft.Container) and isinstance(c.content, ft.Row):
            heads = [k for k in c.content.controls if isinstance(k, ft.Text)]
            if heads and heads[0].value == label:
                return c
    raise AssertionError(f"'{label}' 회차가 없습니다")


def _button(view, label, text):
    for c in _walk(_group(view, label)):
        if isinstance(c, ft.Container) and isinstance(c.content, ft.Row) \
                and any(isinstance(k, ft.Text) and k.value == text
                        for k in c.content.controls):
            return c
    raise AssertionError(f"{label} [{text}] 단추가 없습니다")


# --- 줄 ---------------------------------------------------------------------
def test_every_term_of_the_course_is_listed(tmp_path, monkeypatch):
    v = _view(tmp_path, monkeypatch)
    said = _texts(v)
    assert "기출 원본" in said
    assert [t for t in said if t in ("2014-2", "2015-2", "2016-2")] == \
        ["2014-2", "2015-2", "2016-2"]


def test_the_term_being_solved_is_colored(tmp_path, monkeypatch):
    v = _view(tmp_path, monkeypatch)
    assert _group(v, "2015-2").bgcolor == MINT_BG
    assert _group(v, "2014-2").bgcolor is None


def test_without_an_exam_folder_there_is_no_row(tmp_path):
    v = build_quiz_view(quiz_dir=_quiz(tmp_path))
    assert "기출 원본" not in _texts(v)


# --- 누르면 열린다 -----------------------------------------------------------
def test_pressing_the_sheet_opens_that_file(tmp_path, monkeypatch):
    opened = []
    v = _view(tmp_path, monkeypatch, opened)
    _button(v, "2015-2", "시험지").on_click(None)
    assert opened == [tmp_path / "240b-컴퓨터구조.pdf"]
    assert any("2015-2 시험지를 열었습니다" in t for t in _texts(v))


def test_pressing_the_answers_opens_the_answer_file(tmp_path, monkeypatch):
    opened = []
    v = _view(tmp_path, monkeypatch, opened)
    _button(v, "2015-2", "정답표").on_click(None)
    assert opened == [tmp_path / "2015. 2학기 기말시험 정답표.hwp"]
    assert any("'컴퓨터구조' 줄을 찾으세요" in t for t in _texts(v))


def test_a_pdf_answer_sheet_opens_the_cut_page(tmp_path, monkeypatch):
    opened = []
    v = _view(tmp_path, monkeypatch, opened)
    cut = tmp_path / "_발췌" / "컴퓨터구조_2015-2_정답.pdf"
    monkeypatch.setattr(xf, "answer_target", lambda _s, _c: cut)
    _button(v, "2015-2", "정답표").on_click(None)
    assert opened == [cut]


def test_a_missing_sheet_cannot_be_pressed(tmp_path, monkeypatch):
    v = _view(tmp_path, monkeypatch)
    b = _button(v, "2014-2", "시험지")
    assert b.on_click is None
    assert "index_exam_files.py" in str(b.tooltip)


def test_a_missing_answer_cannot_be_pressed(tmp_path, monkeypatch):
    v = _view(tmp_path, monkeypatch)
    assert _button(v, "2016-2", "정답표").on_click is None


def test_a_file_that_will_not_open_says_so(tmp_path, monkeypatch):
    v = _view(tmp_path, monkeypatch)
    monkeypatch.setattr(open_target, "open_path", lambda _p, **_k: {
        "ok": False, "how": "none", "error": "파일이 없습니다"})
    _button(v, "2016-2", "시험지").on_click(None)
    assert any("열지 못했습니다: 파일이 없습니다" in t for t in _texts(v))


# --- 조각들 -----------------------------------------------------------------
def test_an_exam_bank_knows_its_term():
    assert bank_term({"exam": {"year": 2015, "term": 2}}) == (2015, 2)
    assert bank_term({"seq": 3}) is None


def test_the_sheet_tip_names_the_file():
    t = {"sheets": [Path("a/240b-컴퓨터구조.pdf"), Path("b.pdf")]}
    assert sheet_tip(t) == "240b-컴퓨터구조.pdf (같은 회차 파일 1개 더)"


def test_the_answer_tip_says_how_it_opens():
    whole = {"answer": {"file": Path("2015.hwp"), "pages": [], "many": True}}
    assert answer_tip(whole, COURSE) == \
        "2015.hwp · 여러 회차가 든 파일 — 통째로 열립니다('컴퓨터구조' 줄을 찾으세요)"
    cut = {"answer": {"file": Path("2020.pdf"), "pages": [3]}}
    assert answer_tip(cut, COURSE) == \
        "2020.pdf — 컴퓨터구조 줄이 있는 쪽만 잘라 엽니다"
