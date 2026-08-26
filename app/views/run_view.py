"""[run_view] 실행 화면 — 강의 선택 + 예습 노트 생성(+실시간 로그).

과목·차시를 고르고 "예습 노트 생성"을 누르면 `runner.JobRunner` 가 기존 `main.py`
(`--mode 요약 --course … --seq … --limit 1`)를 하위 프로세스로 구동한다. stdout 을
실시간 로그 패널에 흘리고, `parse_progress_line` 으로 단계 진행률·상태를 갱신한다.
완료되면 "노트 열기"로 결과 노트를 연다(os.startfile).

"새로고침"은 경량 `list_lectures.py` 를 돌려 `lectures.json` 을 갱신한다(로그인 필요).

순수 헬퍼(course_names/rows_for_course/lecture_option_text/load_snapshot_rows)는
단위테스트, 실제 생성은 한 강의 수동 검증(기존 프로젝트 철학).

⚠️ 비밀번호·GEMINI_API_KEY 는 화면·로그에 절대 노출하지 않는다(자식이 .env 에서 읽음).
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import flet as ft

from runner import (  # noqa: E402
    JobRunner,
    LectureRow,
    build_command,
    confirm_message,
    estimate_watch_text,
    format_elapsed,
    job_status,
    latest_log_path,
    note_path_for,
    parse_lectures_snapshot,
    parse_progress_line,
    pct_for_stage,
    read_log_tail,
    requires_confirm,
    watch_sleep_warning,
)
from schedule_win import parse_limit, valid_limit  # noqa: E402 - 예약 화면과 같은 규칙
from ui_async import make_updater  # noqa: E402

# 모드 라벨(화면) → main.py --mode 값
MODE_SUMMARY = "요약"
MODE_WATCH = "이수"
MODE_FULL = "전체"   # 영상 이수 + 예습 노트(한 번에)
# 주 실행 버튼 라벨(모드별)
_MODE_LABELS = {
    MODE_SUMMARY: "예습 노트 생성",
    MODE_WATCH: "영상 이수 시작",
    MODE_FULL: "이수 + 예습 노트 생성",
}

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = PROJECT_ROOT / "lectures.json"
STATE_PATH = PROJECT_ROOT / "state.json"
LIST_LECTURES_PY = PROJECT_ROOT / "list_lectures.py"
_MAX_LOG_LINES = 500


def _python_exe() -> str:
    """현재 인터프리터(소스 실행 시 venv python). 패키징은 Phase 5에서 보정."""
    return sys.executable or "python"


# ---------------------------------------------------------------------------
# 순수 헬퍼 (단위테스트 대상)
# ---------------------------------------------------------------------------
def load_snapshot_rows(path=SNAPSHOT_PATH) -> list[LectureRow]:
    """lectures.json → [LectureRow]. 없거나 깨졌으면 []."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        return parse_lectures_snapshot(p.read_text(encoding="utf-8"))
    except OSError:
        return []


def course_names(rows) -> list[str]:
    """등장 순서를 보존한 과목명 목록(중복 제거)."""
    seen: list[str] = []
    for r in rows:
        if r.course not in seen:
            seen.append(r.course)
    return seen


def rows_for_course(rows, course) -> list[LectureRow]:
    """해당 과목의 차시 행만."""
    return [r for r in rows if r.course == course]


def lecture_option_text(row: LectureRow) -> str:
    """드롭다운 표시문구: '13강 - 트랜잭션 ✅'(영상 이수면 체크)."""
    mark = " ✅" if row.video_done else ""
    return f"{row.seq}강 - {row.name}{mark}"


