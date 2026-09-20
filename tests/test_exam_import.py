"""기출 더 가져오기 — 안 담은 회차만, 못 읽는 자료는 이유를 남기고.

자료실에는 기출이 잔뜩 있지만(컴퓨터구조 49건·자료구조 32건·C프로그래밍 26건)
PDF 첨부는 그 절반도 안 된다. 나머지는 HWP 인데 **배포용 문서**라 본문이 열리지
않는다(실측: '최신 버전의 한글이 필요합니다' 한 줄만 나온다).

같은 학기에 기말과 출석수업대체시험이 나란히 있다는 것도 함정이다. 무엇을 왜
건너뛰었는지 화면에 남겨야 한다.
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


def test_a_round_with_no_file_at_all_is_skipped(tmp_path):
    """PDF 도 HWP 도 없으면 손쓸 길이 없다.

    HWP 만 있는 회차는 더 이상 여기서 걸러지지 않는다 — 직접 넣어 둔 PDF 나
    한글 변환으로 길이 열렸다(hwp_convert 참고).
    """
    todo, skip = bx.plan_imports([_row((2014, 1), pdf=None)], tmp_path)
    assert todo == []
    assert any("PDF 도 HWP 도 없습니다" in why for _r, why in skip)


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


# --- 같은 학기에 시험이 둘 있다 ----------------------------------------------
# 실측(컴퓨터구조): '[2019. 2학기] 기말시험' 과 '[2019. 2학기] 출석수업대체시험'
# 이 나란히 있다. 둘 다 (2019, 2) 라 그대로 담으면 파일·문항번호가 겹치고,
# 정답표는 기말 것뿐이라 대체시험에 붙이면 25개가 통째로 어긋난다.
def test_the_kind_of_exam_is_read_from_the_title():
    assert eb.exam_kind("[2019. 2학기] 기말시험 기출문제") == eb.KIND_FINAL
    assert eb.exam_kind("[2019. 2학기] 출석수업대체시험 기출문제") == eb.KIND_MAKEUP
    assert eb.exam_kind("[2018.2학기 출석대체시험] 기출문제") == eb.KIND_MAKEUP
    assert eb.exam_kind("[2017 하계계절수업시험] 컴퓨터구조") == eb.KIND_SEASON
    assert eb.exam_kind("[2002.2]기출문제해설/컴퓨터구조") == eb.KIND_NOTE


def test_a_makeup_exam_is_not_imported(tmp_path):
    """기말 정답표가 대체시험 문항에 붙으면 통째로 어긋난 채 저장된다."""
    rows = [_row((2019, 2), title="[2019. 2학기] 기말시험 기출문제"),
            _row((2019, 2), title="[2019. 2학기] 출석수업대체시험 기출문제")]
    todo, skip = bx.plan_imports(rows, tmp_path)
    assert [r["title"] for r in todo] == ["[2019. 2학기] 기말시험 기출문제"]
    assert any("출석수업대체시험" in why for _r, why in skip)


def test_a_commentary_post_is_not_an_exam(tmp_path):
    rows = [_row((2002, 2), title="[2002.2]기출문제해설/컴퓨터구조")]
    todo, skip = bx.plan_imports(rows, tmp_path)
    assert todo == [] and any("문제해설" in why for _r, why in skip)


def test_a_seasonal_exam_is_still_imported(tmp_path):
    """계절수업은 학기 번호가 0 이라 기말과 겹치지 않는다."""
    rows = [_row((2017, 0), title="[2017 하계계절수업시험] 컴퓨터구조")]
    todo, _skip = bx.plan_imports(rows, tmp_path, want_all=True)
    assert [r["key"] for r in todo] == [(2017, 0)]


# --- 과목을 바꿔 쓸 수 있는가 ------------------------------------------------
def test_the_bank_name_follows_the_course(tmp_path):
    (tmp_path / eb.bank_filename("컴퓨터구조", 2019, 2)).write_text(
        "{}", encoding="utf-8")
    assert bx.bank_exists(tmp_path, 2019, 2, "컴퓨터구조")
    assert not bx.bank_exists(tmp_path, 2019, 2, "자료구조")


def test_the_notice_names_the_course():
    from app.views.quiz_view import import_body
    assert "'자료구조'" in import_body("자료구조")
    assert "이 과목" in import_body("")


def test_the_post_count_is_high_enough_to_see_old_exams():
    """실측: 기본값 100 이면 딱 100건에 잘려 오래된 기출이 안 보인다."""
    assert bx.POST_COUNT >= 300


# --- 진행이 화면에 보이는가 --------------------------------------------------
# 실측: 앱에서 '새로 가져올 회차 4개' 까지만 뜨고, 정작 오래 걸리는 구간(PDF
# 받기 + AI 가 문항 읽기, 회차당 2~3분)에서 아무 소식이 없어 멈춘 것처럼 보였다.
def test_building_a_round_reports_through_the_given_channel():
    import inspect
    src = inspect.getsource(bx.build_one)
    assert "log = on_event or _log" in src
    assert "_log(" not in src.split('"""', 2)[-1]   # 몸통에서는 콘솔로 안 찍는다


def test_the_slow_steps_say_what_they_are_doing():
    import inspect
    src = inspect.getsource(bx.build_one)
    assert "PDF 받는 중" in src
    assert "몇 분 걸립니다" in src


def test_the_page_by_page_progress_is_passed_along():
    """비전은 쪽마다 보고한다 — 그 보고가 화면까지 와야 한다."""
    import inspect
    src = inspect.getsource(bx.build_one)
    assert "on_event=log" in src
