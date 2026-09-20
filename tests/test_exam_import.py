"""기출 더 가져오기 — 안 담은 회차만, 못 읽는 자료는 이유를 남기고.

자료실에는 기출이 20건 있지만 PDF 첨부는 그 절반도 안 된다. 나머지는 HWP 인데
**배포용 문서**라 본문이 열리지 않는다(실측: '최신 버전의 한글이 필요합니다'
한 줄만 나온다). 무엇을 왜 건너뛰었는지 화면에 남겨야 한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import build_exam_bank as bx  # noqa: E402
import exam_bank as eb  # noqa: E402


def _row(key, pdf="a.pdf", ans="t.hwp", title=None):
    name = title or (f"{key[0]}-{key[1]} 기말시험" if key else "읽을 수 없는 제목")
    return {"key": key, "pdf": pdf, "ans": ans, "title": name, "post": {}}


# --- 이미 담은 회차인가 ------------------------------------------------------
def test_bank_exists_sees_a_bank_that_is_already_there(tmp_path):
    (tmp_path / eb.bank_filename("C프로그래밍", 2019, 1)).write_text(
        "{}", encoding="utf-8")
    assert bx.bank_exists(tmp_path, 2019, 1)
    assert not bx.bank_exists(tmp_path, 2018, 1)


# --- 무엇을 가져올 것인가 ----------------------------------------------------
def test_an_already_imported_round_is_skipped(tmp_path):
    """버튼을 다시 눌러도 이미 담은 회차를 다시 만들지 않는다."""
    (tmp_path / eb.bank_filename("C프로그래밍", 2019, 1)).write_text(
        "{}", encoding="utf-8")
    todo, skip = bx.plan_imports([_row((2019, 1)), _row((2018, 1))], tmp_path)
    assert [r["key"] for r in todo] == [(2018, 1)]
    assert any("이미 가져왔습니다" in why for _r, why in skip)


def test_a_round_without_a_pdf_is_skipped(tmp_path):
    """HWP 는 배포용 문서라 본문이 안 열린다 — 이유를 남긴다."""
    todo, skip = bx.plan_imports([_row((2014, 1), pdf=None)], tmp_path)
    assert todo == []
    assert any("PDF 첨부가 없습니다" in why for _r, why in skip)


def test_a_round_without_an_answer_table_waits_for_permission(tmp_path):
    """정답 없이 외우면 헛공부다 — 사용자가 고를 때만 담는다."""
    rows = [_row((2011, 1), ans=None)]
    todo, skip = bx.plan_imports(rows, tmp_path)
    assert todo == [] and any("정답표가 없습니다" in w for _r, w in skip)
    todo, _skip = bx.plan_imports(rows, tmp_path, want_all=True)
    assert [r["key"] for r in todo] == [(2011, 1)]


def test_an_unreadable_title_is_skipped(tmp_path):
    todo, skip = bx.plan_imports([_row(None)], tmp_path)
    assert todo == []
    assert any("연도·학기를 못 읽었습니다" in why for _r, why in skip)


def test_one_year_can_be_asked_for(tmp_path):
    rows = [_row((2019, 1)), _row((2018, 1))]
    todo, _skip = bx.plan_imports(rows, tmp_path, year=2018)
    assert [r["key"] for r in todo] == [(2018, 1)]


def test_the_newest_round_comes_first(tmp_path):
    """최근 기출이 시험에 가깝다 — 먼저 담는다."""
    rows = [_row((2011, 1)), _row((2019, 1)), _row((2017, 0))]
    todo, _skip = bx.plan_imports(rows, tmp_path)
    assert [r["key"] for r in todo] == [(2019, 1), (2017, 0), (2011, 1)]


# --- 결과 문구 --------------------------------------------------------------
def test_the_summary_counts_what_was_made():
    got = bx.summary_text([{"ok": True, "n": 25, "scored": 25},
                           {"ok": False, "why": "PDF 없음"}])
    assert "1/2회차" in got and "25개" in got


def test_the_summary_says_when_there_was_nothing_to_do():
    assert "없습니다" in bx.summary_text([])


def test_the_screen_message_tells_what_happened():
    from app.views.quiz_view import import_done_text
    assert "2회차" in import_done_text(
        {"made": 2, "done": [{"ok": True, "n": 25}, {"ok": True, "n": 24}]})
    assert "없습니다" in import_done_text({"made": 0, "done": []})
    assert "없습니다" in import_done_text(
        {"made": 0, "done": [], "skip": [("2014", "PDF 없음")]})


def test_the_notice_says_nothing_is_submitted():
    """이수와 달리 읽기만 하는 작업이라는 점이 분명해야 한다."""
    from app.views.quiz_view import IMPORT_BODY
    assert "제출하지 않습니다" in IMPORT_BODY
    assert "이미 담은 회차는 건너뜁니다" in IMPORT_BODY


# --- 화면에 붙었는가 ---------------------------------------------------------
import flet as ft  # noqa: E402


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def test_the_quiz_screen_has_the_button(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=tmp_path)
    labels = [str(c.content) for c in _walk(v) if isinstance(c, ft.TextButton)]
    assert "기출 더 가져오기" in labels


def test_the_button_opens_a_dialog_with_both_choices(tmp_path):
    """정답표 없는 회차까지 담을지는 사용자가 고른다."""
    from app.views.quiz_view import build_quiz_view

    class _Page:
        def __init__(self):
            self.shown = []

        def show_dialog(self, dlg):
            self.shown.append(dlg)

        def pop_dialog(self):
            self.shown.pop()

        def update(self):
            pass

        def run_task(self, *a, **k):
            pass

    pg = _Page()
    v = build_quiz_view(page=pg, quiz_dir=tmp_path)
    btn = next(c for c in _walk(v) if isinstance(c, ft.TextButton)
               and str(c.content) == "기출 더 가져오기")
    btn.on_click(None)
    assert len(pg.shown) == 1
    labels = [str(getattr(a, "content", "")) for a in pg.shown[0].actions]
    assert labels == ["취소", "정답 없는 회차도", "정답표 있는 것만"]
