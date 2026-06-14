"""[schedule_view] 예약 화면 — Windows 작업 스케줄러에 자동 실행 등록.

모드(요약/이수/전체) + (선택)과목·차시 + 시각 + 반복(매일/한번)을 골라
`schedule_win.create_task` 로 작업 스케줄러에 등록한다. 앱·터미널이 꺼져 있어도
지정 시각에 `run_*.bat` 가 기존 `main.py` 를 구동한다. 기존 예약은 표로 보여주고
삭제할 수 있다.

⚠️ 이수/전체는 **실제 방송대 서버에 영상 이수가 적립되고 형성평가 답안이 제출되는
   동작**이며, 예약 시 사람이 보지 않는 시각에 자동 실행된다 → 등록 전 반드시 동의
   다이얼로그를 거친다.

순수 로직(시각검증·인자/스크립트 빌더·CSV 파서)은 schedule_win 에서 단위테스트.
이 뷰는 오프라인 스모크 + 실제 등록 수동 검증(기존 프로젝트 철학).
"""
from __future__ import annotations

import sys
import threading
from pathlib import Path

import flet as ft

from app.views.run_view import (  # noqa: E402
    MODE_FULL,
    MODE_SUMMARY,
    MODE_WATCH,
    build_confirm_dialog,
    course_names,
    lecture_option_text,
    load_snapshot_rows,
    rows_for_course,
)
from runner import confirm_message, requires_confirm, watch_sleep_warning  # noqa: E402
from schedule_win import (  # noqa: E402
    PROJECT_ROOT,
    create_task,
    delete_task,
    is_disabled_status,
    list_tasks,
    normalize_time,
    set_task_enabled,
    valid_time,
)

SNAPSHOT_PATH = PROJECT_ROOT / "lectures.json"

# 모드 → 드롭다운 표시문구
_MODE_OPTIONS = [
    (MODE_SUMMARY, "예습 노트 생성 (영상 이수 안 함)"),
    (MODE_WATCH, "영상 이수 + 형성평가 (⚠️ 실제 서버 제출 · 노트 없음)"),
    (MODE_FULL, "영상 이수 + 형성평가 + 예습 노트 (⚠️ 실제 서버 제출)"),
]
_FREQ_DAILY = "DAILY"
_FREQ_ONCE = "ONCE"


def _python_exe() -> str:
    """예약 .bat 가 쓸 파이썬(소스 실행 시 venv python). 패키징은 Phase 5 보정."""
    return sys.executable or "python"


