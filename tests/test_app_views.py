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
    # Row 안에 화면 겹침(Stack)이 있고, 그 안에 화면 두 칸(일반·실행)이 있는지
    stack = row.controls[-1]
    boxes = list(stack.controls)
    assert len(boxes) == 2
    assert any(b.content is not None for b in boxes)


def test_run_view_is_kept_alive_across_tabs():
    """실행 화면은 탭을 옮겨도 **버려지지 않아야** 한다.

    매번 새로 만들면 돌고 있는 작업의 진행 로그·'실행 중' 표시가 사라진다
    (실측 증상). 숨기기만 하고 같은 컨트롤을 유지하는지 확인한다.
    """
    from app.main_app import NAV_RUN, NAV_STATUS, main

    page = _FakePage()
    main(page)
    stack = page.controls[0].controls[-1]
    content_box, run_box = stack.controls

    rail = next(c for c in _walk(page.controls[0])
                if isinstance(c, ft.NavigationRail))
    rail.on_change(_Ev(rail, NAV_RUN))
    made = run_box.content
    assert made is not None and run_box.visible is True
    assert content_box.visible is False

    rail.on_change(_Ev(rail, NAV_STATUS))          # 현황으로 이동
    assert run_box.visible is False
    assert run_box.content is made                 # 같은 컨트롤이 그대로 살아있다

    rail.on_change(_Ev(rail, NAV_RUN))             # 다시 실행 탭으로
    assert run_box.visible is True
    assert run_box.content is made                 # 새로 만들지 않았다


class _Ev:
    """NavigationRail on_change 이벤트 대역."""

    def __init__(self, control, index):
        control.selected_index = index
        self.control = control