def build_confirm_dialog(mode, body_text, est_text, on_confirm, on_cancel,
                         start_label="이수 시작"):
    """실제 서버에 반영되는 영상 이수 + 형성평가 제출 확인 다이얼로그.

    체크박스에 동의하기 전에는 시작 버튼이 **로직 차원에서** 막힌다
    (UI disabled 뿐 아니라 핸들러에서도 차단 → 실수 클릭·자동화로도 진행 안 됨).
    start_label 로 버튼 문구를 바꿀 수 있다(예약 등록 등 재사용).
    반환: (dlg, agree_checkbox, start_btn) — page 없이도 오프라인 단위테스트 가능.
    """
    agree = ft.Checkbox(
        label="실제 방송대 서버에 이수 기록과 형성평가 답안이 제출됨을 이해합니다",
        value=False)
    start_btn = ft.FilledButton(start_label, icon=ft.Icons.PLAY_CIRCLE,
                                disabled=True)

    def _on_agree(_):
        start_btn.disabled = not bool(agree.value)
        try:
            start_btn.update()
        except Exception:
            pass

    def _on_start(_):
        if start_btn.disabled:   # 안전장치: 미동의 시 클릭 무시
            return
        on_confirm()

    agree.on_change = _on_agree
    start_btn.on_click = _on_start
    cancel_btn = ft.TextButton("취소", on_click=lambda e: on_cancel())

    body_controls = [ft.Text(body_text, size=13)]
    if est_text:
        body_controls.append(ft.Text(est_text, size=13, color=ft.Colors.BLUE))
    body_controls.append(agree)

    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(f"⚠️ '{mode}' — 실제 서버 이수·제출 확인"),
        content=ft.Column(body_controls, tight=True, spacing=10),
        actions=[cancel_btn, start_btn],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dlg, agree, start_btn


