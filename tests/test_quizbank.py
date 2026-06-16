"""quizbank 순수 로직 단위테스트 (퀴즈 복습 HTML — Phase 1).

문항 스키마 정규화 / qid 기준 병합·중복제거 / JSON 저장·로드 / 경로 규칙만
검증한다(LMS 스캔·HTML 생성은 후속 Phase). 표준 라이브러리만 사용.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quizbank import (  # noqa: E402
    bank_path,
    load_bank,
    make_bank,
    merge_questions,
    normalize_question,
    save_bank,
)


# --- normalize_question ----------------------------------------------------
def test_normalize_fills_canonical_shape():
    q = normalize_question({
        "qid": "74151", "source": "형성평가", "qtype": "객관식",
        "question": "정답은?",
        "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
        "answer_no": 1, "answer_text": "가", "explanation": "설명",
    })
    assert q["qid"] == "74151"
    assert q["source"] == "형성평가"
    assert q["question"] == "정답은?"
    assert q["options"] == [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}]
    assert q["answer_no"] == 1
    assert q["answer_text"] == "가"
    assert q["explanation"] == "설명"


def test_normalize_defaults_and_aliases():
    q = normalize_question({"exqsId": "9", "stem": "문제"})
    assert q["qid"] == "9"            # exqsId 별칭 → qid
    assert q["question"] == "문제"     # stem 별칭 → question
    assert q["options"] == []
    assert q["answer_no"] is None
    assert q["answer_text"] == ""
    assert q["explanation"] == ""
    assert q["source"] == ""


def test_normalize_coerces_option_types():
    q = normalize_question({"qid": "1", "options": [{"no": "2", "text": 30}]})
    assert q["options"] == [{"no": 2, "text": "30"}]


def test_normalize_is_idempotent():
    once = normalize_question({"exqsId": "5", "stem": "Q"})
    twice = normalize_question(once)
    assert once == twice


def test_normalize_requires_qid():
    with pytest.raises(ValueError):
        normalize_question({"question": "식별자 없음"})


# --- merge_questions -------------------------------------------------------
def test_merge_appends_new_and_dedups_by_qid():
    a = [normalize_question({"qid": "1", "question": "Q1"})]
    b = [normalize_question({"qid": "1", "question": "Q1"}),
         normalize_question({"qid": "2", "question": "Q2"})]
    out = merge_questions(a, b)
    assert [q["qid"] for q in out] == ["1", "2"]   # 순서 보존 + 중복 제거


def test_merge_fills_missing_answer_explanation():
    old = [normalize_question({"qid": "1", "question": "Q1"})]  # 정답/해설 없음
    new = [normalize_question({"qid": "1", "question": "Q1", "answer_no": 2,
                               "answer_text": "나", "explanation": "해설"})]
    out = merge_questions(old, new)
    assert out[0]["answer_no"] == 2
    assert out[0]["answer_text"] == "나"
    assert out[0]["explanation"] == "해설"


def test_merge_keeps_existing_when_new_empty():
    old = [normalize_question({"qid": "1", "question": "Q1",
                               "explanation": "원해설"})]
    new = [normalize_question({"qid": "1", "question": "Q1", "explanation": ""})]
    out = merge_questions(old, new)
    assert out[0]["explanation"] == "원해설"   # 빈 신규로 덮어쓰지 않음


def test_merge_empty_inputs():
    assert merge_questions([], []) == []
    one = [normalize_question({"qid": "1"})]
    assert merge_questions(one, []) == one
    assert merge_questions([], one) == one


# --- save / load round trip ------------------------------------------------
def test_save_load_bank_round_trip(tmp_path):
    bank = make_bank("이산수학", 1, "개요",
                     [normalize_question({"qid": "1", "question": "Q",
                                          "answer_text": "가"})])
    p = tmp_path / "퀴즈" / "x.json"
    save_bank(p, bank)
    loaded = load_bank(p)
    assert loaded["course"] == "이산수학"
    assert loaded["seq"] == 1
    assert loaded["questions"][0]["qid"] == "1"
    assert loaded["questions"][0]["answer_text"] == "가"


def test_load_bank_missing_returns_empty(tmp_path):
    b = load_bank(tmp_path / "nope.json")
    assert b["questions"] == []


def test_load_bank_broken_returns_empty(tmp_path):
    p = tmp_path / "broken.json"
    p.write_text("{not json", encoding="utf-8")
    assert load_bank(p)["questions"] == []


def test_save_bank_is_utf8_korean(tmp_path):
    bank = make_bank("이산수학", 1, "개요",
                     [normalize_question({"qid": "1", "question": "한글문제"})])
    p = tmp_path / "x.json"
    save_bank(p, bank)
    raw = p.read_text(encoding="utf-8")
    assert "한글문제" in raw          # ensure_ascii=False 로 한글 보존


def test_save_bank_no_secrets(tmp_path):
    bank = make_bank("이산수학", 1, "개요",
                     [normalize_question({"qid": "1", "question": "Q"})])
    p = tmp_path / "x.json"
    save_bank(p, bank)
    raw = p.read_text(encoding="utf-8")
    assert "KNOU_PW" not in raw and "GEMINI_API_KEY" not in raw


# --- bank_path -------------------------------------------------------------
def test_bank_path_uses_summary_dir_and_quiz_folder(tmp_path):
    class _Cfg:
        summary_dir = tmp_path / "방송대"

    p = bank_path(_Cfg(), "데이터베이스시스템", 14)
    assert p.parent.name == "퀴즈"
    assert p.name.endswith("14강.json")
    assert "데이터베이스시스템" in p.name
