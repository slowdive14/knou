"""창이 작으면 퀴즈 화면의 위쪽 메뉴를 접는다 — 문제만 크게.

기본 창(1040×720)에서는 드롭다운·모드·도구·기출 원본이 줄줄이 꺾여 화면의
절반을 차지하고, 정작 문제는 두어 줄만 보였다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

from app.views.quiz_view import build_quiz_view, fold_head  # noqa: E402


class _Page:
    def __init__(self, width, height):
        self.width, self.height = width, height

    def update(self):
        pass


def _dir(tmp_path):
    d = tmp_path / "퀴즈"
    d.mkdir()
    q = {"qid": "2019-1-07", "source": "기출", "question": "옳은 것은?",
         "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
         "answer_no": 1, "answer_text": "가", "explanation": ""}
    (d / "20191.json").write_text(json.dumps(
        {"course": "C프로그래밍", "seq": 20191, "name": "2019 기출",
         "exam": True, "questions": [q]}, ensure_ascii=False),
        encoding="utf-8")
    return d


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _button(view, label):
    for b in _walk(view):
        if isinstance(b, ft.TextButton) and str(b.content) == label:
            return b
    raise AssertionError(f"[{label}] 단추가 없습니다")


def _parts(view):
    """(메뉴 묶음, 접힌 막대) — 화면 맨 위 두 칸."""
    return view.controls[0], view.controls[1]


def _menu_shown(view) -> bool:
    head, slim = _parts(view)
    assert head.visible != slim.visible, "메뉴와 막대 중 하나만 보여야 합니다"
    return head.visible


# --- 언제 접나 ---------------------------------------------------------------
def test_the_default_window_folds_the_menu():
    assert fold_head(1040, 720) is True


def test_a_large_window_keeps_the_menu():
    assert fold_head(1600, 900) is False


def test_a_short_window_folds_even_when_wide():
    """세로가 짧아도 메뉴가 문제를 밀어낸다."""
    assert fold_head(1600, 700) is True


def test_an_unknown_size_keeps_the_menu():
    assert fold_head(None, None) is False


# --- 화면 -------------------------------------------------------------------
def test_a_small_window_shows_only_the_slim_bar(tmp_path):
    v = build_quiz_view(_Page(1040, 720), quiz_dir=_dir(tmp_path))
    assert not _menu_shown(v)
    _head, slim = _parts(v)
    said = [str(t.value) for t in _walk(slim) if isinstance(t, ft.Text)]
    assert "0 / 1" in said                       # 얼마나 풀었는지는 남긴다


def test_the_bar_button_unfolds_the_menu(tmp_path):
    v = build_quiz_view(_Page(1040, 720), quiz_dir=_dir(tmp_path))
    _button(v, "메뉴 펼치기").on_click(None)
    assert _menu_shown(v)
    _button(v, "메뉴 접기").on_click(None)
    assert not _menu_shown(v)


def test_a_large_window_shows_the_menu(tmp_path):
    v = build_quiz_view(_Page(1600, 900), quiz_dir=_dir(tmp_path))
    assert _menu_shown(v)


def test_growing_the_window_unfolds_and_shrinking_folds(tmp_path):
    page = _Page(1040, 720)
    v = build_quiz_view(page, quiz_dir=_dir(tmp_path))
    page.width, page.height = 1600, 900
    page.on_resize(None)
    assert _menu_shown(v)
    page.width, page.height = 1000, 700
    page.on_resize(None)
    assert not _menu_shown(v)


def test_an_unfolded_menu_stays_while_the_window_stays_small(tmp_path):
    """사람이 펼쳐 둔 것을 창을 조금 움직였다고 다시 접으면 안 된다."""
    page = _Page(1040, 720)
    v = build_quiz_view(page, quiz_dir=_dir(tmp_path))
    _button(v, "메뉴 펼치기").on_click(None)
    page.width = 1000
    page.on_resize(None)
    assert _menu_shown(v)


def test_the_slim_bar_counts_answers(tmp_path):
    v = build_quiz_view(_Page(1040, 720), quiz_dir=_dir(tmp_path))
    opt = next(c for c in _walk(v) if isinstance(c, ft.Container)
               and getattr(c, "on_click", None)
               and any(isinstance(t, ft.Text) and t.value == "가"
                       for t in _walk(c)))
    opt.on_click(None)
    _head, slim = _parts(v)
    said = [str(t.value) for t in _walk(slim) if isinstance(t, ft.Text)]
    assert "1 / 1" in said