def build_extra_dialog(body_text, on_confirm, on_cancel,
                       title: str = "🎬 두 번째 영상이 있어요"):
    """한 회차에 영상이 2개일 때 — 두 번째 영상 예습노트 생성 확인 다이얼로그.

    서버에 무언가를 제출하지 않고 노트만 만드는 작업이라 동의 체크박스는 없다
    (이수 확인 다이얼로그와 다른 점). 반환: (dlg, make_btn).
    """
    make_btn = ft.FilledButton("노트 만들기", icon=ft.Icons.NOTE_ADD,
                               on_click=lambda e: on_confirm())
    skip_btn = ft.TextButton("건너뛰기", on_click=lambda e: on_cancel())
    dlg = ft.AlertDialog(
        modal=True,
        title=ft.Text(title),
        content=ft.Column([ft.Text(body_text, size=13)], tight=True,
                          spacing=10),
        actions=[skip_btn, make_btn],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dlg, make_btn


# ---------------------------------------------------------------------------
# 뷰 빌더 (Flet UI — 수동 스모크)
# ---------------------------------------------------------------------------
def build_run_view(page=None, snapshot_path=SNAPSHOT_PATH) -> ft.Control:
    """실행 화면 컨트롤 트리 생성. page 가 없으면(테스트) update 는 무시."""
    state = {"rows": load_snapshot_rows(snapshot_path),
             "job": None, "note_path": None}

    course_dd = ft.Dropdown(label="과목", width=360, options=[])
    lecture_dd = ft.Dropdown(label="차시 (선택 — 비우면 여러 강 차례로)",
                             width=460, options=[])
    progress = ft.ProgressBar(value=0, width=520, visible=False)
    status_badge = ft.Text("", size=13)
    elapsed_text = ft.Text("", size=12, color=ft.Colors.GREY)
    sleep_warn = ft.Text(watch_sleep_warning(), size=12,
                         color=ft.Colors.ORANGE, visible=False)
    log_view = ft.ListView(expand=True, spacing=1, auto_scroll=True, padding=10)

    mode_group = ft.RadioGroup(
        value=MODE_SUMMARY,
        content=ft.Column([
            ft.Radio(value=MODE_SUMMARY,
                     label="예습 노트 생성 (영상 이수 안 함)"),
            ft.Radio(value=MODE_WATCH,
                     label="영상 이수 + 형성평가 (⚠️ 실제 서버 제출 · 노트 없음)"),
            ft.Radio(value=MODE_FULL,
                     label="영상 이수 + 형성평가 + 예습 노트 (⚠️ 실제 서버 제출)"),
        ], spacing=2),
    )
    redo_chk = ft.Checkbox(
        label="이미 만든 것도 다시 만들기 (덮어쓰기)", value=False)
    # 차시를 안 고르면 '몇 강까지' 가 의미를 갖는다(고르면 그 한 강만).
    # Flet 0.85 의 TextField 는 helper_text 가 아니라 helper(컨트롤)를 받는다.
    limit_tf = ft.TextField(
        label="한 번에 최대 (강)", value="1", width=160,
        helper=ft.Text("차시를 비우면 이 개수만큼", size=11),
        keyboard_type=ft.KeyboardType.NUMBER)
    unwatched_chk = ft.Checkbox(
        label="미이수부터 (차시를 안 골랐을 때)", value=True)
    gen_btn = ft.FilledButton(_MODE_LABELS[MODE_SUMMARY],
                              icon=ft.Icons.AUTO_STORIES)
    cancel_btn = ft.OutlinedButton("취소", icon=ft.Icons.STOP, disabled=True)
    refresh_btn = ft.OutlinedButton("목록 새로고침", icon=ft.Icons.REFRESH)
    open_btn = ft.TextButton("노트 열기", icon=ft.Icons.OPEN_IN_NEW,
                             visible=False, disabled=True)
    view_log_btn = ft.OutlinedButton("최근 실행 로그 보기",
                                     icon=ft.Icons.DESCRIPTION)
    exam_btn = ft.OutlinedButton("형성평가만 실행", icon=ft.Icons.FACT_CHECK,
                                 tooltip="선택한 차시의 형성평가만 다시 풀어 "
                                         "퀴즈 문항을 모읍니다 "
                                         "(⚠️ 실제 서버 제출 · 영상/노트 없음)")
    quiz_btn = ft.OutlinedButton("퀴즈 페이지 만들기", icon=ft.Icons.QUIZ)
    status_btn = ft.OutlinedButton("학습 현황 페이지",
                                   icon=ft.Icons.DASHBOARD_OUTLINED)

    # 진행 로그·경과시간은 **워커 스레드**에서 들어온다. 거기서 page.update() 를
    # 직접 부르면 패치가 큐에만 쌓여, 창을 내렸다 올려야 밀린 줄이 나타난다.
    # (자세한 이유는 ui_async 모듈 설명 참고)
    _safe_update = make_updater(page)

    def log(msg: str, color=None):
        log_view.controls.append(
            ft.Text(msg, size=12, selectable=True, color=color))
        if len(log_view.controls) > _MAX_LOG_LINES:
            del log_view.controls[:len(log_view.controls) - _MAX_LOG_LINES]
        _safe_update()

    def set_status(text: str, color=None):
        status_badge.value = text
        status_badge.color = color
        _safe_update()

    # --- 경과시간/영상 진행 티커 -------------------------------------------
    def _watch_est_pos():
        """마지막 보고 pos 를 배속만큼 보간한 (현재 영상위치, 총길이, 배속).

        watch 로그는 드물게 찍히므로(수십 초 간격) 배속×경과로 보간해 영상이
        실제 재생되는 속도(예: 2배속)와 맞게 부드럽게 진행되도록 한다.
        """
        dur = state.get("watch_dur") or 0
        if dur <= 0:
            return None, None, None
        base_pos = state.get("watch_pos", 0) or 0
        base_ts = state.get("watch_ts")
        rate = state.get("watch_rate") or 1
        paused = state.get("watch_paused", False)
        est = base_pos
        if base_ts and not paused:
            est = base_pos + (time.monotonic() - base_ts) * rate
        est = max(0.0, min(est, dur))
        return est, dur, rate

    def _activity_text() -> str:
        t0 = state.get("t_start")
        if not t0:
            return ""
        est, dur, rate = _watch_est_pos()
        if dur:  # 영상 이수 중 → 영상 진행도 우선 표시(총 길이 포함)
            pct = int(est / dur * 100) if dur else 0
            rtxt = f" · {rate:g}배속" if state.get("watch_rate") else ""
            return (f"영상 {format_elapsed(est)} / {format_elapsed(dur)} "
                    f"({pct}%){rtxt}")
        el = format_elapsed(time.monotonic() - t0)
        act = state.get("activity")
        return f"경과 {el}" + (f" · {act}" if act else "")

    def _refresh_elapsed():
        elapsed_text.value = _activity_text()
        est, dur, _ = _watch_est_pos()
        if dur:  # 진행바도 영상 위치로 갱신
            progress.value = est / dur
        _safe_update()

    def _start_ticker():
        stop = threading.Event()
        state["tick_stop"] = stop

        def run():
            while not stop.is_set():
                _refresh_elapsed()
                stop.wait(1.0)

        threading.Thread(target=run, daemon=True).start()

    def _stop_ticker():
        stop = state.get("tick_stop")
        if stop is not None:
            stop.set()
        _refresh_elapsed()  # 최종 경과 고정

    def _set_running(running: bool):
        gen_btn.disabled = running
        exam_btn.disabled = running
        refresh_btn.disabled = running
        course_dd.disabled = running
        lecture_dd.disabled = running
        mode_group.disabled = running
        redo_chk.disabled = running
        limit_tf.disabled = running
        unwatched_chk.disabled = running
        cancel_btn.disabled = not running
        _safe_update()

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
        if names and not course_dd.value:
            course_dd.value = names[0]
        populate_lectures()

    course_dd.on_select = populate_lectures

    # --- 작업 시작/콜백 ----------------------------------------------------
    def _start_job(argv, label, on_done=None):
        log_view.controls.clear()
        progress.value = None  # 첫 단계 전까지 불확정(인디터미네이트)
        progress.visible = True
        open_btn.visible = False
        open_btn.disabled = True
        state["had_error"] = False   # 이번 작업에서 단계 실패가 있었나
        state["summary"] = None      # main.py 의 '=== 요약 ===' 집계
        state["activity"] = None     # 진행중 활동(강의/단계/매칭)
        state["t_start"] = time.monotonic()
        state["watch_dur"] = 0       # 영상 이수 진행도(0 이면 미사용)
        state["watch_pos"] = 0
        state["watch_ts"] = None
        state["watch_rate"] = None
        state["watch_paused"] = False
        _set_running(True)
        set_status(f"실행 중: {label}", ft.Colors.BLUE)
        log(f"$ {' '.join(str(a) for a in argv)}")
        _start_ticker()

        def on_line(line: str):
            log(line)
            ev = parse_progress_line(line)
            if not ev:
                return
            etype = ev.get("event")
            if etype == "lecture":
                state["activity"] = f"{ev.get('course', '')} {ev.get('seq', '')}강"
            elif etype == "match":
                state["activity"] = f"매칭 {ev.get('matched')}/{ev.get('total')}"
            elif etype == "watch":
                # 영상 이수 진행: 위치/길이/배속 기록 → 티커가 보간 표시
                state["watch_pos"] = ev.get("pos", 0)
                state["watch_dur"] = ev.get("dur", 0)
                state["watch_rate"] = ev.get("rate")
                state["watch_paused"] = bool(ev.get("paused", False))
                state["watch_ts"] = time.monotonic()
                _refresh_elapsed()
            elif etype == "summary":
                state["summary"] = ev
            elif ev.get("status") in ("done", "skip") and ev.get("stage"):
                state["activity"] = f"{ev['stage']} ✓"
                state["watch_dur"] = 0   # 이수 끝 → 단계 진행바로 전환(전체 모드)
                pct = pct_for_stage(ev["stage"])
                if pct is not None:
                    progress.value = pct / 100
                    _safe_update()
            elif ev.get("status") == "error":
                state["activity"] = f"{ev.get('stage')} ✗"
                state["had_error"] = True
                set_status(f"단계 실패: {ev.get('stage')} — 로그 확인",
                           ft.Colors.RED)

        def on_exit(code: int):
            _stop_ticker()
            _set_running(False)
            progress.visible = False
            # main.py 는 강의 1개가 실패해도 종료코드 0 으로 끝난다
            # (실패는 '=== 요약 ===' 의 failed 와 '✗' 로그로만 드러남).
            summary = state.get("summary") or {}
            failed = summary.get("failed", 0)
            processed = summary.get("processed")
            status = job_status(code, had_error=bool(state.get("had_error")),
                                failed=failed, processed=processed)
            ok = status == "done"
            if status == "cancelled":
                set_status("취소됨", ft.Colors.ORANGE)
            elif ok:
                set_status(f"완료 ✅  {label}", ft.Colors.GREEN)
            else:
                detail = (f"(실패 {failed}건)" if failed else
                          f"(종료코드 {code})" if code not in (0, -1) else
                          "(빈 결과)")
                # 성공한 단계는 기록돼 있으므로 그냥 다시 누르면 이어서 간다
                # (영상 이수를 다시 하지 않는다) — 사용자가 이걸 몰라 처음부터
                # 다시 돌리는 일이 없게 상태줄에서 알려준다.
                set_status(f"실패 ❌  {label} {detail} — 아래 로그의 ✗ 줄을 "
                           "확인하세요. 그대로 다시 실행하면 **실패한 단계부터** "
                           "이어서 합니다(영상 이수는 다시 안 함).",
                           ft.Colors.RED)
            if on_done:
                try:
                    on_done(ok)
                except Exception:
                    pass
            _safe_update()

        job = JobRunner(on_line=on_line, on_exit=on_exit)
        state["job"] = job
        try:
            job.start(argv)
        except Exception as ex:  # noqa: BLE001
            _set_running(False)
            progress.visible = False
            set_status(f"시작 실패: {str(ex)[:120]}", ft.Colors.RED)

    def run_count() -> int:
        """'한 번에 최대 (강)' 입력값(빈칸·잘못된 값이면 1강)."""
        return parse_limit(limit_tf.value) or 1

    # --- 모드별 실행 ------------------------------------------------------
    _RUN_LABELS = {
        MODE_SUMMARY: "예습 노트",
        MODE_WATCH: "영상 이수",
        MODE_FULL: "이수+예습 노트",
    }

    def _run(cfg, mode, course, seq, row):
        """선택 모드로 main.py 구동. 요약/전체는 노트 생성 → 완료 시 '노트 열기'.

        seq 가 None 이면 차시를 안 고른 것 — 그 과목에서 '한 번에 최대 N강'만큼
        차례로 처리한다(노트 열기·두 번째 영상 확인은 한 강일 때만 의미가 있다).
        """
        makes_note = mode in (MODE_SUMMARY, MODE_FULL)
        one = seq is not None
        count = 1 if one else run_count()
        name = row.name if row else ""
        state["note_path"] = (note_path_for(cfg, course, seq, name)
                              if (makes_note and one and name) else None)
        argv = build_command(_python_exe(), mode, course=course,
                             seq=seq, limit=count,
                             unwatched=(not one and bool(unwatched_chk.value)),
                             force=bool(redo_chk.value))

        def after(ok):
            np = state.get("note_path")
            if ok and np and Path(np).exists():
                open_btn.visible = True
                open_btn.disabled = False
            # 한 회차에 영상이 2개면 여기서 물어본다(실행이 다 끝난 뒤 한 번).
            # 실패한 실행 뒤에는 묻지 않는다 — 다음 성공 실행 때 다시 뜬다.
            # 여러 강을 한 번에 돌린 경우엔 어느 강인지 특정할 수 없어 묻지 않는다.
            if ok and one:
                _ask_extra_video(cfg, course, seq, name)

        target = f"{seq}강" if one else f"최대 {count}강"
        label = f"{course} {target} {_RUN_LABELS.get(mode, mode)}"
        _start_job(argv, label, on_done=after if makes_note else None)

    # --- 두 번째 영상(회차에 영상 2개) 예습노트 -----------------------------
    def _run_extra(cfg, course, seq, name):
        """`main.py --stages extra` 로 두 번째 영상 노트만 따로 만든다."""
        from extra_video import extra_note_name
        state["note_path"] = (note_path_for(cfg, course, seq,
                                            extra_note_name(name, 2))
                              if name else None)
        argv = build_command(_python_exe(), MODE_SUMMARY, course=course,
                             seq=seq, limit=1, stages=["extra"])

        def after(ok):
            np = state.get("note_path")
            if ok and np and Path(np).exists():
                open_btn.visible = True
                open_btn.disabled = False

        _start_job(argv, f"{course} {seq}강 두 번째 영상 예습노트", on_done=after)

    # --- 형성평가(퀴즈)만 따로 -------------------------------------------
    def _run_exam_only(course, seq):
        """`main.py --stages exam --force` 로 형성평가만 다시 푼다(+문항 캡처).

        --force 가 핵심이다: 형성평가가 한 번 '없음(skip)'으로 **완료 기록**되면
        보통 실행에서는 영영 건너뛰어져, 나중에 문제가 올라와도 안 잡힌다.
        """
        argv = build_command(_python_exe(), MODE_WATCH, course=course,
                             seq=seq, limit=1, stages=["exam"], force=True)
        _start_job(argv, f"{course} {seq}강 형성평가·퀴즈")

    def on_exam_only(_):
        """형성평가만 실행 — 실제 서버 제출이므로 동의 다이얼로그를 반드시 거친다."""
        if not course_dd.value or not lecture_dd.value:
            set_status("먼저 과목과 차시를 선택하세요.", ft.Colors.RED)
            return
        course, seq = course_dd.value, int(lecture_dd.value)
        body = (f"'{course} {seq}강' 의 형성평가만 다시 풀어 문항을 모읍니다"
                "(영상 이수·노트 생성은 하지 않습니다).\n\n"
                + confirm_message(MODE_WATCH))

        def _confirm():
            _close_dialog()
            _run_exam_only(course, seq)

        def _cancel():
            _close_dialog()
            set_status("형성평가 실행 취소됨.", ft.Colors.GREY)

        dlg, _agree, _start = build_confirm_dialog(
            MODE_WATCH, body, "", _confirm, _cancel,
            start_label="형성평가 실행")
        state["confirm_dialog"] = dlg
        if page is not None:
            try:
                page.show_dialog(dlg)
            except Exception:
                pass

    def _ask_extra_video(cfg, course, seq, name):
        """실행 뒤 state.json 을 보고, 두 번째 영상이 있으면 생성 여부를 묻는다.

        capture 단계가 남긴 탐지 기록만 읽는다(추가 로그인·플레이어 열기 없음).
        """
        try:
            from extra_video import (extra_prompt_text, pending_extras,
                                     read_state)
            clips = pending_extras(read_state(STATE_PATH), course, seq)
        except Exception:  # noqa: BLE001 - 탐지 기록 문제로 실행 결과를 가리지 않게
            return
        if not clips:
            return
        body = extra_prompt_text(clips, course, seq)
        log(f"🎬 두 번째 영상 {len(clips)}개 감지 — 노트 생성 여부 확인")

        def _confirm():
            _close_dialog()
            _run_extra(cfg, course, seq, name)

        def _cancel():
            _close_dialog()
            set_status("두 번째 영상 노트는 건너뜀 "
                       "(나중에 같은 차시를 다시 실행하면 또 물어봅니다)",
                       ft.Colors.GREY)

        dlg, _make = build_extra_dialog(body, _confirm, _cancel)
        state["extra_dialog"] = dlg      # 테스트/디버그용 보관
        if page is not None:
            try:
                page.show_dialog(dlg)
            except Exception:
                pass

    def _close_dialog():
        if page is not None:
            try:
                page.pop_dialog()
            except Exception:
                pass

    def _open_confirm(cfg, mode, course, seq, row):
        """이수/전체 전 확인 다이얼로그(예상시간 + 비가역성 경고 + 동의 체크)."""
        est = ""
        if row and getattr(row, "total_min", 0) > 0:
            est = estimate_watch_text(row.total_min, row.watched_min,
                                      getattr(cfg, "playback_speed", 2.0))
        scope = (f"'{course} {seq}강' 한 강" if seq is not None
                 else f"'{course}' 에서 최대 {run_count()}강(차시 미지정)")
        body = (f"대상: {scope}\n\n" + confirm_message(mode) + "\n\n"
                + watch_sleep_warning())

        def _confirm():
            _close_dialog()
            _run(cfg, mode, course, seq, row)

        def _cancel():
            _close_dialog()
            set_status("이수 취소됨(사용자 취소)", ft.Colors.GREY)

        dlg, _agree, _start = build_confirm_dialog(mode, body, est,
                                                   _confirm, _cancel)
        state["confirm_dialog"] = dlg  # 테스트/디버그용 보관
        if page is not None:
            try:
                page.show_dialog(dlg)
            except Exception:
                pass

    def on_primary(_):
        """주 실행 버튼: 선택된 모드(요약/이수/전체)로 분기.

        차시는 **선택 사항**이다 — 비워두면 '한 번에 최대 N강'만큼 차례로 돈다.
        """
        if not course_dd.value:
            set_status("먼저 과목을 선택하세요.", ft.Colors.RED)
            return
        if not valid_limit(limit_tf.value):
            set_status("'한 번에 최대'는 1 이상의 숫자이거나 비워두세요.",
                       ft.Colors.RED)
            return
        try:
            from config import load_config
            cfg = load_config()
        except Exception as ex:  # noqa: BLE001
            set_status(f"설정이 필요합니다: {str(ex)[:100]} → '설정' 탭",
                       ft.Colors.RED)
            return
        course = course_dd.value
        seq = int(lecture_dd.value) if lecture_dd.value else None
        row = (next((r for r in rows_for_course(state["rows"], course)
                     if r.seq == seq), None) if seq is not None else None)
        mode = mode_group.value
        if requires_confirm(mode):       # 이수/전체 → 반드시 확인 다이얼로그
            _open_confirm(cfg, mode, course, seq, row)
        else:                            # 요약 → 바로 실행
            _run(cfg, mode, course, seq, row)

    def on_mode_change(_):
        """모드 라디오 변경 시 버튼 라벨/아이콘 갱신 + 절전경고 토글 + 노트열기 숨김."""
        mode = mode_group.value
        gen_btn.content = _MODE_LABELS.get(mode, "실행")  # Flet 0.85: text 아님
        gen_btn.icon = (ft.Icons.AUTO_STORIES if mode == MODE_SUMMARY
                        else ft.Icons.PLAY_CIRCLE)
        sleep_warn.visible = (mode in (MODE_WATCH, MODE_FULL))
        open_btn.visible = False
        open_btn.disabled = True
        _safe_update()

    def on_refresh(_):
        argv = [_python_exe(), "-u", str(LIST_LECTURES_PY)]

        def after(ok):
            if ok:
                state["rows"] = load_snapshot_rows(snapshot_path)
                course_dd.value = None
                populate_courses()

        _start_job(argv, "강의 목록 새로고침", on_done=after)

    def on_cancel(_):
        job = state.get("job")
        if job is not None:
            job.cancel()
            set_status("취소 요청…", ft.Colors.ORANGE)

    def on_open(_):
        np = state.get("note_path")
        if np and Path(np).exists():
            try:
                os.startfile(str(np))  # noqa: S606 - 사용자 의도적 노트 열기
            except Exception as ex:  # noqa: BLE001
                set_status(f"열기 실패: {str(ex)[:100]}", ft.Colors.RED)
        else:
            set_status("열 노트가 아직 없습니다.", ft.Colors.RED)

    def on_view_log(_):
        """예약(창 없이 실행)이 남긴 가장 최근 실행 로그를 로그 패널에 불러온다."""
        p = latest_log_path()
        if not p:
            set_status("표시할 실행 로그가 없습니다 (logs/run_*.log).",
                       ft.Colors.GREY)
            return
        lines = read_log_tail(p, _MAX_LOG_LINES)
        log_view.controls.clear()
        log(f"📄 최근 실행 로그: {Path(p).name}", ft.Colors.BLUE)
        for ln in lines:
            log(ln)
        set_status(f"최근 실행 로그 표시 ({len(lines)}줄) — {Path(p).name}",
                   ft.Colors.BLUE)

    def on_make_quiz(_):
        """모은 돌발퀴즈/형성평가 문항으로 복습용 HTML 페이지를 만들어 연다."""
        try:
            from config import load_config
            cfg = load_config()
        except Exception as ex:  # noqa: BLE001
            set_status(f"설정이 필요합니다: {str(ex)[:100]} → '설정' 탭",
                       ft.Colors.RED)
            return
        from quiz_page import default_quiz_paths, write_quiz_page
        quiz_dir, out_path = default_quiz_paths(cfg)
        try:
            p = write_quiz_page(quiz_dir, out_path)
        except Exception as ex:  # noqa: BLE001
            set_status(f"퀴즈 페이지 생성 실패: {str(ex)[:100]}", ft.Colors.RED)
            return
        set_status(f"퀴즈 페이지 생성: {Path(p).name}", ft.Colors.GREEN)
        try:
            os.startfile(str(p))  # noqa: S606 - 사용자 의도적 페이지 열기
        except Exception:
            pass

    def on_make_status(_):
        """과목·차시별로 무엇이 만들어졌는지 한눈에 보는 현황 페이지를 만들어 연다."""
        try:
            from config import load_config
            cfg = load_config()
        except Exception as ex:  # noqa: BLE001
            set_status(f"설정이 필요합니다: {str(ex)[:100]} → '설정' 탭",
                       ft.Colors.RED)
            return
        from status_page import write_status_page
        try:
            p = write_status_page(cfg, snapshot_path, STATE_PATH)
        except Exception as ex:  # noqa: BLE001
            set_status(f"현황 페이지 생성 실패: {str(ex)[:100]}", ft.Colors.RED)
            return
        set_status(f"현황 페이지 생성: {Path(p).name} "
                   "(목록이 오래됐으면 '목록 새로고침' 후 다시 만드세요)",
                   ft.Colors.GREEN)
        try:
            os.startfile(str(p))  # noqa: S606 - 사용자 의도적 페이지 열기
        except Exception:
            pass

    gen_btn.on_click = on_primary
    mode_group.on_change = on_mode_change
    cancel_btn.on_click = on_cancel
    refresh_btn.on_click = on_refresh
    open_btn.on_click = on_open
    view_log_btn.on_click = on_view_log
    quiz_btn.on_click = on_make_quiz
    exam_btn.on_click = on_exam_only
    status_btn.on_click = on_make_status

    populate_courses()

    log_panel = ft.Container(
        content=log_view,
        border_radius=8,
        bgcolor=ft.Colors.with_opacity(0.05, ft.Colors.ON_SURFACE),
        expand=True,
    )

    return ft.Column(
        [
            ft.Text("실행 — 예습 노트 · 영상 이수", size=24,
                    weight=ft.FontWeight.BOLD),
            ft.Text("과목과 모드를 고르고 실행하세요. 차시를 비우면 "
                    "'한 번에 최대' 개수만큼 차례로 돕니다. "
                    "(목록이 비었으면 '목록 새로고침')", size=13,
                    color=ft.Colors.GREY),
            ft.Divider(),
            ft.Row([course_dd, refresh_btn],
                   vertical_alignment=ft.CrossAxisAlignment.END),
            ft.Row([lecture_dd, limit_tf], wrap=True,
                   vertical_alignment=ft.CrossAxisAlignment.START),
            unwatched_chk,
            ft.Row([ft.Text("모드:", size=13, weight=ft.FontWeight.BOLD),
                    mode_group],
                   vertical_alignment=ft.CrossAxisAlignment.START),
            redo_chk,
            sleep_warn,
            ft.Row([gen_btn, exam_btn, cancel_btn, open_btn], wrap=True),
            progress,
            ft.Row([status_badge, elapsed_text], spacing=12),
            ft.Row([ft.Text("진행 로그", size=13, weight=ft.FontWeight.BOLD),
                    ft.Row([status_btn, quiz_btn, view_log_btn])],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            log_panel,
        ],
        spacing=12,
        expand=True,
    )
