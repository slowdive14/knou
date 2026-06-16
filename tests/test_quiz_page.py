"""quiz_page 단위테스트 (퀴즈 복습 HTML — Phase 4 조립/저장).

은행 폴더 수집·정렬, HTML 조립, 캡처 저장(병합)을 검증한다.
실제 LMS 캡처(_stage_exam/watch 연결)는 수동 검증 게이트.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quiz_page import (  # noqa: E402
    build_quiz_page,
    collect_banks,
    persist_questions,
)
from quizbank import load_bank, make_bank, save_bank  # noqa: E402


def _q(qid="1", question="Q", **kw):
    base = {"qid": qid, "question": question,
            "options": [{"no": 1, "text": "가"}]}
    base.update(kw)
    return base


def _write(d, course, seq, name, qs):
    save_bank(Path(d) / f"{course}_{seq}강.json", make_bank(course, seq, name, qs))


def test_collect_banks_sorts_by_seq_and_excludes_empty(tmp_path):
    _write(tmp_path, "이산수학", 2, "집합", [_q("a")])
    _write(tmp_path, "이산수학", 1, "개요", [_q("b")])
    _write(tmp_path, "이산수학", 3, "빈강", [])     # 문제 없음 → 제외
    banks = collect_banks(tmp_path)
    assert [b["seq"] for b in banks] == [1, 2]


def test_collect_banks_missing_dir(tmp_path):
    assert collect_banks(tmp_path / "none") == []


def test_build_quiz_page_renders_questions(tmp_path):
    _write(tmp_path, "이산수학", 1, "개요",
           [_q("7", "문항본문ABC", answer_no=1, answer_text="가")])
    html = build_quiz_page(tmp_path, title="복습페이지")
    assert "<!DOCTYPE html>" in html
    assert "문항본문ABC" in html
    assert "복습페이지" in html


def test_build_quiz_page_empty_dir_is_safe(tmp_path):
    html = build_quiz_page(tmp_path / "none")
    assert "<!DOCTYPE html>" in html and "</html>" in html


def test_persist_questions_merges_and_fills(tmp_path):
    class _Cfg:
        summary_dir = tmp_path / "방송대"

    p = persist_questions(_Cfg(), "이산수학", 1, "개요", [_q("1", "Q1")])
    persist_questions(_Cfg(), "이산수학", 1, "개요",
                      [_q("1", "Q1", answer_text="가"), _q("2", "Q2")])
    bank = load_bank(p)
    assert [q["qid"] for q in bank["questions"]] == ["1", "2"]
    assert bank["questions"][0]["answer_text"] == "가"   # 빈 칸 보강


def test_persist_questions_empty_is_noop(tmp_path):
    class _Cfg:
        summary_dir = tmp_path / "방송대"

    assert persist_questions(_Cfg(), "이산수학", 1, "개요", []) is None
