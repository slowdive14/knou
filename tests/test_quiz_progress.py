"""quiz_progress 단위테스트 — 틀린 것부터 다시 내기.

풀이 기록이 파일에 남아야 앱을 껐다 켜도 '무엇을 틀렸는지' 가 유지된다.
그 기록으로 출제 순서를 정하는 것이 반복 학습의 전부다.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quiz_progress as qp  # noqa: E402

NOW = datetime(2026, 9, 21, 10, 0, 0)


def _bank(seq=20191, course="C프로그래밍"):
    return {"course": course, "seq": seq}


def _q(qid):
    return {"qid": qid}


# --- 기록 키 ---------------------------------------------------------------
def test_key_separates_banks_with_the_same_question_number():
    """회차가 달라도 문항 번호는 겹친다 — 섞이면 남의 기록으로 공부하게 된다."""
    a = qp.record_key(_bank(20191), "2019-1-03")
    b = qp.record_key(_bank(20181), "2019-1-03")
    assert a != b


def test_key_accepts_a_plain_name():
    assert qp.record_key("C프로그래밍|8", "q1").endswith("|q1")


# --- 한 번 풀었을 때 -------------------------------------------------------
def test_mark_counts_a_correct_answer():
    r = qp.mark(None, True, NOW)
    assert (r["tries"], r["correct"], r["streak"]) == (1, 1, 1)
    assert r["last_ok"] is True and r["last"].startswith("2026-09-21")


def test_mark_resets_the_streak_on_a_miss():
    r = qp.mark({"tries": 3, "correct": 3, "streak": 3, "last": "", }, False, NOW)
    assert r["tries"] == 4 and r["correct"] == 3
    assert r["streak"] == 0 and r["last_ok"] is False


def test_mark_does_not_touch_the_old_record():
    src = qp.blank()
    qp.mark(src, True, NOW)
    assert src["tries"] == 0


# --- 다시 낼 때 ------------------------------------------------------------
def test_a_new_question_is_due_now():
    assert qp.is_due(qp.blank(), NOW) is True
    assert qp.due_at(qp.blank()) is None


def test_a_wrong_answer_comes_back_immediately():
    r = qp.mark(None, False, NOW)
    assert qp.is_due(r, NOW) is True


def test_intervals_grow_as_you_keep_getting_it_right():
    assert qp.interval_days(0) == 0
    assert qp.interval_days(1) == 1
    assert qp.interval_days(2) == 3
    assert qp.interval_days(5) == 30
    assert qp.interval_days(99) == 30       # 상한을 넘지 않는다


def test_a_correct_answer_waits_before_coming_back():
    r = qp.mark(None, True, NOW)            # streak 1 → 하루 뒤
    assert qp.is_due(r, NOW) is False
    assert qp.is_due(r, NOW + timedelta(hours=23)) is False
    assert qp.is_due(r, NOW + timedelta(days=1)) is True


def test_a_broken_timestamp_does_not_hide_a_question():
    """기록이 깨졌다고 문항이 영영 안 나오면 안 된다 — 지금 낸다."""
    assert qp.is_due({"tries": 1, "streak": 3, "last": "어제"}, NOW) is True


# --- 출제 순서 -------------------------------------------------------------
def test_groups_put_wrong_answers_first():
    wrong = qp.mark(None, False, NOW)
    fresh = qp.blank()
    right = qp.mark(None, True, NOW)
    assert qp.group_of(wrong, NOW) == qp.GROUP_WRONG
    assert qp.group_of(fresh, NOW) == qp.GROUP_NEW
    assert qp.group_of(right, NOW) == qp.GROUP_LATER
    assert qp.GROUP_WRONG < qp.GROUP_NEW < qp.GROUP_DUE < qp.GROUP_LATER


def test_pick_orders_wrong_then_new_then_review():
    b = _bank()
    qs = [_q("a"), _q("b"), _q("c")]
    prog = {
        qp.record_key(b, "a"): qp.mark(None, True, NOW),        # 나중에
        qp.record_key(b, "c"): qp.mark(None, False, NOW),       # 틀림 → 먼저
    }                                                           # b 는 새 문항
    assert [q["qid"] for q in qp.pick(qs, prog, b, "all", NOW)] == \
        ["c", "b", "a"]


def test_pick_wrong_mode_keeps_only_misses():
    b = _bank()
    qs = [_q("a"), _q("b")]
    prog = {qp.record_key(b, "a"): qp.mark(None, False, NOW),
            qp.record_key(b, "b"): qp.mark(None, True, NOW)}
    assert [q["qid"] for q in qp.pick(qs, prog, b, "wrong", NOW)] == ["a"]


def test_pick_due_mode_skips_what_is_still_fresh():
    b = _bank()
    qs = [_q("a"), _q("b"), _q("c")]
    prog = {qp.record_key(b, "a"): qp.mark(None, True, NOW),    # 아직 이르다
            qp.record_key(b, "b"): qp.mark(None, False, NOW)}   # 틀림
    got = [q["qid"] for q in qp.pick(qs, prog, b, "due", NOW)]
    assert got == ["b", "c"]                # c 는 아직 안 푼 것


def test_pick_due_mode_brings_it_back_after_the_interval():
    b = _bank()
    prog = {qp.record_key(b, "a"): qp.mark(None, True, NOW)}
    later = NOW + timedelta(days=2)
    assert [q["qid"] for q in qp.pick([_q("a")], prog, b, "due", later)] == ["a"]


def test_pick_all_mode_keeps_every_question():
    b = _bank()
    qs = [_q("a"), _q("b")]
    prog = {qp.record_key(b, "a"): qp.mark(None, True, NOW)}
    assert len(qp.pick(qs, prog, b, "all", NOW)) == 2


def test_pick_survives_an_empty_bank():
    assert qp.pick([], {}, _bank(), "all", NOW) == []
    assert qp.pick(None, None, _bank(), "wrong", NOW) == []


# --- 현황 문구 -------------------------------------------------------------
def test_stats_count_what_matters():
    b = _bank()
    qs = [_q("a"), _q("b"), _q("c")]
    prog = {qp.record_key(b, "a"): qp.mark(None, True, NOW),
            qp.record_key(b, "b"): qp.mark(None, False, NOW)}
    s = qp.bank_stats(qs, prog, b, NOW)
    assert s["total"] == 3 and s["seen"] == 2
    assert s["solved"] == 1 and s["wrong"] == 1
    assert s["due"] == 2                    # 틀린 것 + 안 푼 것


def test_stats_text_reads_naturally():
    t = qp.stats_text({"total": 25, "seen": 21, "solved": 18, "wrong": 3})
    assert "25문항" in t and "맞힘 18" in t and "오답 3" in t and "아직 4" in t


def test_stats_text_is_quiet_when_there_is_nothing():
    assert qp.stats_text({"total": 0}) == ""
    assert qp.stats_text(None) == ""


def test_stats_text_omits_zero_counts():
    t = qp.stats_text({"total": 5, "seen": 5, "solved": 5, "wrong": 0})
    assert "오답" not in t and "아직" not in t


# --- 저장 ------------------------------------------------------------------
def test_save_and_load_round_trip(tmp_path):
    p = qp.progress_path(tmp_path)
    prog = {"C프로그래밍|20191|q1": qp.mark(None, True, NOW)}
    qp.save(p, prog)
    assert qp.load(p) == prog


def test_load_is_forgiving(tmp_path):
    """기록이 깨졌다고 퀴즈를 못 풀면 안 된다 — 빈 기록으로 시작한다."""
    assert qp.load(tmp_path / "없음.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{망가진", encoding="utf-8")
    assert qp.load(bad) == {}
    arr = tmp_path / "arr.json"
    arr.write_text("[1,2]", encoding="utf-8")
    assert qp.load(arr) == {}


def test_save_leaves_no_half_written_file(tmp_path):
    """사람이 쌓은 기록이라 반쪽짜리가 남으면 되돌릴 수 없다."""
    p = qp.progress_path(tmp_path)
    qp.save(p, {"a": qp.blank()})
    qp.save(p, {"b": qp.blank()})
    assert qp.load(p) == {"b": qp.blank()}
    assert not list(tmp_path.glob("*.tmp"))      # 임시 파일이 남지 않는다


def test_save_creates_the_folder(tmp_path):
    p = qp.progress_path(tmp_path / "없던폴더")
    qp.save(p, {"a": qp.blank()})
    assert p.exists()


# --- 화면과 이어 붙였을 때 (앱을 껐다 켜도 기록이 남는가) -------------------
import json  # noqa: E402

import flet as ft  # noqa: E402


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _quiz_dir(tmp_path, n=3):
    d = tmp_path / "퀴즈"
    d.mkdir()
    qs = [{"qid": f"q{i}", "source": "기출", "question": f"문항 {i}",
           "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
           "answer_no": 1, "answer_text": "가"} for i in range(1, n + 1)]
    (d / "b.json").write_text(json.dumps(
        {"course": "C프로그래밍", "seq": 20191, "name": "2019",
         "exam": {"year": 2019, "term": 1}, "questions": qs},
        ensure_ascii=False), encoding="utf-8")
    return d


def _options(view):
    """보기 버튼(누르면 답이 골라지는 것)."""
    return [c for c in _walk(view)
            if isinstance(c, ft.Container) and c.on_click is not None
            and isinstance(c.content, ft.Row)]


def _mode_btn(view, label):
    return next(c for c in _walk(view)
                if isinstance(c, ft.OutlinedButton) and c.content == label)


def test_answering_is_written_to_disk(tmp_path):
    """앱을 껐다 켜도 무엇을 틀렸는지 남아야 한다."""
    from app.views.quiz_view import build_quiz_view
    d = _quiz_dir(tmp_path)
    view = build_quiz_view(quiz_dir=d)
    _options(view)[1].on_click(None)          # 첫 문항에서 2번(오답)을 고른다
    saved = qp.load(qp.progress_path(d))
    assert saved, "기록이 저장되지 않았다"
    rec = next(iter(saved.values()))
    assert rec["tries"] == 1 and rec["last_ok"] is False


def test_a_missed_question_comes_back_first(tmp_path):
    """다시 열면 틀린 문항이 맨 앞에 온다 — 반복 학습의 핵심."""
    from app.views.quiz_view import build_quiz_view
    d = _quiz_dir(tmp_path)
    v1 = build_quiz_view(quiz_dir=d)
    opts = _options(v1)
    opts[0].on_click(None)                    # q1 정답
    opts[2].on_click(None)                    # q2 정답(보기 2개씩이므로 index 2)
    opts[5].on_click(None)                    # q3 오답

    v2 = build_quiz_view(quiz_dir=d)          # 앱을 다시 켠 셈
    first = next(c.value for c in _walk(v2)
                 if isinstance(c, ft.Text) and str(c.value or "").startswith("문항"))
    assert first == "문항 3"


def test_wrong_only_mode_shows_just_the_misses(tmp_path):
    from app.views.quiz_view import build_quiz_view
    d = _quiz_dir(tmp_path)
    v = build_quiz_view(quiz_dir=d)
    _options(v)[1].on_click(None)             # q1 오답
    _mode_btn(v, "오답만").on_click(None)
    shown = [c.value for c in _walk(v)
             if isinstance(c, ft.Text) and str(c.value or "").startswith("문항")]
    assert shown == ["문항 1"]


def test_wrong_only_says_so_when_nothing_is_wrong(tmp_path):
    from app.views.quiz_view import build_quiz_view
    v = build_quiz_view(quiz_dir=_quiz_dir(tmp_path))
    _mode_btn(v, "오답만").on_click(None)
    texts = [str(c.value or "") for c in _walk(v) if isinstance(c, ft.Text)]
    assert any("틀린 문항이 없습니다" in t for t in texts)


def test_reset_clears_the_saved_record(tmp_path):
    from app.views.quiz_view import build_quiz_view
    d = _quiz_dir(tmp_path)
    v = build_quiz_view(quiz_dir=d)
    _options(v)[1].on_click(None)
    assert qp.load(qp.progress_path(d))
    next(c for c in _walk(v) if isinstance(c, ft.OutlinedButton)
         and c.content == "현재 강 초기화").on_click(None)
    assert qp.load(qp.progress_path(d)) == {}


def test_a_question_without_an_answer_is_not_scored(tmp_path):
    """정답을 모르는 문항(정답표에 글자가 있던 자리)은 채점하지 않는다."""
    from app.views.quiz_view import build_quiz_view
    d = tmp_path / "퀴즈"
    d.mkdir()
    (d / "b.json").write_text(json.dumps(
        {"course": "C프로그래밍", "seq": 20181, "name": "2018",
         "exam": {"year": 2018, "term": 1},
         "questions": [{"qid": "q25", "question": "문항 25",
                        "options": [{"no": 1, "text": "가"},
                                    {"no": 2, "text": "나"}],
                        "answer_no": 0}]}, ensure_ascii=False), encoding="utf-8")
    v = build_quiz_view(quiz_dir=d)
    _options(v)[0].on_click(None)
    assert qp.load(qp.progress_path(d)) == {}      # 기록이 남지 않는다


# --- 아직 안 푼 것만 --------------------------------------------------------
# '전체' 는 틀린 것부터 내주므로 이미 푼 문항을 지나야 안 푼 문항에 닿는다.
# 24문항 중 14문항이 남았을 때 그 14개만 보려면 눈으로 골라내야 했다.
def test_pick_new_mode_keeps_only_what_was_never_answered():
    b = _bank()
    qs = [_q("a"), _q("b"), _q("c")]
    prog = {qp.record_key(b, "a"): qp.mark(None, True, NOW),     # 맞힘
            qp.record_key(b, "b"): qp.mark(None, False, NOW)}    # 틀림
    assert [q["qid"] for q in qp.pick(qs, prog, b, "new", NOW)] == ["c"]


def test_pick_new_mode_drops_a_question_once_it_is_answered():
    """한 번 풀고 나면 '안 푼 것' 에서 빠져야 한다(맞혔든 틀렸든)."""
    b = _bank()
    prog = {qp.record_key(b, "a"): qp.mark(None, False, NOW)}
    assert qp.pick([_q("a")], prog, b, "new", NOW) == []


def test_pick_new_mode_counts_match_the_headline():
    """머리말의 '아직 N' 과 '안 푼 것만' 이 낸 문항 수가 같아야 한다."""
    b = _bank()
    qs = [_q(x) for x in "abcde"]
    prog = {qp.record_key(b, "a"): qp.mark(None, True, NOW),
            qp.record_key(b, "b"): qp.mark(None, False, NOW)}
    s = qp.bank_stats(qs, prog, b, NOW)
    left = s["total"] - s["seen"]
    assert len(qp.pick(qs, prog, b, "new", NOW)) == left == 3


def test_the_new_mode_is_a_known_mode():
    assert "new" in qp.MODES
