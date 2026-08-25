"""status_html 순수 렌더 단위테스트 — 현황 표 HTML.

구조(과목·표·6열)·완료표시 3단계·파일 링크·이스케이프·자체완결·JS 없이 보이는지·
비밀값 미포함을 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from status_html import (  # noqa: E402
    fmt_when,
    overall_stats,
    render_status_html,
    row_is_done,
)


def _row(seq=1, name="C 언어의 개요", **over):
    row = {"course": "C프로그래밍", "seq": seq, "name": name,
           "video_done": False, "exam_done": False,
           "watched_min": 0, "total_min": 49,
           "watch_run": False, "exam_run": False,
           "watch_new": False, "exam_new": False,
           "notes": [], "mp3": None, "doc": None, "quiz_count": 0,
           "extra_videos": [], "extra_done": False}
    row.update(over)
    return row


def _course(rows=None, name="C프로그래밍"):
    from status_page import course_stats
    rows = rows if rows is not None else [_row()]
    return {"course": name, "rows": rows, "stats": course_stats(rows)}


def _file(name="C프로그래밍_1강.mp3", url="file:///C:/d/x.mp3"):
    return {"name": name, "url": url, "ext": name.rsplit(".", 1)[-1],
            "size_mb": 72.7}


# --- 문서 구조 -------------------------------------------------------------
def test_render_returns_html_document():
    html = render_status_html([_course()])
    assert html.lstrip().startswith("<!DOCTYPE html>") and "</html>" in html


def test_render_lists_course_and_lecture():
    html = render_status_html([_course([_row(seq=3, name="포인터")])])
    assert "C프로그래밍" in html and "포인터" in html
    assert '<span class="seq">03</span>' in html      # 두 자리 mono 번호


def test_render_has_six_columns():
    html = render_status_html([_course()])
    for col in ("차시", "영상이수", "형성평가", "예습노트", "MP3", "강의록"):
        assert f"<th>{col}</th>" in html or f'class="lec">{col}<' in html


def test_render_empty_is_safe():
    html = render_status_html([])
    assert "표시할 강의가 없습니다" in html
    assert html.lstrip().startswith("<!DOCTYPE html>")


# --- 완료 표시 3단계 -------------------------------------------------------
def test_lms_done_shows_check():
    html = render_status_html([_course([_row(video_done=True)])])
    assert '<span class="pill ok">' in html and "이수완료" in html
    assert 'href="#i-check"' in html                  # 아이콘은 인라인 SVG


def test_fresh_run_shows_starred_check():
    # 목록 새로고침 전에 이수한 경우 — LMS 는 아직 모른다
    html = render_status_html([_course([_row(watch_run=True, watch_new=True)])])
    assert '<span class="pill fresh"' in html and "실행함<sup>*</sup>" in html


def test_old_run_without_lms_done_shows_pending_pill():
    html = render_status_html([_course([_row(watch_run=True)])])
    assert '<span class="pill wait"' in html and "실행함" in html
    # 갱신 전 실행(fresh)과 구분 — 표 안에는 fresh 알약이 없다(범례에는 있음)
    assert '<span class="pill fresh" title=' not in html


def test_nothing_shows_dash():
    html = render_status_html([_course([_row()])])
    assert '<span class="none">·</span>' in html


# --- 파일 링크 -------------------------------------------------------------
def test_mp3_and_doc_are_links():
    row = _row(mp3=_file(), doc=dict(_file("C프로그래밍_1강.pdf",
                                           "file:///C:/d/x.pdf"), kind="PDF"))
    html = render_status_html([_course([row])])
    assert 'href="file:///C:/d/x.mp3"' in html and "<span>MP3</span>" in html
    assert 'href="file:///C:/d/x.pdf"' in html and "<span>PDF</span>" in html
    assert 'href="#i-audio"' in html and 'href="#i-doc"' in html


def test_note_links_include_second_video_note():
    row = _row(notes=[{"name": "n.md", "url": "file:///C:/v/n.md", "part": 1},
                      {"name": "n2.md", "url": "file:///C:/v/n2.md", "part": 2}])
    html = render_status_html([_course([row])])
    assert "<span>노트</span>" in html and "<span>2</span>" in html
    assert html.count('href="#i-note"') == 2


def test_pending_second_video_note_is_flagged():
    row = _row(notes=[{"name": "n.md", "url": "file:///C:/v/n.md", "part": 1}],
               extra_videos=[{"idx": 1, "duration": 900}])
    assert "＋2번째 영상" in render_status_html([_course([row])])


def test_quiz_count_links_to_quiz_page():
    row = _row(quiz_count=4)
    html = render_status_html([_course([row])], quiz_url="file:///C:/v/q.html")
    assert "4문항" in html and 'href="file:///C:/v/q.html"' in html
    assert "퀴즈 복습 페이지" in html


def test_quiz_count_without_page_is_plain_chip():
    html = render_status_html([_course([_row(quiz_count=4)])])
    assert "4문항" in html and "퀴즈 복습 페이지" not in html


# --- 통계/머리말 -----------------------------------------------------------
def test_overall_stats_sums_courses():
    c1 = _course([_row(video_done=True)])
    c2 = _course([_row(video_done=True), _row(seq=2)], name="자료구조")
    total = overall_stats([c1, c2])
    assert total["total"] == 3 and total["watched"] == 2


def test_header_shows_counts_and_snapshot_time():
    html = render_status_html([_course()],
                              generated_at="2026-08-17T12:09:22")
    assert "1과목" in html and "목록 기준 2026-08-17 12:09" in html


def test_fmt_when_handles_odd_input():
    assert fmt_when("2026-08-17T12:09:22") == "2026-08-17 12:09"
    assert fmt_when("") == ""
    assert fmt_when("어제") == "어제"


# --- 남은 것만 보기 기준 ----------------------------------------------------
def test_row_is_done_requires_all_three():
    note = [{"part": 1}]
    assert row_is_done(_row(video_done=True, exam_done=True, notes=note))
    assert not row_is_done(_row(video_done=True, exam_done=True))
    assert not row_is_done(_row(video_done=True, notes=note))


def test_row_is_done_accepts_fresh_runs():
    # 방금 이수했는데 목록이 옛날이라 미완료로 보이는 줄도 '완료'로 친다
    note = [{"part": 1}]
    assert row_is_done(_row(watch_run=True, watch_new=True,
                            exam_run=True, exam_new=True, notes=note))


def test_done_row_gets_done_class():
    note = [{"part": 1}]
    html = render_status_html([_course([_row(video_done=True, exam_done=True,
                                             notes=note)])])
    assert '<tr class="done">' in html


# --- 안전 -----------------------------------------------------------------
def test_render_escapes_html():
    html = render_status_html([_course([_row(name="<script>x</script>")])])
    assert "<script>x</script>" not in html and "&lt;script&gt;" in html


def test_render_is_self_contained():
    html = render_status_html([_course()])
    assert "<script src=" not in html
    assert "http://" not in html and "https://" not in html


def test_render_no_secrets():
    html = render_status_html([_course()])
    assert "KNOU_PW" not in html and "GEMINI_API_KEY" not in html


def test_table_rows_visible_without_js():
    # 표는 CSS 로 숨기지 않는다(JS 는 '남은 것만 보기' 필터에만 쓰임)
    html = render_status_html([_course()])
    assert "tbody tr { display: none" not in html
    assert "body.only-todo tr.done { display: none; }" in html


# --- 새 디자인 요소 --------------------------------------------------------
def test_icons_are_inline_sprite_not_emoji():
    # 이모지 대신 문서 안 SVG 스프라이트를 참조한다(외부 파일 0)
    html = render_status_html([_course([_row(video_done=True)])])
    assert '<symbol id="i-check"' in html and '<svg class="sprite">' in html
    assert "xmlns" not in html            # 인라인 SVG 라 네임스페이스 불필요


def test_course_ring_encodes_progress():
    from status_html import RING_C
    c = _course([_row(video_done=True), _row(seq=2)])
    html = render_status_html([c])
    assert f"--c:{RING_C}" in html        # 원주
    assert '<span class="ring-n">50<em>%</em></span>' in html


def test_ring_at_zero_is_full_offset():
    from status_html import RING_C
    html = render_status_html([_course([_row(), _row(seq=2)])])
    assert f"--o:{RING_C}" in html        # 0% → 원호 전체가 비어 있음


def test_progress_bar_only_when_watched():
    # 0분 시청인 줄에 빈 회색 막대를 그리지 않는다(줄 높이 낭비 방지)
    bar = '<span class="mbar">'
    assert bar not in render_status_html([_course([_row(watched_min=0)])])
    assert bar in render_status_html([_course([_row(watched_min=20)])])


def test_rows_are_classed_by_activity():
    idle = render_status_html([_course([_row()])])
    live = render_status_html([_course([_row(mp3={"name": "a", "url": "file:///a"})])])
    assert '<tr class="idle">' in idle and '<tr class="live">' in live


def test_page_has_dark_mode_and_reduced_motion():
    html = render_status_html([_course()])
    assert "prefers-color-scheme: dark" in html
    assert "prefers-reduced-motion: reduce" in html


def test_metric_rails_render_percent():
    html = render_status_html([_course([_row(video_done=True), _row(seq=2)])])
    assert "--w:50.0%" in html


def test_long_title_is_single_line_with_tooltip():
    name = "생성형 AI 기반 서비스를 활용한 리서치 활용"
    html = render_status_html([_course([_row(name=name)])])
    assert f'title="{name}"' in html      # 잘려도 전체는 툴팁으로


# --- 화면 밝기(테마) 전환 ---------------------------------------------------
def test_theme_button_is_rendered():
    html = render_status_html([_course()])
    assert 'id="themeBtn"' in html and 'id="themeLbl"' in html
    for sym in ('id="i-sun"', 'id="i-moon"', 'id="i-auto"'):
        assert sym in html                    # 해·달·자동 아이콘


def test_dark_palette_applies_to_system_and_manual_choice():
    html = render_status_html([_course()])
    # ① 시스템이 다크 + 사용자가 '밝게'를 고르지 않았을 때
    assert ':root:not([data-theme="light"])' in html
    # ② 사용자가 '어둡게'를 직접 골랐을 때(시스템이 밝아도)
    assert ':root[data-theme="dark"]' in html
    assert html.count("--paper:#101315") == 2  # 팔레트는 한 벌, 두 셀렉터에


def test_saved_theme_applied_before_paint():
    # 머리(head)에서 저장값을 먼저 적용 → 열자마자 반대 테마가 번쩍이지 않게
    html = render_status_html([_course()])
    head = html.split("<body>")[0]
    from ui_theme import THEME_KEY
    assert THEME_KEY in head          # 두 페이지가 같은 키를 쓴다(현황·퀴즈)
    assert "<script src=" not in html          # 여전히 외부 파일 0


def test_theme_choice_is_optional_without_js():
    # JS 가 없으면 data-theme 이 안 붙고 시스템 설정을 그대로 따른다
    html = render_status_html([_course()])
    assert "prefers-color-scheme: dark" in html
    assert 'data-theme="dark">' not in html    # 서버가 테마를 못박지 않는다