def build_task_row(task: dict, on_toggle, on_delete) -> ft.Control:
    """등록된 예약 한 줄: 이름·다음 실행·상태 + **[끄기/켜기]·[삭제]** 버튼.

    page 없이도 만들어지는 순수 표현 함수(단위테스트 대상). 콜백:
      on_toggle(name, enable) : 끄기/켜기 클릭(enable=True 면 다시 켜기)
      on_delete(name)         : 삭제 클릭
    상태가 '사용 안 함'이면 회색·"(꺼짐)" 표시하고 버튼은 '켜기'로 바뀐다.
    """
    name = task.get("name", "")
    disabled = is_disabled_status(task.get("status", ""))
    toggle_icon = ft.Icons.PLAY_ARROW if disabled else ft.Icons.PAUSE
    toggle_label = "켜기" if disabled else "끄기"
    toggle_tip = ("예약 다시 켜기(매일 실행 재개)" if disabled
                  else "예약 잠시 끄기(삭제 안 함 · 언제든 다시 켤 수 있음)")
    sub = ft.Text(
        f"다음 실행: {task.get('next_run', '?')} · "
        f"상태: {task.get('status', '?')}"
        + ("  (꺼짐)" if disabled else ""),
        size=11,
        color=ft.Colors.ORANGE if disabled else ft.Colors.GREY)
    return ft.Row(
        [
            ft.Icon(ft.Icons.SCHEDULE, size=18,
                    color=ft.Colors.GREY if disabled else None),
            ft.Column([
                ft.Text(name, size=13, weight=ft.FontWeight.BOLD,
                        selectable=True),
                sub,
            ], spacing=1, expand=True),
            ft.OutlinedButton(toggle_label, icon=toggle_icon, tooltip=toggle_tip,
                              on_click=lambda e: on_toggle(name, disabled)),
            ft.OutlinedButton("삭제", icon=ft.Icons.DELETE_OUTLINE,
                              tooltip="이 예약을 완전히 삭제",
                              on_click=lambda e: on_delete(name)),
        ],
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def build_schedule_view(page=None, snapshot_path=SNAPSHOT_PATH) -> ft.Control:
    """예약 화면 컨트롤 트리. page 가 없으면(테스트) update·schtasks 조회를 건너뛴다."""
    state = {"rows": load_snapshot_rows(snapshot_path)}

    mode_dd = ft.Dropdown(
        label="모드", width=420, value=MODE_SUMMARY,
        options=[ft.dropdown.Option(key=k, text=t) for k, t in _MODE_OPTIONS],
    )
    course_dd = ft.Dropdown(label="과목 (선택 — 비우면 모드 기본 동작)",
                            width=360, options=[])
    lecture_dd = ft.Dropdown(label="차시 (선택)", width=420, options=[])
    unwatched_cb = ft.Checkbox(
        label="미이수만 처리 (과목을 안 고르면 전체 미이수 대상)", value=True)
    time_tf = ft.TextField(label="실행 시각 (HH:MM · 24시간)", value="02:00",
                           width=200)
    freq_group = ft.RadioGroup(
        value=_FREQ_DAILY,
        content=ft.Row([
            ft.Radio(value=_FREQ_DAILY, label="매일"),
            ft.Radio(value=_FREQ_ONCE, label="한 번"),
        ]),
    )
    highest_cb = ft.Checkbox(
        label="최고 권한으로 실행 (앱을 '관리자 권한으로 실행'한 경우에만)",
        value=False)
    guide_note = ft.Text(
        "※ 예약은 현재 Windows 사용자 계정으로 실행됩니다. 지정 시각에 PC가 "
        "켜져 있고 로그인되어 있어야 하며(절전 금지), 같은 조건의 예약을 다시 "
        "추가하면 기존 예약을 덮어씁니다. 일반 권한이면 '최고 권한'은 자동으로 "
        "꺼져 등록됩니다.", size=11, color=ft.Colors.GREY)
    add_btn = ft.FilledButton("예약 추가", icon=ft.Icons.ALARM_ADD)
    refresh_btn = ft.OutlinedButton("목록 새로고침", icon=ft.Icons.REFRESH)
    status = ft.Text("", size=13)
    sleep_note = ft.Text(watch_sleep_warning(), size=12, color=ft.Colors.ORANGE,
                         visible=False)
    table = ft.Column([], spacing=6)

    def _safe_update():
        if page is not None:
            try:
                page.update()
            except Exception:
                pass

    def set_status(text, color=None):
        status.value = text
        status.color = color
        _safe_update()

    # --- 과목/차시 채우기 --------------------------------------------------
    def populate_lectures(*_):
        rows = rows_for_course(state["rows"], course_dd.value)
        lecture_dd.options = [
            ft.dropdown.Option(key=str(r.seq), text=lecture_option_text(r))
            for r in rows
        ]
        lecture_dd.value = None
        _safe_update()

    def populate_courses():
        names = course_names(state["rows"])
        course_dd.options = [ft.dropdown.Option(key=n, text=n) for n in names]

    course_dd.on_select = populate_lectures

    # --- 기존 예약 표 ------------------------------------------------------
    def _row_control(task: dict) -> ft.Control:
        name = task.get("name", "")

        def _on_delete(n):
            res = delete_task(n)
            if res.get("ok"):
                set_status(f"삭제됨: {n}", ft.Colors.GREEN)
            else:
                set_status(f"삭제 실패: {n} — {res.get('stderr', '')[:120]}",
                           ft.Colors.RED)
            refresh_table()

        def _on_toggle(n, enable):
            res = set_task_enabled(n, enable)
            if res.get("ok"):
                set_status(("다시 켬: " if enable else "잠시 끔: ") + n,
                           ft.Colors.GREEN)
            else:
                set_status(f"변경 실패: {n} — {res.get('stderr', '')[:120]}",
                           ft.Colors.RED)
            refresh_table()

        return build_task_row(task, _on_toggle, _on_delete)

    def refresh_table():
        if page is None:        # 오프라인 테스트: schtasks 조회 생략
            return
        try:
            tasks = list_tasks()
        except Exception as ex:  # noqa: BLE001
            set_status(f"목록 조회 실패: {str(ex)[:120]}", ft.Colors.RED)
            return
        table.controls.clear()
        if not tasks:
            table.controls.append(
                ft.Text("등록된 예약이 없습니다.", size=12, color=ft.Colors.GREY))
        else:
            for t in tasks:
                table.controls.append(_row_control(t))
        _safe_update()

    # --- 예약 등록 ---------------------------------------------------------
    def _do_create(mode, course, seq, unwatched):
        def work():
            try:
                res = create_task(
                    _python_exe(), str(PROJECT_ROOT), mode,
                    normalize_time(time_tf.value),
                    course=course, seq=seq, unwatched=unwatched,
                    freq=freq_group.value, highest=bool(highest_cb.value),
                )
            except Exception as ex:  # noqa: BLE001
                set_status(f"등록 실패: {str(ex)[:140]}", ft.Colors.RED)
                return
            if res.get("ok"):
                extra = ("  (관리자 권한이 아니어서 '최고 권한'은 빼고 등록)"
                         if res.get("downgraded") else "")
                set_status(f"예약 등록됨 ✅  {res.get('name')}  "
                           f"({freq_group.value} {normalize_time(time_tf.value)})"
                           f"{extra}", ft.Colors.GREEN)
            else:
                set_status(f"등록 실패 ❌  {res.get('name')} — "
                           f"{(res.get('stderr') or '')[:140]}", ft.Colors.RED)
            refresh_table()

        set_status("예약 등록 중…", ft.Colors.BLUE)
        threading.Thread(target=work, daemon=True).start()

    def _close_dialog():
        if page is not None:
            try:
                page.pop_dialog()
            except Exception:
                pass

    def on_add(_):
        if not valid_time(time_tf.value):
            set_status("시각 형식이 올바르지 않습니다 (예: 02:00).", ft.Colors.RED)
            return
        mode = mode_dd.value
        course = course_dd.value or None
        seq = int(lecture_dd.value) if lecture_dd.value else None
        unwatched = bool(unwatched_cb.value) and not seq
        if requires_confirm(mode):       # 이수/전체 → 실제 서버 이수 동의 필수
            body = (confirm_message(mode) + "\n\n"
                    "이 작업은 예약된 시각에 사람이 보지 않는 상태로 자동 실행되어 "
                    "실제 서버에 영상 이수가 적립되고 형성평가 답안이 제출됩니다.\n\n"
                    + watch_sleep_warning())

            def _confirm():
                _close_dialog()
                _do_create(mode, course, seq, unwatched)

            def _cancel():
                _close_dialog()
                set_status("예약 등록 취소됨.", ft.Colors.GREY)

            dlg, _agree, _start = build_confirm_dialog(
                mode, body, "", _confirm, _cancel, start_label="예약 등록")
            state["confirm_dialog"] = dlg
            if page is not None:
                try:
                    page.show_dialog(dlg)
                except Exception:
                    pass
        else:
            _do_create(mode, course, seq, unwatched)

    def on_mode_change(_):
        sleep_note.visible = (mode_dd.value in (MODE_WATCH, MODE_FULL))
        _safe_update()

    def on_refresh(_):
        set_status("목록 새로고침 중…", ft.Colors.BLUE)
        refresh_table()

    add_btn.on_click = on_add
    mode_dd.on_select = on_mode_change
    refresh_btn.on_click = on_refresh

    populate_courses()
    refresh_table()

    table_panel = ft.Container(
        content=ft.Column([table], scroll=ft.ScrollMode.AUTO),
        border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
        padding=12,
        expand=True,
    )

    return ft.Column(
        [
            ft.Text("예약 — 정해진 시각에 자동 실행", size=24,
                    weight=ft.FontWeight.BOLD),
            ft.Text("앱·터미널이 꺼져 있어도 Windows 작업 스케줄러가 지정 시각에 "
                    "실행합니다(창은 뜨지 않음). 실행 결과는 '실행' 탭의 "
                    "'최근 실행 로그 보기'로 확인하세요. (이수/전체는 실제 서버에 "
                    "이수 적립 + 형성평가 제출)", size=13, color=ft.Colors.GREY),
            ft.Divider(),
            mode_dd,
            ft.Row([course_dd, lecture_dd], wrap=True),
            unwatched_cb,
            ft.Row([time_tf, ft.Text("반복:", size=13,
                                     weight=ft.FontWeight.BOLD), freq_group],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            highest_cb,
            guide_note,
            sleep_note,
            ft.Row([add_btn, refresh_btn]),
            status,
            ft.Divider(),
            ft.Text("등록된 예약", size=16, weight=ft.FontWeight.BOLD),
            table_panel,
        ],
        spacing=12,
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
