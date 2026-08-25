"""quiz_html 순수 렌더 단위테스트 (퀴즈 복습 HTML — Phase 3).

render_quiz_html(lectures) → 단일 자체완결 HTML 문자열. 구조·이스케이프·정답
비노출·사이드바·진행률·내비/초기화·출처배지·단일파일·비밀값 미포함을 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from quiz_html import render_quiz_html  # noqa: E402


def _lec(seq=1, name="컴퓨터의 이해", course="파이썬", questions=None):
    return {"course": course, "seq": seq, "name": name,
            "questions": questions if questions is not None else [_q()]}


def _q(qid="1", question="폰 노이만 구조는?", source="형성평가",
       answer_no=1, answer_text="폰 노이만 구조", explanation="설명입니다"):
    return {"qid": qid, "source": source, "qtype": "객관식",
            "question": question,
            "options": [{"no": 1, "text": "폰 노이만 구조"},
                        {"no": 2, "text": "하버드 구조"}],
            "answer_no": answer_no, "answer_text": answer_text,
            "explanation": explanation}


def test_render_returns_html_document():
    html = render_quiz_html([_lec()])
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_render_includes_title():
    html = render_quiz_html([_lec()], title="파이썬 강의 퀴즈")
    assert "파이썬 강의 퀴즈" in html


def test_render_includes_question_and_options():
    html = render_quiz_html([_lec(questions=[_q(question="질문본문XYZ")])])
    assert "질문본문XYZ" in html
    assert "폰 노이만 구조" in html and "하버드 구조" in html


def test_render_escapes_html():
    html = render_quiz_html([_lec(questions=[_q(question="<script>x</script>")])])
    assert "<script>x</script>" not in html       # 원시 스크립트 주입 방지
    assert "&lt;script&gt;" in html


def test_render_answer_hidden_by_default():
    html = render_quiz_html([_lec(questions=[_q(answer_no=1,
                                               explanation="해설텍스트")])])
    # 정답은 data 속성 + 기본 숨김(hidden) 박스에만, 평문으로 바로 노출되지 않음
    assert 'data-answer-no="1"' in html
    assert 'class="answer-box" hidden' in html
    assert "해설텍스트" in html                    # 숨김 박스 안에 존재


def test_render_sidebar_lists_all_lectures():
    lecs = [_lec(seq=1), _lec(seq=2), _lec(seq=3)]
    html = render_quiz_html(lecs)
    assert html.count('class="lec-item') == 3      # 첫 항목은 'lec-item active'


def test_render_has_nav_and_reset_controls():
    html = render_quiz_html([_lec()])
    for label in ("이전 강의", "다음 강의", "현재 강 초기화", "전체 초기화"):
        assert label in html


def test_render_has_progress_and_answer_button():
    html = render_quiz_html([_lec()])
    assert "progress" in html          # 진행률 마크업
    assert "정답 보기" in html


def test_render_progress_has_count_and_label():
    # 첨부 이미지: "N / N" 카운트 + "N문제 풀이" 라벨
    html = render_quiz_html([_lec()])
    assert 'id="progressText"' in html
    assert 'id="progressLabel"' in html
    assert "문제 풀이" in html


def test_render_answer_box_has_header():
    html = render_quiz_html([_lec(questions=[_q(explanation="해설")])])
    assert 'class="ans-head"' in html      # '정답' 헤더 스타일


def test_render_shows_source_badge():
    html = render_quiz_html([_lec(questions=[_q(source="돌발퀴즈")])])
    assert "돌발퀴즈" in html


def test_render_is_self_contained():
    html = render_quiz_html([_lec()])
    assert "<script src=" not in html          # 외부 JS 링크 없음
    assert "cdn" not in html.lower()           # CDN 의존 없음
    assert "http://" not in html and "https://" not in html


def test_render_empty_is_safe():
    html = render_quiz_html([])
    assert html.lstrip().startswith("<!DOCTYPE html>")
    assert "</html>" in html


def test_render_first_lecture_visible_without_js():
    # JS 가 안 돌아도 첫 강 문제가 보여야 한다(.lecture 는 기본 display:none).
    html = render_quiz_html([_lec(seq=1, questions=[_q(question="첫강문제")]),
                             _lec(seq=2)])
    assert 'class="lecture active"' in html
    assert html.count('class="lecture active"') == 1     # 첫 강만 활성
    assert 'class="lec-item active"' in html


def test_render_header_prefilled_without_js():
    # 제목·문제수도 서버에서 채워 둔다(빈 헤더 방지).
    html = render_quiz_html([_lec(seq=3, name="자료구조", course="파이썬",
                                  questions=[_q("1"), _q("2")])])
    assert '<div class="lec-title" id="lecTitle">파이썬 · 3강 · 자료구조</div>' in html
    assert '>0 / 2<' in html and ">2문제 풀이<" in html


def test_render_no_secrets():
    html = render_quiz_html([_lec()])
    assert "KNOU_PW" not in html and "GEMINI_API_KEY" not in html
