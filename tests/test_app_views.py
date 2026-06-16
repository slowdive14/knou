"""Flet 화면 구성 오프라인 스모크 테스트 (디스플레이 없이 컨트롤 트리만 검증).

실제 창 띄우기는 수동 검증. 여기서는 뷰 빌더가 예외 없이 컨트롤을 만들고
필수 구조(필드 6개·비밀필드 2개)와 저장 로직이 맞는지 확인한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

ft = pytest.importorskip("flet")  # flet 미설치 시 스킵

from app.views.settings_view import (  # noqa: E402
    apply_settings,
    build_settings_view,
)


def _walk(control):
    """컨트롤 트리를 깊이우선 순회(.controls / .content)."""
    yield control
    for child in getattr(control, "controls", None) or []:
        yield from _walk(child)
    inner = getattr(control, "content", None)
    if inner is not None and hasattr(inner, "__class__"):
        yield from _walk(inner)


def _textfields(control):
    return [c for c in _walk(control) if isinstance(c, ft.TextField)]


# --- settings view 구성 ----------------------------------------------------
def test_settings_view_builds_six_fields(tmp_path):
    view = build_settings_view(tmp_path / ".env")
    tfs = _textfields(view)
    assert len(tfs) == 6


def test_settings_view_secret_fields_are_password(tmp_path):
    view = build_settings_view(tmp_path / ".env")
    secret = [t for t in _textfields(view) if t.password]
    # 비밀번호 + Gemini 키 = 정확히 2개
    assert len(secret) == 2
    assert all(t.can_reveal_password for t in secret)


def test_settings_view_prefills_existing_values(tmp_path):
    p = tmp_path / ".env"
    p.write_text("KNOU_ID=loaded_id\n", encoding="utf-8")
    view = build_settings_view(p)
    values = {t.value for t in _textfields(view)}
    assert "loaded_id" in values


def test_settings_view_has_desktop_shortcut_button(tmp_path):
    # Phase 5: 비개발자가 바탕화면 바로가기를 만들 수 있는 버튼이 있어야 함
    view = build_settings_view(tmp_path / ".env")
    labels = [c.content for c in _walk(view)
              if isinstance(c, ft.OutlinedButton)]
    assert any("바로가기" in str(l) for l in labels)


def test_settings_view_first_run_hint_only_when_incomplete(tmp_path):
    # 필수값 누락(첫 실행)이면 친절 안내가 뜨고, 다 채워지면 사라진다.
    texts_missing = [c.value for c in _walk(build_settings_view(tmp_path / "a.env"))
                     if isinstance(c, ft.Text)]
    assert any("처음이신가요" in str(v) for v in texts_missing)

    p = tmp_path / "b.env"
    p.write_text("KNOU_ID=x\nKNOU_PW=y\nGEMINI_API_KEY=z\nVAULT_PATH=C:/v\n",
                 encoding="utf-8")
    texts_complete = [c.value for c in _walk(build_settings_view(p))
                      if isinstance(c, ft.Text)]
    assert not any("처음이신가요" in str(v) for v in texts_complete)


# --- apply_settings(저장 경로) ---------------------------------------------
def test_apply_settings_writes_and_reports_complete(tmp_path):
    p = tmp_path / ".env"
    missing = apply_settings(p, {
        "KNOU_ID": "id", "KNOU_PW": "pw",
        "GEMINI_API_KEY": "AIzaX", "VAULT_PATH": "C:/v",
    })
    assert missing == []
    assert "KNOU_ID=id" in p.read_text(encoding="utf-8")


def test_apply_settings_reports_missing(tmp_path):
    p = tmp_path / ".env"
    missing = apply_settings(p, {"KNOU_ID": "id"})
    assert "KNOU_PW" in missing
    assert "VAULT_PATH" in missing


def test_apply_settings_strips_whitespace(tmp_path):
    p = tmp_path / ".env"
    apply_settings(p, {
        "KNOU_ID": "  id  ", "KNOU_PW": "pw",
        "GEMINI_API_KEY": "k", "VAULT_PATH": "v",
    })
    assert "KNOU_ID=id\n" in p.read_text(encoding="utf-8")


# --- 앱 셸 구성(가짜 페이지) -----------------------------------------------
class _FakeWindow:
    pass


class _FakePage:
    def __init__(self):
        self.window = _FakeWindow()
        self.controls = []
        self.title = None
        self.updates = 0

    def add(self, *controls):
        self.controls.extend(controls)

    def update(self):
        self.updates += 1


def test_main_builds_shell_without_error():
    from app.main_app import APP_TITLE, main

    page = _FakePage()
    main(page)  # 예외 없이 셸 구성되어야 함
    assert page.title == APP_TITLE
    assert page.updates >= 1
    assert len(page.controls) == 1  # 최상위 Row 하나
    row = page.controls[0]
    # Row 안에 콘텐츠 컨테이너가 채워졌는지
    container = row.controls[-1]
    assert container.content is not None


# --- run_view 순수 헬퍼 -----------------------------------------------------
from app.views.run_view import (  # noqa: E402
    build_confirm_dialog,
    build_run_view,
    course_names,
    lecture_option_text,
    load_snapshot_rows,
    rows_for_course,
)
from runner import LectureRow  # noqa: E402


def _rows():
    return [
        LectureRow("데이터베이스시스템", 13, "트랜잭션", False, False),
        LectureRow("데이터베이스시스템", 14, "회복", True, True),
        LectureRow("이산수학", 1, "집합", False, False),
    ]


def test_course_names_unique_in_order():
    assert course_names(_rows()) == ["데이터베이스시스템", "이산수학"]


def test_rows_for_course_filters():
    rows = rows_for_course(_rows(), "데이터베이스시스템")
    assert {r.seq for r in rows} == {13, 14}


def test_lecture_option_text_marks_video_done():
    rows = _rows()
    assert lecture_option_text(rows[0]) == "13강 - 트랜잭션"        # 미이수
    assert lecture_option_text(rows[1]) == "14강 - 회복 ✅"          # 이수


def test_load_snapshot_rows_missing_file(tmp_path):
    assert load_snapshot_rows(tmp_path / "nope.json") == []


def test_load_snapshot_rows_reads_file(tmp_path):
    p = tmp_path / "lectures.json"
    p.write_text(
        '{"courses":[{"name":"이산수학","lectures":'
        '[{"seq":1,"name":"집합","video_done":false,"exam_done":false}]}]}',
        encoding="utf-8")
    rows = load_snapshot_rows(p)
    assert len(rows) == 1
    assert rows[0].course == "이산수학"


# --- run_view 구성(오프라인) -----------------------------------------------
def test_build_run_view_offline(tmp_path):
    # 스냅샷 없이도 예외 없이 빌드되어야 함
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    assert isinstance(view, ft.Column)
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    assert len(dds) == 2  # 과목·차시 드롭다운


def test_build_run_view_populates_courses(tmp_path):
    p = tmp_path / "lectures.json"
    p.write_text(
        '{"courses":[{"name":"이산수학","lectures":'
        '[{"seq":1,"name":"집합","video_done":false,"exam_done":false}]}]}',
        encoding="utf-8")
    view = build_run_view(snapshot_path=p)
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    course_dd = dds[0]
    assert course_dd.value == "이산수학"
    assert any(o.key == "이산수학" for o in course_dd.options)


def test_build_run_view_has_mode_radios(tmp_path):
    # 요약/이수/전체 세 모드 라디오가 화면에 노출되어야 함
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    radios = [c for c in _walk(view) if isinstance(c, ft.Radio)]
    assert len(radios) == 3
    assert {r.value for r in radios} == {"요약", "이수", "전체"}


def test_mode_change_updates_button_label(tmp_path):
    # Flet 0.85: 버튼 라벨은 .content (text 아님) — 회귀 방지
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    rg = next(c for c in _walk(view) if isinstance(c, ft.RadioGroup))
    btn = next(c for c in _walk(view) if isinstance(c, ft.FilledButton))
    assert btn.content == "예습 노트 생성"
    rg.value = "이수"
    rg.on_change(None)
    assert btn.content == "영상 이수 시작"
    rg.value = "전체"
    rg.on_change(None)
    assert btn.content == "이수 + 예습 노트 생성"


def test_build_run_view_has_redo_checkbox(tmp_path):
    # '다시 만들기(덮어쓰기)' 체크박스가 있고 기본은 꺼짐
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    chks = [c for c in _walk(view) if isinstance(c, ft.Checkbox)]
    assert len(chks) == 1
    assert chks[0].value is False
    assert "다시 만들기" in chks[0].label


def test_build_run_view_has_recent_log_button(tmp_path):
    # 예약(창 없이 실행)이 남긴 로그를 다시 볼 수 있는 버튼이 있어야 함
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    labels = [c.content for c in _walk(view)
              if isinstance(c, ft.OutlinedButton)]
    assert "최근 실행 로그 보기" in labels


def test_build_run_view_has_quiz_button(tmp_path):
    # 복습용 퀴즈 HTML 페이지를 만드는 버튼이 있어야 함
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    labels = [c.content for c in _walk(view)
              if isinstance(c, ft.OutlinedButton)]
    assert "퀴즈 페이지 만들기" in labels


def test_build_run_view_sleep_warning_hidden_by_default(tmp_path):
    # 절전 경고는 화면에 있지만 기본(요약) 모드에선 숨김
    from runner import watch_sleep_warning
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    warns = [c for c in _walk(view)
             if isinstance(c, ft.Text) and c.value == watch_sleep_warning()]
    assert len(warns) == 1
    assert warns[0].visible is False


# --- Phase 3 안전장치: 이수 확인 다이얼로그 -------------------------------
def test_confirm_dialog_is_modal_alert_with_checkbox():
    dlg, agree, start = build_confirm_dialog(
        "이수", "본문 경고", "약 28분 예상", lambda: None, lambda: None)
    assert isinstance(dlg, ft.AlertDialog)
    assert dlg.modal is True
    assert isinstance(agree, ft.Checkbox)


def test_confirm_dialog_start_disabled_until_agree():
    # 비가역 제출 안전장치: 동의 전에는 시작 버튼이 막혀 있고 클릭해도 무시된다
    calls = {"confirm": 0, "cancel": 0}
    dlg, agree, start = build_confirm_dialog(
        "이수", "본문", "약 28분 예상",
        on_confirm=lambda: calls.__setitem__("confirm", calls["confirm"] + 1),
        on_cancel=lambda: calls.__setitem__("cancel", calls["cancel"] + 1),
    )
    assert start.disabled is True
    start.on_click(None)               # 미동의 클릭 → 제출 안 됨
    assert calls["confirm"] == 0

    agree.value = True
    agree.on_change(None)              # 동의 → 활성화
    assert start.disabled is False
    start.on_click(None)               # 이제 제출
    assert calls["confirm"] == 1


def test_confirm_dialog_cancel_invokes_callback():
    calls = {"cancel": 0}
    dlg, agree, start = build_confirm_dialog(
        "이수", "본문", "",
        on_confirm=lambda: None,
        on_cancel=lambda: calls.__setitem__("cancel", calls["cancel"] + 1),
    )
    cancel_btn = dlg.actions[0]
    cancel_btn.on_click(None)
    assert calls["cancel"] == 1


def test_confirm_dialog_custom_start_label():
    # 예약 등록 등 재사용을 위해 시작 버튼 문구를 바꿀 수 있어야 함(Flet 0.85: .content)
    dlg, agree, start = build_confirm_dialog(
        "전체", "본문", "", lambda: None, lambda: None,
        start_label="예약 등록")
    assert start.content == "예약 등록"


# --- Phase 4: schedule_view 구성(오프라인) ---------------------------------
from app.views.schedule_view import build_schedule_view, build_task_row  # noqa: E402


def _outlined_labels(control):
    return [c.content for c in _walk(control)
            if isinstance(c, ft.OutlinedButton)]


def test_task_row_enabled_has_off_and_delete_buttons():
    # 켜져 있는(준비) 예약 줄에는 '끄기'와 '삭제' 버튼이 보여야 함
    row = build_task_row(
        {"name": "KNOU_요약", "next_run": "2026-06-03 02:00:00",
         "status": "준비"},
        on_toggle=lambda n, e: None, on_delete=lambda n: None)
    labels = _outlined_labels(row)
    assert "끄기" in labels
    assert "삭제" in labels


def test_task_row_disabled_shows_on_button():
    # 꺼진(사용 안 함) 예약 줄에서는 버튼이 '켜기'로 바뀜
    row = build_task_row(
        {"name": "KNOU_요약", "status": "사용 안 함"},
        on_toggle=lambda n, e: None, on_delete=lambda n: None)
    labels = _outlined_labels(row)
    assert "켜기" in labels
    assert "끄기" not in labels


def test_task_row_toggle_and_delete_callbacks():
    calls = {"toggle": [], "delete": []}
    row = build_task_row(
        {"name": "KNOU_요약", "status": "준비"},
        on_toggle=lambda n, e: calls["toggle"].append((n, e)),
        on_delete=lambda n: calls["delete"].append(n))
    off_btn = next(c for c in _walk(row)
                   if isinstance(c, ft.OutlinedButton) and c.content == "끄기")
    del_btn = next(c for c in _walk(row)
                   if isinstance(c, ft.OutlinedButton) and c.content == "삭제")
    off_btn.on_click(None)
    del_btn.on_click(None)
    # 켜져있던 예약을 '끄기' → enable=False 로 콜백
    assert calls["toggle"] == [("KNOU_요약", False)]
    assert calls["delete"] == ["KNOU_요약"]


def test_build_schedule_view_offline(tmp_path):
    # 스냅샷·스케줄러 조회 없이도 예외 없이 빌드되어야 함(page=None → schtasks 미호출)
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    assert isinstance(view, ft.Column)
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    assert len(dds) == 3                      # 모드·과목·차시
    tfs = _textfields(view)
    assert any(t.value == "02:00" for t in tfs)   # 기본 실행 시각


def test_schedule_view_has_freq_radios(tmp_path):
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    radios = [c for c in _walk(view) if isinstance(c, ft.Radio)]
    assert {r.value for r in radios} == {"DAILY", "ONCE"}


def test_schedule_view_mode_toggles_sleep_note(tmp_path):
    # 이수/전체 모드를 고르면 절전 주의 안내가 노출(요약에선 숨김)
    from runner import watch_sleep_warning
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    mode_dd = next(c for c in _walk(view) if isinstance(c, ft.Dropdown))
    warns = [c for c in _walk(view)
             if isinstance(c, ft.Text) and c.value == watch_sleep_warning()]
    assert len(warns) == 1
    assert warns[0].visible is False          # 기본 요약 → 숨김
    mode_dd.value = "이수"
    mode_dd.on_select(None)
    assert warns[0].visible is True
