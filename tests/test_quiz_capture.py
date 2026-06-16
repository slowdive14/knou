"""quiz_capture 순수 파싱 단위테스트 (퀴즈 복습 HTML — Phase 2).

스캔 결과(raw dict) → 표준 문항 목록 변환만 검증한다. 실제 브라우저 DOM 스캔
(scan_quiz)은 수동 검증 게이트(LMS 라이브)라 여기서 테스트하지 않는다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quiz_capture import parse_scanned  # noqa: E402


def test_parse_scanned_basic_answer_by_number():
    raw = {"source": "형성평가", "questions": [
        {"exqsId": "74151", "question": "정답은?", "exqsDc": "1", "exqsTc": "1",
         "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
         "answer_text": "1", "explanation": "해설"}]}
    out = parse_scanned(raw)
    assert len(out) == 1
    q = out[0]
    assert q["qid"] == "74151"
    assert q["source"] == "형성평가"
    assert q["answer_no"] == 1
    assert q["answer_text"] == "가"        # 정답 번호 → 보기 텍스트로 보강
    assert q["explanation"] == "해설"


def test_parse_scanned_answer_by_text_match():
    raw = {"source": "돌발퀴즈", "questions": [
        {"exqsId": "9", "question": "Q",
         "options": [{"no": 1, "text": "폰노이만"}, {"no": 2, "text": "하버드"}],
         "answer_text": "하버드"}]}
    q = parse_scanned(raw)[0]
    assert q["answer_no"] == 2              # 텍스트 일치 → 보기 번호 찾기
    assert q["answer_text"] == "하버드"
    assert q["source"] == "돌발퀴즈"


def test_parse_scanned_unsolved_has_no_answer():
    raw = {"questions": [
        {"exqsId": "1", "question": "Q", "options": [{"no": 1, "text": "가"}]}]}
    q = parse_scanned(raw)[0]
    assert q["answer_no"] is None
    assert q["answer_text"] == ""
    assert q["explanation"] == ""


def test_parse_scanned_qtype_defaults_objective_when_options():
    raw = {"questions": [{"exqsId": "1", "options": [{"no": 1, "text": "가"}]}]}
    assert parse_scanned(raw)[0]["qtype"] == "객관식"


def test_parse_scanned_source_fallback_per_question():
    # 상위 source 가 비어도 문항별 source 가 있으면 유지
    raw = {"questions": [{"exqsId": "1", "source": "돌발퀴즈"}]}
    assert parse_scanned(raw)[0]["source"] == "돌발퀴즈"


def test_parse_scanned_skips_missing_id():
    # exqsId 없는 문항은 건너뛴다(전체 실패 대신 스킵)
    raw = {"questions": [{"question": "no id"}, {"exqsId": "2", "question": "Q"}]}
    out = parse_scanned(raw)
    assert [q["qid"] for q in out] == ["2"]


def test_parse_scanned_empty():
    assert parse_scanned({}) == []
    assert parse_scanned(None) == []