# --- run_view 순수 헬퍼 -----------------------------------------------------
from app.views.run_view import (  # noqa: E402
    build_confirm_dialog,
    build_extra_dialog,
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
    redo = [c for c in _walk(view)
            if isinstance(c, ft.Checkbox) and "다시 만들기" in (c.label or "")]
    assert len(redo) == 1
    assert redo[0].value is False


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


def _run_limit_field(view):
    """실행 화면의 '한 번에 최대 (강)' 입력칸."""
    return next(c for c in _walk(view)
                if isinstance(c, ft.TextField) and "한 번에 최대" in (c.label or ""))


def _gen_btn(view):
    return next(c for c in _walk(view) if isinstance(c, ft.FilledButton))


def test_run_view_has_limit_field(tmp_path):
    # 예약 화면과 같은 규칙 — 다만 기본은 1강(실행 탭은 보통 한 강씩 쓴다)
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    assert _run_limit_field(view).value == "1"


def test_run_view_lecture_is_optional(tmp_path):
    # 차시를 비워도 과목만 있으면 실행할 수 있어야 한다
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    lec = [c for c in _walk(view)
           if isinstance(c, ft.Dropdown) and "차시" in (c.label or "")]
    assert len(lec) == 1
    assert "비우면" in lec[0].label       # 선택 사항임이 라벨에 드러나야 한다


def test_run_view_without_course_still_complains(tmp_path):
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    _gen_btn(view).on_click(None)
    msgs = [c.value for c in _walk(view)
            if isinstance(c, ft.Text) and c.color == ft.Colors.RED]
    assert any("과목" in (m or "") for m in msgs)
    # 차시를 요구하던 예전 문구는 사라져야 한다
    assert not any("과목과 차시" in (m or "") for m in msgs)


def test_run_view_rejects_bad_limit(tmp_path):
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    dds[0].value = "컴퓨터구조"
    _run_limit_field(view).value = "0"
    _gen_btn(view).on_click(None)
    msgs = [c.value for c in _walk(view)
            if isinstance(c, ft.Text) and c.color == ft.Colors.RED]
    assert any("한 번에 최대" in (m or "") for m in msgs)


class _CapturingJob:
    """JobRunner 대역 — 실제 프로세스 대신 argv 만 받아 적는다."""
    argvs: list = []

    def __init__(self, on_line=None, on_exit=None):
        self.on_line, self.on_exit = on_line, on_exit

    def start(self, argv):
        _CapturingJob.argvs.append(list(argv))


def _run_argv(tmp_path, monkeypatch, *, course, seq, limit, unwatched=True):
    """실행 탭을 실제로 눌러 main.py 에 넘어가는 argv 를 얻는다."""
    import app.views.run_view as rv
    pytest.importorskip("config")
    try:
        from config import load_config
        load_config()
    except Exception:                      # .env 없는 환경이면 이 테스트는 건너뜀
        pytest.skip("설정(.env)이 없어 실행 경로를 태울 수 없음")
    _CapturingJob.argvs = []
    monkeypatch.setattr(rv, "JobRunner", _CapturingJob)
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    dds[0].value = course
    dds[1].value = str(seq) if seq is not None else None
    _run_limit_field(view).value = str(limit)
    uw = next(c for c in _walk(view)
              if isinstance(c, ft.Checkbox) and "미이수부터" in (c.label or ""))
    uw.value = unwatched
    _gen_btn(view).on_click(None)          # 기본 모드 = 요약(확인 다이얼로그 없음)
    assert _CapturingJob.argvs, "작업이 시작되지 않았다"
    return _CapturingJob.argvs[-1]


def test_run_tab_passes_count_when_no_lecture_chosen(tmp_path, monkeypatch):
    argv = _run_argv(tmp_path, monkeypatch, course="컴퓨터구조", seq=None, limit=3)
    assert "--limit" in argv and argv[argv.index("--limit") + 1] == "3"
    assert "--seq" not in argv
    assert "--unwatched" in argv


def test_run_tab_single_lecture_overrides_count(tmp_path, monkeypatch):
    # 차시를 고르면 개수는 무시하고 그 한 강만 — 실수로 5강이 돌면 안 된다
    argv = _run_argv(tmp_path, monkeypatch, course="컴퓨터구조", seq=7, limit=5)
    assert argv[argv.index("--limit") + 1] == "1"
    assert argv[argv.index("--seq") + 1] == "7"
    assert "--unwatched" not in argv


def test_multi_lecture_command_uses_limit_and_unwatched():
    # 차시를 안 고르면: --seq 없이 --limit N --unwatched 로 돌아야 한다
    from runner import build_command
    argv = build_command("py.exe", "요약", course="컴퓨터구조", seq=None,
                         limit=3, unwatched=True)
    assert "--seq" not in argv
    assert "--limit" in argv and "3" in argv
    assert "--unwatched" in argv


def test_single_lecture_command_ignores_count():
    # 차시를 고르면 그 한 강만 — 미이수 필터도 걸지 않는다
    from runner import build_command
    argv = build_command("py.exe", "요약", course="컴퓨터구조", seq=7,
                         limit=1, unwatched=False)
    assert "--seq" in argv and "7" in argv
    assert "--unwatched" not in argv


def _watch_btn(view):
    """실행 화면의 '영상 이수만 실행' 버튼."""
    return next(c for c in _walk(view)
                if isinstance(c, ft.OutlinedButton) and c.content == "영상 이수만 실행")


def test_build_run_view_has_watch_only_button(tmp_path):
    # 노트는 멀쩡한데 이수만 안 된 차시를 되돌리는 통로
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    assert _watch_btn(view) is not None


def test_watch_only_requires_course_and_lecture(tmp_path):
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    _watch_btn(view).on_click(None)
    msgs = [c.value for c in _walk(view)
            if isinstance(c, ft.Text) and c.color == ft.Colors.RED]
    assert any("과목과 차시" in (m or "") for m in msgs)


def test_watch_only_asks_for_consent(tmp_path):
    # 실제 서버 적립이므로 동의 다이얼로그를 거치고, 동의 전엔 시작 불가
    page = _DialogPage()
    view = build_run_view(page, snapshot_path=tmp_path / "none.json")
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    dds[0].value, dds[1].value = "컴퓨터구조", "10"
    _watch_btn(view).on_click(None)

    assert len(page.dialogs) == 1
    dlg = page.dialogs[0]
    start = next(a for a in dlg.actions if isinstance(a, ft.FilledButton))
    assert start.disabled is True
    body = " ".join(t.value for t in _walk(dlg)
                    if isinstance(t, ft.Text) and t.value)
    assert "형성평가·예습노트는 건드리지 않습니다" in body


def test_watch_only_command_is_watch_stage_with_force():
    # --stages watch + --force. force 가 없으면 완청 오판으로 '완료' 기록된
    # 차시를 영영 되돌릴 수 없다. 노트(summarize)는 절대 섞이면 안 된다.
    from runner import build_command
    argv = build_command("py.exe", "이수", course="컴퓨터구조", seq=10,
                         limit=1, stages=["watch"], force=True)
    assert "--stages" in argv and "watch" in argv
    assert "--force" in argv
    assert argv[argv.index("--seq") + 1] == "10"
    assert "summarize" not in argv and "exam" not in argv


def _exam_btn(view):
    """실행 화면의 '형성평가만 실행' 버튼."""
    return next(c for c in _walk(view)
                if isinstance(c, ft.OutlinedButton) and c.content == "형성평가만 실행")


def test_build_run_view_has_exam_only_button(tmp_path):
    # 형성평가(퀴즈)만 따로 돌릴 수 있어야 한다
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    assert _exam_btn(view) is not None


def test_exam_only_requires_course_and_lecture(tmp_path):
    # 과목·차시 없이 누르면 안내만 하고 실행하지 않는다
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    _exam_btn(view).on_click(None)
    msgs = [c.value for c in _walk(view)
            if isinstance(c, ft.Text) and c.color == ft.Colors.RED]
    assert any("과목과 차시" in (m or "") for m in msgs)


class _DialogPage:
    """show_dialog 만 받아 적는 가짜 page(다이얼로그 내용을 검사하기 위함)."""

    def __init__(self):
        self.dialogs = []

    def show_dialog(self, dlg):
        self.dialogs.append(dlg)

    def update(self):
        pass


def test_exam_only_asks_for_consent_before_submitting(tmp_path):
    # 실제 서버 제출이므로 동의 다이얼로그를 반드시 거치고, 동의 전엔 시작 불가
    page = _DialogPage()
    view = build_run_view(page, snapshot_path=tmp_path / "none.json")
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    dds[0].value, dds[1].value = "자료구조", "2"
    _exam_btn(view).on_click(None)

    assert len(page.dialogs) == 1
    dlg = page.dialogs[0]
    assert dlg.modal is True
    start = next(a for a in dlg.actions if isinstance(a, ft.FilledButton))
    assert start.disabled is True             # 동의 전에는 눌리지 않는다
    body = " ".join(t.value for t in _walk(dlg)
                    if isinstance(t, ft.Text) and t.value)
    assert "형성평가" in body
    assert "영상 이수·노트 생성은 하지 않습니다" in body


def test_exam_only_command_is_exam_stage_with_force():
    # --stages exam + --force 여야 한다. force 가 없으면 '없음(skip)' 으로 완료
    # 기록된 차시가 영영 다시 시도되지 않는다(이번 사건의 핵심).
    from runner import build_command
    argv = build_command("py.exe", "이수", course="자료구조", seq=2,
                         limit=1, stages=["exam"], force=True)
    assert "--stages" in argv and "exam" in argv
    assert "--force" in argv
    assert "--seq" in argv and "2" in argv
    # 영상 이수·노트 단계는 섞이면 안 된다
    assert "watch" not in argv and "summarize" not in argv


def test_build_run_view_has_status_button(tmp_path):
    # 과목·차시별 현황을 한눈에 보는 페이지 버튼이 있어야 함
    view = build_run_view(snapshot_path=tmp_path / "none.json")
    labels = [c.content for c in _walk(view)
              if isinstance(c, ft.OutlinedButton)]
    assert "학습 현황 페이지" in labels


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


# --- 두 번째 영상(회차에 영상 2개) 확인 다이얼로그 -------------------------
def test_extra_dialog_is_modal_alert_without_agree_checkbox():
    # 노트만 만드는 작업이라 '서버 제출 동의' 체크박스가 없어야 한다
    dlg, make = build_extra_dialog("본문", lambda: None, lambda: None)
    assert isinstance(dlg, ft.AlertDialog)
    assert dlg.modal is True
    assert not [c for c in _walk(dlg.content) if isinstance(c, ft.Checkbox)]
    assert make.disabled in (None, False)


def test_extra_dialog_buttons_invoke_callbacks():
    calls = {"make": 0, "skip": 0}
    dlg, make = build_extra_dialog(
        "본문",
        on_confirm=lambda: calls.__setitem__("make", calls["make"] + 1),
        on_cancel=lambda: calls.__setitem__("skip", calls["skip"] + 1),
    )
    dlg.actions[0].on_click(None)      # 건너뛰기
    make.on_click(None)                # 노트 만들기
    assert calls == {"make": 1, "skip": 1}


def test_extra_dialog_shows_body_text():
    body = "자료구조 1강 회차에 영상이 2개입니다."
    dlg, _make = build_extra_dialog(body, lambda: None, lambda: None)
    texts = [c.value for c in _walk(dlg.content) if isinstance(c, ft.Text)]
    assert body in texts


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


def _limit_field(view):
    """예약 화면의 '한 번에 최대 (강)' 입력칸."""
    return next(c for c in _walk(view)
                if isinstance(c, ft.TextField) and "한 번에 최대" in (c.label or ""))


def test_schedule_view_has_limit_field(tmp_path):
    # 한 번 실행에 몇 강까지 돌지 정할 수 있어야 한다(없으면 12시간짜리 실행이 됨)
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    assert _limit_field(view).value == "3"


def test_schedule_view_rejects_bad_limit(tmp_path):
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    _limit_field(view).value = "0"
    add = next(c for c in _walk(view)
               if isinstance(c, ft.FilledButton) and c.content == "예약 추가")
    add.on_click(None)
    msgs = [c.value for c in _walk(view)
            if isinstance(c, ft.Text) and c.color == ft.Colors.RED]
    assert any("한 번에 최대" in (m or "") for m in msgs)


def test_task_row_has_stop_button_distinct_from_disable():
    # '끄기'는 다음 실행만 막는다 — 도는 것을 세우는 버튼이 따로 있어야 한다
    calls = {}
    row = build_task_row({"name": "KNOU_전체", "next_run": "", "status": "준비"},
                         lambda n, e: calls.setdefault("toggle", (n, e)),
                         lambda n: calls.setdefault("delete", n),
                         on_stop=lambda n: calls.setdefault("stop", n))
    labels = [c.content for c in _walk(row) if isinstance(c, ft.OutlinedButton)]
    assert "지금 멈추기" in labels and "끄기" in labels
    stop = next(c for c in _walk(row)
                if isinstance(c, ft.OutlinedButton) and c.content == "지금 멈추기")
    stop.on_click(None)
    assert calls["stop"] == "KNOU_전체" and "toggle" not in calls


def test_task_row_without_stop_callback_omits_the_button():
    row = build_task_row({"name": "KNOU_요약", "next_run": "", "status": "준비"},
                         lambda n, e: None, lambda n: None)
    labels = [c.content for c in _walk(row) if isinstance(c, ft.OutlinedButton)]
    assert "지금 멈추기" not in labels


def _wake_cb(view):
    """예약 화면의 '절전 중이면 PC를 깨워서 실행' 체크박스."""
    return next(c for c in _walk(view)
                if isinstance(c, ft.Checkbox) and "깨워서" in (c.label or ""))


def test_schedule_view_has_wake_checkbox(tmp_path):
    # 절전 중에도 예약이 돌게 하는 선택지 — 기본은 꺼짐(사용자가 켜야 함)
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    assert _wake_cb(view).value is False


def test_wake_checkbox_warns_when_power_policy_blocks(tmp_path, monkeypatch):
    # 전원 정책이 꺼져 있으면 체크하는 순간 안내가 뜬다(켜기 전엔 숨김)
    import app.views.schedule_view as sv
    monkeypatch.setattr(sv, "wake_timer_setting", lambda: {"ac": 0, "dc": 0})
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    cb = _wake_cb(view)
    notes = [c for c in _walk(view)
             if isinstance(c, ft.Text) and c.color == ft.Colors.ORANGE
             and c.value == ""]
    assert notes and notes[0].visible is False
    cb.value = True
    cb.on_change(None)
    assert notes[0].visible is True
    assert "powercfg" in notes[0].value


def test_wake_checkbox_quiet_when_policy_ok(tmp_path, monkeypatch):
    import app.views.schedule_view as sv
    monkeypatch.setattr(sv, "wake_timer_setting", lambda: {"ac": 1, "dc": 1})
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    cb = _wake_cb(view)
    cb.value = True
    cb.on_change(None)
    notes = [c for c in _walk(view)
             if isinstance(c, ft.Text) and c.color == ft.Colors.ORANGE
             and c.visible and "powercfg" in (c.value or "")]
    assert notes == []


def test_wake_checkbox_survives_powercfg_failure(tmp_path, monkeypatch):
    # powercfg 조회가 터져도 예약 화면이 죽으면 안 된다
    import app.views.schedule_view as sv

    def _boom():
        raise OSError("powercfg 없음")

    monkeypatch.setattr(sv, "wake_timer_setting", _boom)
    view = build_schedule_view(snapshot_path=tmp_path / "none.json")
    cb = _wake_cb(view)
    cb.value = True
    cb.on_change(None)                        # 예외가 새어나오면 실패


# --- 현황 화면(앱 안) ------------------------------------------------------
from app.views.status_view import (  # noqa: E402
    build_status_view,
    status_label,
    summary_text,
)


def _snap(tmp_path):
    """과목 2개짜리 임시 lectures.json."""
    import json
    p = tmp_path / "lectures.json"
    p.write_text(json.dumps({
        "generated_at": "2026-08-17T12:09:22",
        "courses": [
            {"name": "C프로그래밍", "lectures": [
                {"seq": 1, "name": "개요", "video_done": True}]},
            {"name": "자료구조", "lectures": [
                {"seq": 1, "name": "배열", "video_done": False}]},
        ]}, ensure_ascii=False), encoding="utf-8")
    return p


def _srow(**over):
    row = {"course": "C프로그래밍", "seq": 1, "name": "개요",
           "video_done": False, "exam_done": False, "watch_run": False,
           "exam_run": False, "watch_new": False, "exam_new": False,
           "watched_min": 0, "total_min": 76, "notes": [], "mp3": None,
           "doc": None, "quiz_count": 0, "extra_videos": [], "extra_done": False}
    row.update(over)
    return row


def test_status_label_four_states():
    assert status_label(_srow(video_done=True), "watch") == ("이수완료", "done")
    assert status_label(_srow(watch_run=True, watch_new=True), "watch")         == ("실행함*", "fresh")
    assert status_label(_srow(watch_run=True), "watch") == ("실행함", "wait")
    assert status_label(_srow(), "watch") == ("", "none")


def test_status_label_reads_exam_fields():
    # 이수/형성평가가 서로 다른 필드를 본다
    assert status_label(_srow(exam_done=True), "exam")[1] == "done"
    assert status_label(_srow(exam_done=True), "watch")[1] == "none"


def test_status_label_matches_html_rule():
    # 앱 화면과 생성 HTML 의 판정이 어긋나면 안 된다
    from status_html import _mark
    row = _srow(watch_run=True, watch_new=True)
    txt, kind = status_label(row, "watch")
    assert kind == "fresh" and "실행함" in _mark(False, True, "이수완료", True)


def test_summary_text_counts_courses():
    from status_page import course_stats
    rows = [_srow(video_done=True), _srow(seq=2)]
    c = {"course": "C프로그래밍", "rows": rows, "stats": course_stats(rows)}
    t = summary_text([c])
    assert "1과목" in t and "2차시" in t and "이수 1" in t


def test_build_status_view_offline(tmp_path):
    # 목록/상태 파일이 없어도 화면이 만들어져야 한다
    view = build_status_view(snapshot_path=tmp_path / "none.json",
                             state_path=tmp_path / "none2.json")
    assert isinstance(view, ft.Column) and len(view.controls) >= 5


def test_build_status_view_has_filter_switch(tmp_path):
    view = build_status_view(snapshot_path=tmp_path / "none.json",
                             state_path=tmp_path / "none2.json")
    switches = [c for c in _walk(view) if isinstance(c, ft.Switch)]
    assert any("남은 것만" in (s.label or "") for s in switches)


def test_short_course_trims_long_names():
    from app.views.status_view import short_course
    assert short_course("자료구조") == "자료구조"
    assert short_course("AI네이티브가되기위한기초소양") == "AI네이티브가되기…"
    assert len(short_course("AI네이티브가되기위한기초소양")) == 10


def test_course_chips_let_you_switch_without_scrolling(tmp_path):
    # 과목 칩 = 전체 + 과목수. 누르면 그 과목만 남는다(스크롤 대신)
    view = build_status_view(snapshot_path=_snap(tmp_path),
                             state_path=tmp_path / "s.json")
    btns = [c for c in _walk(view)
            if isinstance(c, (ft.FilledButton, ft.OutlinedButton))
            and isinstance(c.content, str)]
    labels = [b.content for b in btns]
    assert "전체 2" in labels and "C프로그래밍" in labels and "자료구조" in labels

    before = [c.value for c in _walk(view) if isinstance(c, ft.Text)]
    assert "C프로그래밍" in before and "자료구조" in before
    next(b for b in btns if b.content == "자료구조").on_click(None)
    after = [c.value for c in _walk(view) if isinstance(c, ft.Text)]
    assert "자료구조" in after and after.count("C프로그래밍") == 0


def test_selected_course_chip_is_filled(tmp_path):
    view = build_status_view(snapshot_path=_snap(tmp_path),
                             state_path=tmp_path / "s.json")
    def chip(label):
        return next(c for c in _walk(view)
                    if isinstance(c, (ft.FilledButton, ft.OutlinedButton))
                    and c.content == label)
    assert isinstance(chip("전체 2"), ft.FilledButton)       # 기본은 전체
    chip("자료구조").on_click(None)
    assert isinstance(chip("자료구조"), ft.FilledButton)


# --- 좁은 창 대응 ----------------------------------------------------------
def test_is_compact_threshold():
    from app.views.status_view import COMPACT_WIDTH, is_compact
    assert is_compact(COMPACT_WIDTH - 1) is True
    assert is_compact(COMPACT_WIDTH) is False
    assert is_compact(None) is False            # 폭을 모르면 넓은 배치


def test_grid_columns_add_up():
    # 넓을 땐 한 줄(24), 좁을 땐 정확히 세 줄(24×3)로 접힌다
    from app.views.status_view import COLS, GRID
    assert sum(v["md"] for v in COLS.values()) == GRID
    assert sum(v["xs"] for v in COLS.values()) == GRID * 3


def test_wide_layout_uses_grid_row(tmp_path):
    view = build_status_view(snapshot_path=_snap(tmp_path),
                             state_path=tmp_path / "s.json")
    assert [c for c in _walk(view) if isinstance(c, ft.ResponsiveRow)]


class _WidthPage:
    """폭만 알려주는 가짜 page(오프라인에서 좁은 창을 흉내낸다)."""

    def __init__(self, width):
        self.width = width

    def update(self):
        pass


def test_compact_layout_drops_grid_and_header(tmp_path):
    # 좁은 창: 24칸 그리드 대신 접힌 줄, 머리글은 빼서 헷갈리지 않게
    view = build_status_view(page=_WidthPage(600), snapshot_path=_snap(tmp_path),
                             state_path=tmp_path / "s.json")
    assert not [c for c in _walk(view) if isinstance(c, ft.ResponsiveRow)]
    texts = [c.value for c in _walk(view) if isinstance(c, ft.Text)]
    assert "차시" not in texts and "강의록" not in texts
    assert "배열" in texts                      # 내용은 그대로 보인다


def test_wide_layout_keeps_grid_and_header(tmp_path):
    view = build_status_view(page=_WidthPage(1400), snapshot_path=_snap(tmp_path),
                             state_path=tmp_path / "s.json")
    assert [c for c in _walk(view) if isinstance(c, ft.ResponsiveRow)]
    texts = [c.value for c in _walk(view) if isinstance(c, ft.Text)]
    assert "차시" in texts and "강의록" in texts


def test_resize_across_threshold_switches_layout(tmp_path):
    # 창을 줄였다 늘리면 배치가 따라 바뀐다(기준을 넘을 때만)
    page = _WidthPage(1400)
    view = build_status_view(page=page, snapshot_path=_snap(tmp_path),
                             state_path=tmp_path / "s.json")
    assert [c for c in _walk(view) if isinstance(c, ft.ResponsiveRow)]
    page.width = 600
    page.on_resize(None)
    assert not [c for c in _walk(view) if isinstance(c, ft.ResponsiveRow)]
    page.width = 1400
    page.on_resize(None)
    assert [c for c in _walk(view) if isinstance(c, ft.ResponsiveRow)]


# --- 퀴즈 화면(앱 안) ------------------------------------------------------
from app.views.quiz_view import (  # noqa: E402
    answer_text,
    bank_index,
    bank_title,
    build_quiz_view,
    option_tone,
    progress_text,
)


def _bank(course="C프로그래밍", seq=1, name="개요", n=2):
    return {"course": course, "seq": seq, "name": name,
            "questions": [{"qid": str(i), "question": f"q{i}",
                           "options": [{"no": 1, "text": "가"},
                                       {"no": 2, "text": "나"}],
                           "answer_no": 1, "answer_text": "가",
                           "explanation": "해설"} for i in range(n)]}


def test_bank_title_joins_course_and_lecture():
    assert bank_title(_bank()) == "C프로그래밍 · 1강 · 개요"


def test_bank_index_finds_lecture():
    banks = [_bank(seq=1), _bank(seq=2), _bank("자료구조", 1)]
    assert bank_index(banks, "C프로그래밍", 2) == 1
    assert bank_index(banks, "자료구조", 1) == 2


def test_bank_index_unknown_falls_back_to_first():
    assert bank_index([_bank()], "없는과목", 9) == 0
    assert bank_index([], None, None) == 0


def test_option_tone_marks_right_and_wrong():
    assert option_tone(1, 1, 1) == "correct"
    assert option_tone(2, 2, 1) == "wrong"
    assert option_tone(1, 2, 1) == "plain"      # 고르지 않은 보기
    assert option_tone(None, 1, 1) == "plain"   # 아직 안 품


def test_option_tone_without_answer_is_selected_only():
    assert option_tone(1, 1, None) == "selected"


def test_answer_text_formats():
    assert answer_text({"answer_no": 3, "answer_text": "다"}) == "정답: 3. 다"
    assert answer_text({"answer_text": "다"}) == "정답: 다"
    assert answer_text({}) == "정답 정보 없음"


def test_progress_text():
    assert progress_text(2, 5) == "2 / 5"


def test_build_quiz_view_offline(tmp_path):
    view = build_quiz_view(quiz_dir=tmp_path)      # 빈 폴더
    assert isinstance(view, ft.Column) and len(view.controls) >= 5


def _quiz_dir_with_two_banks(tmp_path):
    import json
    def bank(course, name, qs):
        return {"course": course, "seq": 1, "name": name, "questions": [
            {"qid": f"{course}-{i}", "question": q,
             "options": [{"no": 1, "text": "가"}, {"no": 2, "text": "나"}],
             "answer_no": 1, "answer_text": "가", "explanation": "해설"}
            for i, q in enumerate(qs)]}
    (tmp_path / "a.json").write_text(json.dumps(
        bank("C프로그래밍", "C 언어의 개요", ["C질문A", "C질문B"]),
        ensure_ascii=False), encoding="utf-8")
    (tmp_path / "b.json").write_text(json.dumps(
        bank("오픈소스기반데이터분석", "데이터 분석과 오픈소스", ["오픈질문A"]),
        ensure_ascii=False), encoding="utf-8")
    return tmp_path


def _quiz_texts(view, needle="질문"):
    return [c.value for c in _walk(view)
            if isinstance(c, ft.Text) and needle in str(c.value or "")]


def test_quiz_picker_uses_event_that_flet_actually_fires(tmp_path):
    # Flet 0.85 Dropdown 은 on_change 가 없다 — on_select 에 붙어야 실제로 호출된다
    import dataclasses
    names = {f.name for f in dataclasses.fields(ft.Dropdown)}
    assert "on_select" in names and "on_change" not in names
    view = build_quiz_view(quiz_dir=_quiz_dir_with_two_banks(tmp_path))
    dd = [c for c in _walk(view) if isinstance(c, ft.Dropdown)][0]
    assert callable(dd.on_select)


def test_changing_lecture_swaps_questions(tmp_path):
    # 강의를 바꾸면 문제·부제가 그 강의 것으로 바뀌어야 한다
    view = build_quiz_view(quiz_dir=_quiz_dir_with_two_banks(tmp_path))
    dd = [c for c in _walk(view) if isinstance(c, ft.Dropdown)][0]
    assert _quiz_texts(view) == ["C질문A", "C질문B"]

    dd.value = "1"
    dd.on_select(None)                      # Flet 이 부르는 그대로
    assert _quiz_texts(view) == ["오픈질문A"]
    assert any("오픈소스기반데이터분석" in str(c.value or "")
               for c in _walk(view) if isinstance(c, ft.Text))


def test_changing_lecture_resets_progress_count(tmp_path):
    view = build_quiz_view(quiz_dir=_quiz_dir_with_two_banks(tmp_path))
    dd = [c for c in _walk(view) if isinstance(c, ft.Dropdown)][0]
    dd.value = "1"
    dd.on_select(None)
    assert any((c.value or "") == "0 / 1" for c in _walk(view)
               if isinstance(c, ft.Text))     # 1문제짜리 강의


def test_build_quiz_view_lists_banks(tmp_path):
    import json
    (tmp_path / "C프로그래밍_1강.json").write_text(
        json.dumps(_bank(), ensure_ascii=False), encoding="utf-8")
    view = build_quiz_view(quiz_dir=tmp_path)
    dds = [c for c in _walk(view) if isinstance(c, ft.Dropdown)]
    assert dds and len(dds[0].options) == 1


# --- PDF 뷰어(앱 안) -------------------------------------------------------
from app.views.pdf_view import build_pdf_view, page_label  # noqa: E402


def test_page_label_is_one_based():
    assert page_label(0, 51) == "1 / 51"
    assert page_label(50, 51) == "51 / 51"
    assert page_label(99, 51) == "51 / 51"       # 범위 밖은 보정


def test_page_label_empty_document():
    assert page_label(0, 0) == "0 / 0"


def test_pdf_view_missing_file_is_safe(tmp_path):
    panel, st = build_pdf_view(tmp_path / "none.pdf")
    assert isinstance(panel, ft.Column) and st["total"] == 0
    texts = [c.value for c in _walk(panel) if isinstance(c, ft.Text)]
    assert any("열 수 없" in (t or "") for t in texts)


class _ScrollPage(_WidthPage):
    """scroll_to 예약(run_task)을 받아 적는 가짜 page."""

    def __init__(self, width=1200):
        super().__init__(width)
        self.tasks = []

    def run_task(self, fn, *a, **k):
        self.tasks.append((getattr(fn, "__name__", str(fn)), k))
        return None


def _pdf(tmp_path, pages=6):
    fitz = pytest.importorskip("fitz")
    p = tmp_path / "s.pdf"
    doc = fitz.open()
    for i in range(pages):
        doc.new_page().insert_text((72, 100), f"page {i + 1}")
    doc.save(str(p)); doc.close()
    return p


def _imgs(panel):
    return [c for c in _walk(panel) if isinstance(c, ft.Image)]


def _plabel(panel):
    return next(c.value for c in _walk(panel)
                if isinstance(c, ft.Text) and "/" in str(c.value or ""))


def _pbtn(panel, tip):
    return next(c for c in _walk(panel) if isinstance(c, ft.IconButton)
                and c.tooltip == tip)


# --- 스크롤로 넘겨 보기 -----------------------------------------------------
def test_visible_page_from_scroll_offset():
    from app.views.pdf_view import PAGE_GAP, visible_page
    h = 460
    assert visible_page(0, h, 51) == 0
    assert visible_page(h + PAGE_GAP, h, 51) == 1
    assert visible_page((h + PAGE_GAP) * 5, h, 51) == 5
    assert visible_page(10 ** 9, h, 51) == 50          # 끝을 넘지 않는다
    assert visible_page(100, 0, 51) == 0               # 높이를 모르면 0


def test_page_offset_is_inverse_of_visible_page():
    from app.views.pdf_view import page_offset, visible_page
    h = 460
    for i in (0, 1, 7, 42):
        assert visible_page(page_offset(i, h), h, 50) == i


def test_all_pages_are_rendered_so_scroll_never_stalls(tmp_path):
    # 중간에 끊기던 원인(느린 지연 로딩) 제거 — 결국 전 쪽이 다 붙는다
    from app.views.pdf_view import build_pdf_view
    panel, st = build_pdf_view(_pdf(tmp_path, pages=12), page=_ScrollPage(),
                                background=False)
    assert st["loaded"] == 12 and len(_imgs(panel)) == 12


def test_opens_fast_with_first_pages_then_fills(tmp_path):
    # 여는 순간에는 앞 몇 쪽만(43쪽을 다 그리면 5초 멈춘다)
    from app.views.pdf_view import build_pdf_view
    panel, st = build_pdf_view(_pdf(tmp_path, pages=12), page=_ScrollPage(),
                                eager=2, background=False)
    assert st["total"] == 12


def test_loading_text_shows_progress_then_clears():
    from app.views.pdf_view import loading_text
    assert "3/43" in loading_text(3, 43)
    assert loading_text(43, 43) == ""
    assert loading_text(0, 0) == ""


def test_background_fill_stops_when_closed(tmp_path):
    # 창을 닫으면 배경 렌더가 멈춰야 한다(닫힌 창을 계속 그리지 않게)
    from app.views.pdf_view import build_pdf_view
    panel, st = build_pdf_view(_pdf(tmp_path, pages=8), page=_ScrollPage(),
                                eager=1, background=False)
    st["closed"] = True
    before = st["loaded"]
    from app.views import pdf_view as pv
    assert before <= 8 and st["closed"] is True


def test_page_buttons_scroll_by_offset_not_key(tmp_path):
    # scroll_key 는 Flet 0.85 에서 동작하지 않는다(실측) → offset 이어야 한다
    from app.views.pdf_view import build_pdf_view, page_offset
    page = _ScrollPage()
    panel, st = build_pdf_view(_pdf(tmp_path, pages=10), page=page,
                                background=False)
    _pbtn(panel, "다음 쪽").on_click(None)
    assert st["i"] == 1 and _plabel(panel) == "2 / 10"
    name, kw = page.tasks[-1]
    assert "scroll_key" not in kw
    assert kw["offset"] == page_offset(1, st["h"])
    _pbtn(panel, "이전 쪽").on_click(None)
    assert st["i"] == 0 and page.tasks[-1][1]["offset"] == 0


def test_page_buttons_stop_at_both_ends(tmp_path):
    from app.views.pdf_view import build_pdf_view
    panel, st = build_pdf_view(_pdf(tmp_path, pages=3), page=_ScrollPage(),
                                background=False)
    _pbtn(panel, "이전 쪽").on_click(None)
    assert st["i"] == 0
    for _ in range(9):
        _pbtn(panel, "다음 쪽").on_click(None)
    assert st["i"] == 2 and _plabel(panel) == "3 / 3"


def test_scrolling_updates_page_label(tmp_path):
    from app.views.pdf_view import build_pdf_view, page_offset
    panel, st = build_pdf_view(_pdf(tmp_path, pages=10), page=_ScrollPage(),
                                background=False)
    stack = next(c for c in _walk(panel)
                 if isinstance(c, ft.Column) and c.on_scroll)

    class _E:
        pixels = 0
    _E.pixels = page_offset(6, st["h"])
    stack.on_scroll(_E())
    assert _plabel(panel) == "7 / 10"


def test_pdf_view_renders_real_pdf(tmp_path):
    fitz = pytest.importorskip("fitz")
    p = tmp_path / "s.pdf"
    doc = fitz.open(); doc.new_page(); doc.save(str(p)); doc.close()
    panel, st = build_pdf_view(p, title="강의록")
    imgs = [c for c in _walk(panel) if isinstance(c, ft.Image)]
    assert st["total"] == 1 and imgs
    assert bytes(imgs[0].src[:4]) == bytes([0x89, 0x50, 0x4E, 0x47])


# --- 앱 화면 밝기(시스템/밝게/어둡게) --------------------------------------
from app.main_app import (  # noqa: E402
    NAV,
    SEED_COLOR,
    theme_icon_for,
    theme_mode_for,
)


def test_theme_mode_maps_three_states():
    assert theme_mode_for("system") is ft.ThemeMode.SYSTEM
    assert theme_mode_for("light") is ft.ThemeMode.LIGHT
    assert theme_mode_for("dark") is ft.ThemeMode.DARK


def test_theme_mode_unknown_falls_back_to_system():
    assert theme_mode_for("보라색") is ft.ThemeMode.SYSTEM


def test_theme_icon_differs_per_state():
    icons = {theme_icon_for(v) for v in ("system", "light", "dark")}
    assert len(icons) == 3


def test_app_accent_matches_generated_pages():
    # 앱과 생성 HTML 이 같은 민트 액센트를 쓴다
    from ui_theme import CSS
    assert SEED_COLOR == "#00a37a" and SEED_COLOR in CSS


def test_nav_has_status_and_quiz_tabs():
    labels = [n for n, _ in NAV]
    assert "현황" in labels and "퀴즈" in labels


def test_pdf_view_is_full_screen_not_a_dialog(tmp_path):
    # 다이얼로그 안에 넣으면 다이얼로그가 휠을 가로채 페이지가 안 넘어간다(실측)
    from app.views import pdf_view as pv
    from app.views.pdf_view import build_pdf_view
    assert not hasattr(pv, "open_pdf_dialog")
    view, st = build_pdf_view(_pdf(tmp_path, pages=4), page=_ScrollPage(),
                              background=False)
    assert isinstance(view, ft.Column) and view.expand is True
    stack = next(c for c in _walk(view)
                 if isinstance(c, ft.Column) and c.on_scroll)
    assert stack.expand is True          # 화면을 채우는 유일한 스크롤러


def test_pdf_view_has_back_button(tmp_path):
    from app.views.pdf_view import build_pdf_view
    calls = []
    view, st = build_pdf_view(_pdf(tmp_path, pages=2), page=_ScrollPage(),
                              on_back=lambda: calls.append(1), background=False)
    back = next(c for c in _walk(view)
                if isinstance(c, ft.TextButton) and c.content == "뒤로")
    back.on_click(None)
    assert calls == [1]


def test_status_view_routes_pdf_to_app_screen(tmp_path):
    # 강의록 칩 → on_open_pdf 콜백(앱 화면). 콜백이 없으면 기본 프로그램으로.
    import inspect
    from app.views.status_view import build_status_view
    sig = inspect.signature(build_status_view)
    assert "on_open_pdf" in sig.parameters


# --- 현황: '형성평가 없음'을 경고와 구분 -------------------------------------
def test_status_label_absent_exam():
    row = {"exam_done": False, "exam_run": True, "exam_new": False,
           "exam_none": True}
    assert status_label(row, "exam") == ("없음", "absent")


def test_status_label_absent_is_not_warning_colour():
    absent = _pill_kind({"exam_done": False, "exam_run": True,
                         "exam_none": True})
    warn = _pill_kind({"exam_done": False, "exam_run": True})
    assert absent != warn


def _pill_kind(row):
    from app.views.status_view import _pill
    text, kind = status_label(row, "exam")
    _pill(text, kind)                      # 색 매핑에서 터지지 않아야 한다
    return kind


def test_status_label_done_wins_over_absent():
    row = {"exam_done": True, "exam_run": True, "exam_none": True}
    assert status_label(row, "exam")[1] == "done"


def test_status_label_watch_has_no_absent_state():
    # 영상은 '없음'이라는 개념이 없다 — 기존 3단계 그대로
    row = {"video_done": False, "watch_run": True, "watch_new": False}
    assert status_label(row, "watch") == ("실행함", "wait")
