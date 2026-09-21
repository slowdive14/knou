"""문항마다 붙는 풀이 표지 — 안 푼 문제와 여러 번 본 문제를 가른다.

머리말의 '맞힘 18 · 오답 4' 는 은행 전체 이야기라, 눈앞의 이 문항을 전에
풀어 봤는지는 알 수 없었다. 두 번째로 훑을 때 어디를 건너뛰어도 되는지
가리려면 문항마다 표지가 있어야 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

import quiz_progress as qp  # noqa: E402
from app.views.quiz_view import build_quiz_view  # noqa: E402


def _q(qid="2019-1-07", **over):
    d = {"qid": qid, "source": "기출", "question": "올바른 것은?",
         "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
         "answer_no": 1, "answer_text": "가", "explanation": ""}
    d.update(over)
    return d


def _dir(tmp_path, *questions, course="C프로그래밍", seq=20191):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / f"{seq}.json").write_text(json.dumps(
        {"course": course, "seq": seq, "name": str(seq), "exam": True,
         "questions": list(questions)}, ensure_ascii=False), encoding="utf-8")
    return d


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _texts(view) -> list:
    return [str(t.value or "") for t in _walk(view) if isinstance(t, ft.Text)]


def _chips(view) -> list:
    """풀이 표지 문구만 골라낸다."""
    return [t for t in _texts(view)
            if t in ("안 푼 문제", "채점 없음") or "풀어" in t]


def _chip_tip(view, text) -> str:
    """그 표지에 달린 설명(마우스를 올렸을 때)."""
    for c in _walk(view):
        if isinstance(c, ft.Container) and isinstance(c.content, ft.Text) \
                and str(c.content.value) == text:
            return str(c.tooltip or "")
    raise AssertionError(f"'{text}' 표지가 없습니다")


def _choose(view, n=0):
    opts = [c for c in _walk(view) if isinstance(c, ft.Container)
            and getattr(c, "on_click", None)]
    opts[n].on_click(None)


# --- 아직 안 푼 문제 --------------------------------------------------------
def test_a_fresh_question_is_marked_as_never_answered(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    assert _chips(v) == ["안 푼 문제"]
    assert _chip_tip(v, "안 푼 문제") == "아직 한 번도 풀지 않았습니다"


def test_every_question_carries_its_own_mark(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q("a"), _q("b"), _q("c")))
    assert _chips(v) == ["안 푼 문제"] * 3


# --- 풀면 그 자리에서 바뀐다 -------------------------------------------------
def test_answering_turns_the_mark_into_a_count(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _choose(v, 0)                       # 1번 보기 = 정답
    assert _chips(v) == ["한 번 풀어 맞힘"]


def test_a_wrong_answer_shows_up_in_the_mark(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _choose(v, 1)                       # 2번 보기 = 오답
    assert _chips(v) == ["한 번 풀어 틀림"]


def test_only_the_answered_question_changes(tmp_path):
    """한 문항을 풀었다고 옆 문항까지 푼 것으로 보이면 안 된다."""
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q("a"), _q("b")))
    _choose(v, 0)
    assert _chips(v) == ["한 번 풀어 맞힘", "안 푼 문제"]


# --- 앱을 껐다 켜도 남는다 ---------------------------------------------------
def test_the_mark_survives_a_restart(tmp_path):
    d = _dir(tmp_path, _q())
    _choose(build_quiz_view(quiz_dir=d), 0)
    again = build_quiz_view(quiz_dir=d)          # 화면을 다시 세운다
    assert _chips(again) == ["한 번 풀어 맞힘"]


def test_the_count_grows_over_several_sittings(tmp_path):
    """같은 문항을 세 번 풀면 '3번 풀어 2번 맞힘' 처럼 쌓여야 한다."""
    d = _dir(tmp_path, _q())
    for pick in (0, 1, 0):                       # 맞힘 · 틀림 · 맞힘
        _choose(build_quiz_view(quiz_dir=d), pick)
    v = build_quiz_view(quiz_dir=d)
    assert _chips(v) == ["3번 풀어 2번 맞힘"]
    assert "마지막으로 푼 날" in _chip_tip(v, "3번 풀어 2번 맞힘")


# --- 채점하지 않는 문항 ------------------------------------------------------
def test_a_question_without_an_answer_table_is_not_called_unanswered(tmp_path):
    """정답을 몰라 채점하지 않는 문항은 풀어도 기록이 쌓이지 않는다."""
    d = _dir(tmp_path, _q(answer_no=0, answer_text=""))
    v = build_quiz_view(quiz_dir=d)
    assert _chips(v) == ["채점 없음"]
    _choose(v, 0)
    assert _chips(v) == ["채점 없음"]        # 풀어도 '안 푼 문제' 로 돌아가지 않는다


# --- 모아보기 ---------------------------------------------------------------
def test_a_gathered_question_shows_the_count_from_its_own_bank(tmp_path):
    """모아보기는 여러 회차를 한 자리에 모은다 — 기록은 제 출처의 것이다."""
    d = tmp_path / "퀴즈"
    d.mkdir()
    for seq in (20191, 20192):
        (d / f"{seq}.json").write_text(json.dumps(
            {"course": "C프로그래밍", "seq": seq, "name": str(seq), "exam": True,
             "questions": [_q(f"q{seq}", lecture=3)]}, ensure_ascii=False),
            encoding="utf-8")
    _choose(build_quiz_view(quiz_dir=d), 0)      # 첫 회차의 문항만 푼다
    v = build_quiz_view(quiz_dir=d)
    picks = [p for p in _walk(v) if isinstance(p, ft.Dropdown)
             and p.label == "강 모아보기"]
    picks[0].value = "3"
    picks[0].on_select(None)
    assert sorted(_chips(v)) == ["안 푼 문제", "한 번 풀어 맞힘"]


# --- 순서와 표지가 어긋나지 않는다 -------------------------------------------
def test_the_marks_agree_with_the_headline(tmp_path):
    """머리말의 '아직 N' 과 '안 푼 문제' 표지 수가 같아야 한다."""
    d = _dir(tmp_path, _q("a"), _q("b"), _q("c"))
    v = build_quiz_view(quiz_dir=d)
    _choose(v, 0)
    head = [t for t in _texts(v) if "문항" in t and "맞힘" in t]
    assert head and "아직 2" in head[0]
    assert _chips(v).count("안 푼 문제") == 2


def test_the_mark_matches_the_stored_record(tmp_path):
    d = _dir(tmp_path, _q())
    _choose(build_quiz_view(quiz_dir=d), 1)
    rec = list(qp.load(qp.progress_path(d)).values())[0]
    assert qp.tries_text(rec) == "한 번 풀어 틀림"
