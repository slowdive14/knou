"""[tools_view] 도구 — 가끔 돌리는 명령들을 설명과 함께 눌러서 실행한다.

그동안 '이럴 때는 python ○○.py 를 돌리세요' 하고 안내한 명령이 여럿이었다.
한 번 쓰고 나면 언제 무엇을 돌려야 하는지 잊는다. 그래서 명령마다 **이럴 때**
와 **하는 일**을 적고, 필요한 값만 채워 [실행] 을 누르게 한다.

  · 명령은 앱과 같은 파이썬으로 하위 프로세스에서 돈다(창 없이)
  · 출력은 오른쪽 기록판에 그대로 흐른다 — [멈추기] 로 끊을 수 있다
  · 한 번에 하나만 돈다(같은 파일을 두 작업이 함께 고치지 않게)
  · 마지막으로 넣은 값(과목·닉네임 등)은 기억해 둔다(ui_prefs.json)

순수 로직(단위테스트 대상):
  - TOOLS                      : 도구 목록(무엇을 · 언제 · 어떤 값으로)
  - missing(tool, values)      : 비어 있는 필수 칸 이름들
  - build_argv(tool, values, py) : 실행할 명령 줄
  - command_text(argv)         : 기록판에 보일 명령(파이썬 경로는 줄여서)

⚠️ 시스템에 프로그램을 까는 일(C 컴파일러)은 앱이 대신하지 않는다 — 파일
   위치만 열어 주고 사람이 더블클릭한다.
⚠️ 명령 줄에 비밀값을 넣지 않는다(자식은 .env 에서 직접 읽는다).
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass
from pathlib import Path

import flet as ft

from ui_async import make_updater

MINT = "#00a37a"
MINT_BG = "#e3f6ef"
ROSE = "#c8452f"
APRI = "#d98324"
MUTE = "#8b9198"

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
SNAPSHOT_PATH = PROJECT_ROOT / "lectures.json"
LOG_WIDTH = 440          # 오른쪽 기록판 폭(px)
MAX_LOG_LINES = 600      # 기록판에 남길 줄 수
PREFS_KEY = "tools"      # ui_prefs.json 안에서 이 화면이 쓰는 칸

GROUP_EXAM = "기출 문제"
GROUP_QUIZ = "강의 퀴즈"
GROUP_NOTE = "예습 노트"
GROUP_PLAN = "진도"
GROUPS = (GROUP_EXAM, GROUP_QUIZ, GROUP_NOTE, GROUP_PLAN)

# 꼬리표 — 실행 전에 알아야 할 것
TAG_AI = "AI 사용"
TAG_LOGIN = "로그인"
TAG_SLOW = "몇 분 걸림"
TAG_HWP = "한글 필요"
TAG_TIPS = {
    TAG_AI: "Gemini 를 부릅니다(설정의 API 키). 무료 등급은 붐비면 잠깐 기다립니다",
    TAG_LOGIN: "학교 사이트에 로그인해 읽기만 합니다. 실행 탭에서 작업이 돌고 "
               "있으면 끝난 뒤에 누르세요(브라우저를 함께 쓸 수 없습니다)",
    TAG_SLOW: "회차·과목이 많으면 몇 분 이상 걸립니다. 다른 탭에 가 있어도 계속 돕니다",
    TAG_HWP: "HWP 시험지는 한글 프로그램으로 인쇄해 PDF 로 바꿉니다",
}


@dataclass(frozen=True)
class Field:
    """도구에 넣는 값 한 칸.

    kind: course(과목 고르기) · year · term · text · file · folder · check
    flag: '--course' 처럼 붙일 이름. 비우면 위치 인자.
    check 는 켜면 flag 를 붙인다(invert=True 면 **꺼져 있을 때** 붙인다).
    """
    key: str
    label: str
    kind: str
    flag: str = ""
    required: bool = False
    hint: str = ""
    exts: tuple = ()
    invert: bool = False


@dataclass(frozen=True)
class Tool:
    key: str
    group: str
    title: str
    when: str                 # 이럴 때
    does: str                 # 하는 일
    script: str = ""          # 프로젝트 폴더의 .py
    fields: tuple = ()
    tags: tuple = ()
    after: str = ""           # 끝나고 이어서 할 일
    reveal: str = ""          # 실행 대신 위치만 열어 줄 파일(사람이 직접 연다)


def _course(required=False, hint="비우면 전부"):
    return Field("course", "과목", "course", "--course", required, hint)


def _year(hint="비우면 전부"):
    return Field("year", "연도", "year", "--year", hint=hint)


TOOLS: tuple = (
    # --- 기출 문제 -----------------------------------------------------------
    Tool("index_sheets", GROUP_EXAM, "시험지 회차 읽기",
         when="퀴즈의 '기출 원본' 줄에서 [시험지] 가 흐리게 나올 때 · "
              "시험지를 새로 받았을 때",
         does="받아 둔 시험지 첫 쪽을 보고 몇 년도 몇 학기 것인지 적어 둡니다. "
              "한 번 읽은 시험지는 다시 읽지 않습니다.",
         script="index_exam_files.py", fields=(_course(),), tags=(TAG_AI,)),
    Tool("local_exam", GROUP_EXAM, "건네받은 시험지로 회차 만들기",
         when="자료실에서 받지 못한 시험지(한글 배포용 문서 등)를 따로 구했을 때",
         does="시험지를 PDF 로 바꾸고 머리글로 회차를 확인한 뒤, 문항을 읽어 "
              "기출 은행을 만듭니다. 정답표가 있으면 정답도 붙입니다.",
         script="build_exam_bank.py",
         fields=(Field("file", "시험지 파일", "file", "--file", True,
                       exts=("hwp", "hwpx", "pdf")),
                 _course(required=True, hint=""),
                 Field("year", "연도", "year", "--year", True),
                 Field("term", "학기", "term", "--term", True),
                 Field("force", "이미 있는 회차도 다시 만들기", "check",
                       "--force")),
         tags=(TAG_AI, TAG_SLOW, TAG_HWP),
         after="만든 뒤에는 '기출 문항 확인' → '기출 그림 붙이기' → "
               "'기출에 강 번호 붙이기' 를 차례로 돌리세요."),
    Tool("verify", GROUP_EXAM, "기출 문항 확인·바로잡기",
         when="문제가 시험지와 달라 보일 때 · 기출을 새로 담은 뒤",
         does="시험지를 다시 읽어 은행 문항과 하나씩 대 봅니다. 다른 문항은 "
              "지면을 보여 주고 어느 쪽이 맞는지 판정하고, 정답표 번호와 말이 "
              "되는지도 풀어 봅니다.",
         script="verify_exams.py",
         fields=(_course(), _year(),
                 Field("fix", "바로잡기까지(고치기 전에 백업합니다)", "check",
                       "--fix")),
         tags=(TAG_AI, TAG_SLOW),
         after="바로잡기를 끄고 돌리면 무엇이 다른지 보여 주기만 합니다."),
    Tool("figures", GROUP_EXAM, "기출 그림 붙이기",
         when="'아래 그림은…' 인데 그림이 없는 기출 문항이 있을 때 · "
              "기출을 새로 담은 뒤",
         does="시험지에서 그 문항의 그림만 잘라 문항에 붙입니다. 이미 그림이 "
              "있는 문항은 건너뜁니다.",
         script="fetch_exam_figures.py",
         fields=(_course(),
                 Field("dry", "붙이지 않고 보기만", "check", "--dry"),
                 Field("hwp", "PDF 가 없는 한글 시험지도 바꿔서(오래 걸림)",
                       "check", "--no-hwp", invert=True)),
         tags=(TAG_AI,)),
    Tool("tag", GROUP_EXAM, "기출에 강 번호 붙이기",
         when="'강 모아보기' 에 새로 담은 기출 문항이 안 나올 때 · "
              "기출을 새로 담은 뒤",
         does="강의 목차를 놓고 문항마다 몇 강 내용인지 가려 적어 둡니다. "
              "이미 적힌 문항은 건너뜁니다.",
         script="tag_lectures.py",
         fields=(_course(required=True, hint=""), _year(),
                 Field("dry", "적지 않고 보기만", "check", "--dry-run")),
         tags=(TAG_AI,)),
    Tool("variants", GROUP_EXAM, "변형 문제 만들기",
         when="기출을 여러 번 풀어 답이 외워졌을 때",
         does="개념은 그대로 두고 숫자·코드만 바꾼 문제를 따로 된 은행에 "
              "만듭니다. 코드 문항은 실제로 컴파일·실행해 정답을 확인합니다"
              "(C 컴파일러가 필요합니다).",
         script="build_variants.py",
         fields=(_course(required=True, hint=""), _year()),
         tags=(TAG_AI, TAG_SLOW),
         after="만든 뒤에는 '변형 문제 검토' 를 돌리세요."),
    Tool("check_variants", GROUP_EXAM, "변형 문제 검토",
         when="변형 문제의 물음과 정답이 어긋나 보일 때 · 변형을 새로 만든 뒤",
         does="정답을 알려 주지 않고 다시 풀게 해, 은행의 정답과 다르면 믿을 "
              "수 없는 문항으로 표시하고 화면에서 뺍니다(파일에는 남깁니다).",
         script="check_variants.py",
         fields=(_course(required=True, hint=""), _year(),
                 Field("apply", "표시까지(끄면 살펴보기만)", "check",
                       "--apply")),
         tags=(TAG_AI, TAG_SLOW)),
    Tool("compiler", GROUP_EXAM, "C 컴파일러 설치",
         when="'변형 문제 만들기' 에서 컴파일러가 없다고 나올 때",
         does="시스템에 프로그램을 까는 일이라 앱이 대신하지 않습니다. "
              "[파일 위치 열기] 를 눌러 install_compiler.bat 을 더블클릭하세요. "
              "설치가 끝나면 앱을 껐다가 다시 켜야 인식됩니다.",
         reveal="install_compiler.bat"),
    # --- 강의 퀴즈 -----------------------------------------------------------
    Tool("intros", GROUP_QUIZ, "빠진 형성평가 지문 채우기",
         when="'위 문장의 출력 결과는?' 인데 그 문장이 없는 형성평가 문항이 "
              "있을 때",
         does="그 차시를 다시 열어 읽기만 하고 지문을 채웁니다. 아무것도 "
              "제출하지 않지만, 강의 플레이어를 열어 영상이 잠깐 재생될 수 "
              "있습니다.",
         script="fetch_intros.py",
         fields=(_course(),
                 Field("seq", "차시", "text", "--seq", hint="비우면 전부"),
                 Field("dry", "어디가 비었는지만 보기", "check", "--dry-run")),
         tags=(TAG_LOGIN,)),
    # --- 예습 노트 -----------------------------------------------------------
    Tool("import_docs", GROUP_NOTE, "손에 있는 강의록 들여오기",
         when="강의자료실 다운로드가 실패해 강의록 PDF 를 따로 모아 두었을 때",
         does="폴더의 PDF 를 앱이 찾는 이름(과목_N강.pdf)으로 복사합니다. "
              "원본은 그대로 두고, 이미 있는 파일은 덮어쓰지 않습니다.",
         script="import_docs.py",
         fields=(Field("src", "강의록 폴더", "folder", required=True),
                 Field("course", "과목", "course", required=True),
                 Field("dry", "옮길 계획만 보기", "check", "--dry-run"))),
    Tool("slides", GROUP_NOTE, "바이오통계학 슬라이드 받기",
         when="바이오통계학 예습 노트를 만들기 전(강의록이 슬라이드 ZIP 으로만 "
              "올라와 있습니다)",
         does="강의자료실의 슬라이드 ZIP 을 받아 풉니다. 읽기만 합니다.",
         script="fetch_knouon_slides.py", tags=(TAG_LOGIN,),
         after="받은 뒤 '손에 있는 강의록 들여오기' 로 downloads 폴더의 "
               "_바이오통계학_슬라이드 를 바이오통계학으로 들여오세요."),
    Tool("resize", GROUP_NOTE, "노트 그림 폭 맞추기",
         when="예전에 만든 노트의 그림 크기가 들쭉날쭉할 때",
         does="노트에 적힌 그림 표시 폭만 한꺼번에 맞춥니다. 그림 파일은 "
              "건드리지 않습니다.",
         script="resize_embeds.py",
         fields=(Field("dry", "고치지 않고 보기만", "check", "--dry-run"),)),
    # --- 진도 ----------------------------------------------------------------
    Tool("kakao", GROUP_PLAN, "카카오톡 인증 기록 불러오기",
         when="단톡방에 올린 공부 인증을 진도 트래커에 한꺼번에 채울 때",
         does="카카오톡 대화 내보내기(.txt)에서 내 인증만 골라 진도 탭에 "
              "표시합니다. 이미 적힌 날짜는 덮어쓰지 않습니다.",
         script="import_kakao.py",
         fields=(Field("file", "대화 파일", "file", "--file", True,
                       exts=("txt",)),
                 Field("nick", "내 닉네임", "text", "--nick", True,
                       hint="단톡방에서 쓰는 이름"),
                 Field("dry", "채우지 않고 보기만", "check", "--dry"))),
)


def tool_by_key(key):
    return next((t for t in TOOLS if t.key == key), None)


# ---------------------------------------------------------------------------
# 순수 조각
# ---------------------------------------------------------------------------
def _filled(value) -> str:
    if isinstance(value, bool):
        return ""
    return str(value or "").strip()


def missing(tool, values) -> list:
    """비어 있는 필수 칸의 이름들."""
    values = values or {}
    return [f.label for f in tool.fields
            if f.required and f.kind != "check" and not _filled(values.get(f.key))]


def bad_values(tool, values) -> list:
    """형식이 틀린 칸 — 연도는 네 자리, 학기는 1·2, 차시는 숫자."""
    values = values or {}
    out = []
    for f in tool.fields:
        v = _filled(values.get(f.key))
        if not v:
            continue
        if f.kind == "year" and not (v.isdigit() and len(v) == 4):
            out.append(f"{f.label}는 2014 처럼 네 자리로 적어 주세요")
        elif f.kind == "term" and v not in ("1", "2"):
            out.append(f"{f.label}는 1 또는 2 입니다")
        elif f.key == "seq" and not v.isdigit():
            out.append(f"{f.label}는 숫자로 적어 주세요")
    return out


def build_argv(tool, values, python=None) -> list:
    """실행할 명령 줄 — [파이썬, -u, 스크립트, 위치 인자…, --이름 값…]."""
    values = values or {}
    py = python or sys.executable or "python"
    pos, opts = [], []
    for f in tool.fields:
        v = values.get(f.key)
        if f.kind == "check":
            on = bool(v)
            if on != f.invert:
                opts.append(f.flag)
            continue
        s = _filled(v)
        if not s:
            continue
        if f.flag:
            opts += [f.flag, s]
        else:
            pos.append(s)
    return [py, "-u", str(PROJECT_ROOT / tool.script)] + pos + opts


def command_text(argv) -> str:
    """기록판에 보일 명령 — 'python verify_exams.py --course 자료구조'."""
    parts = list(argv or [])
    if len(parts) >= 3:
        parts = ["python", Path(parts[2]).name] + parts[3:]
    return " ".join(f'"{p}"' if " " in str(p) else str(p) for p in parts)


def child_env() -> dict:
    """자식 프로세스 환경 — 한글 출력이 깨지지 않게 UTF-8 로 맞춘다."""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    return env


def course_names(path=SNAPSHOT_PATH) -> list:
    """과목 고르기에 올릴 이름들 — 강의 목록(lectures.json)에서."""
    import study_plan as sp
    return [c["course"] for c in sp.courses_from_lectures(path, skip=())]


def load_values(prefs) -> dict:
    """기억해 둔 값 — {도구: {칸: 값}}. 파일 경로는 다시 쓰지 않는다."""
    got = (prefs or {}).get(PREFS_KEY) or {}
    return {k: dict(v) for k, v in got.items() if isinstance(v, dict)}


def remembered(tool, values) -> dict:
    """다음에 다시 채워 둘 값 — 과목·연도·닉네임처럼 되풀이되는 것만.

    파일·폴더 경로와 켜고 끄는 칸은 기억하지 않는다. 지난번에 켜 둔 '바로잡기'
    가 다음에도 켜져 있으면 모르고 고치게 된다.
    """
    keep = {}
    for f in tool.fields:
        if f.kind in ("course", "year", "term", "text"):
            v = _filled((values or {}).get(f.key))
            if v:
                keep[f.key] = v
    return keep


# ---------------------------------------------------------------------------
# 화면 (Flet — 수동 스모크)
# ---------------------------------------------------------------------------
def build_tools_view(page=None, runner_factory=None, prefs_path=None,
                     snapshot_path=None, opener=None) -> ft.Control:
    """도구 화면. runner_factory·opener 는 테스트에서 바꿔 끼운다."""
    import ui_prefs
    from runner import JobRunner

    make_runner = runner_factory or JobRunner
    prefs_path = prefs_path or ui_prefs.PREFS_PATH
    courses = course_names(snapshot_path or SNAPSHOT_PATH)
    _upd = make_updater(page)
    st = {"job": None, "tool": None,
          "values": load_values(ui_prefs.load_prefs(prefs_path))}
    controls: dict = {}          # (도구, 칸) → 입력 컨트롤

    status = ft.Text("도구를 골라 [실행] 을 누르세요.", size=13, color=MUTE)
    log_list = ft.ListView(expand=True, spacing=1, auto_scroll=True, padding=8)
    stop_btn = ft.OutlinedButton("멈추기", icon=ft.Icons.STOP_CIRCLE_OUTLINED,
                                 disabled=True)
    run_btns: dict = {}

    def _update():
        _upd()

    def log(line):
        log_list.controls.append(ft.Text(str(line), size=12, selectable=True,
                                         font_family="Consolas"))
        if len(log_list.controls) > MAX_LOG_LINES:
            del log_list.controls[:len(log_list.controls) - MAX_LOG_LINES]
        _update()

    def _values(tool) -> dict:
        out = {}
        for f in tool.fields:
            c = controls.get((tool.key, f.key))
            if c is None:
                continue
            out[f.key] = c.value
        return out

    def _set_running(on: bool):
        stop_btn.disabled = not on
        for b in run_btns.values():
            b.disabled = on
        _update()

    def _remember(tool, values):
        keep = remembered(tool, values)
        st["values"][tool.key] = keep
        prefs = ui_prefs.load_prefs(prefs_path)
        prefs[PREFS_KEY] = st["values"]
        ui_prefs.save_prefs(prefs, prefs_path)

    def _reveal(tool):
        p = PROJECT_ROOT / tool.reveal
        if opener is not None:
            opener(p)
        else:
            from proc_util import run_hidden
            run_hidden(["explorer", f"/select,{p}"], check=False)
        status.value = f"{tool.reveal} 이 있는 폴더를 열었습니다. 더블클릭하세요."
        status.color = MINT
        _update()

    def _run(tool):
        if st["job"] is not None and st["job"].running:
            return
        values = _values(tool)
        gaps = missing(tool, values)
        bad = bad_values(tool, values)
        if gaps or bad:
            status.value = (f"먼저 채워 주세요: {', '.join(gaps)}" if gaps
                            else " · ".join(bad))
            status.color = ROSE
            _update()
            return
        _remember(tool, values)
        argv = build_argv(tool, values)
        log_list.controls.clear()
        log(f"$ {command_text(argv)}")
        status.value = f"실행 중: {tool.title}"
        status.color = APRI
        st["tool"] = tool

        def on_exit(code):
            st["job"] = None
            if code == 0:
                status.value = f"끝났습니다: {tool.title}"
                status.color = MINT
                if tool.after:
                    log(f"→ {tool.after}")
            elif code == -1:
                status.value = f"멈췄습니다: {tool.title}"
                status.color = MUTE
            else:
                status.value = f"문제가 있었습니다(종료 코드 {code}) — 기록을 확인하세요"
                status.color = ROSE
            _set_running(False)

        job = make_runner(on_line=log, on_exit=on_exit)
        st["job"] = job
        _set_running(True)
        try:
            job.start(argv, cwd=PROJECT_ROOT, env=child_env())
        except Exception as ex:  # noqa: BLE001 - 시작조차 못 하면 알린다
            st["job"] = None
            status.value = f"시작하지 못했습니다: {str(ex)[:120]}"
            status.color = ROSE
            _set_running(False)

    def on_stop(_e=None):
        job = st.get("job")
        if job is not None:
            job.cancel()
            status.value = "멈추는 중…"
            _update()

    stop_btn.on_click = on_stop

    # --- 칸 만들기 --------------------------------------------------------
    picker = None
    if page is not None:
        try:
            picker = ft.FilePicker()
            page.services.append(picker)
        except Exception:  # noqa: BLE001 - 고르기 창이 없어도 경로는 칠 수 있다
            picker = None

    def _browse(field, box):
        async def _h(_e=None):
            if picker is None:
                return
            if field.kind == "folder":
                got = await picker.get_directory_path(dialog_title=field.label)
            else:
                files = await picker.pick_files(
                    dialog_title=field.label,
                    allowed_extensions=list(field.exts) or None)
                got = files[0].path if files else None
            if got:
                box.value = got
                _update()
        return _h

    def _field(tool, f) -> ft.Control:
        saved = (st["values"].get(tool.key) or {}).get(f.key, "")
        if f.kind == "check":
            c = ft.Checkbox(label=f.label, value=False)
            controls[(tool.key, f.key)] = c
            return c
        if f.kind == "course":
            opts = ([ft.DropdownOption(key="", text="(전부)")]
                    if not f.required else [])
            opts += [ft.DropdownOption(key=n, text=n) for n in courses]
            c = ft.Dropdown(label=f.label + (" *" if f.required else ""),
                            options=opts, width=230, dense=True,
                            value=saved if saved in courses else
                            ("" if not f.required else None))
            controls[(tool.key, f.key)] = c
            return c
        if f.kind == "term":
            c = ft.Dropdown(label=f.label + (" *" if f.required else ""),
                            options=[ft.DropdownOption(key="1", text="1학기"),
                                     ft.DropdownOption(key="2", text="2학기")],
                            width=130, dense=True, value=saved or None)
            controls[(tool.key, f.key)] = c
            return c
        width = {"year": 100, "text": 180}.get(f.kind, 360)
        c = ft.TextField(label=f.label + (" *" if f.required else ""),
                         hint_text=f.hint or None, width=width, dense=True,
                         value=saved if f.kind in ("year", "text") else "")
        controls[(tool.key, f.key)] = c
        if f.kind in ("file", "folder"):
            return ft.Row([c, ft.IconButton(
                icon=ft.Icons.FOLDER_OPEN, tooltip="찾아보기",
                on_click=_browse(f, c))], spacing=2, tight=True)
        return c

    def _tag(t) -> ft.Control:
        return ft.Container(
            content=ft.Text(t, size=11, weight=ft.FontWeight.BOLD,
                            color=APRI if t != TAG_AI else MINT),
            bgcolor=ft.Colors.with_opacity(.06, ft.Colors.ON_SURFACE),
            padding=ft.Padding(8, 2, 8, 2), border_radius=99,
            tooltip=TAG_TIPS.get(t))

    def _line(head, body) -> ft.Control:
        return ft.Row([ft.Text(head, size=12, weight=ft.FontWeight.BOLD,
                               color=MUTE, width=56),
                       ft.Text(body, size=13, expand=True)],
                      vertical_alignment=ft.CrossAxisAlignment.START)

    def _card(tool) -> ft.Control:
        head = [ft.Text(tool.title, size=15, weight=ft.FontWeight.BOLD,
                        expand=True)] + [_tag(t) for t in tool.tags]
        rows = [ft.Row(head, spacing=6,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER),
                _line("이럴 때", tool.when), _line("하는 일", tool.does)]
        if tool.fields:
            rows.append(ft.Row([_field(tool, f) for f in tool.fields],
                               spacing=10, wrap=True,
                               vertical_alignment=ft.CrossAxisAlignment.CENTER))
        if tool.reveal:
            btn = ft.OutlinedButton("파일 위치 열기", icon=ft.Icons.FOLDER_OPEN,
                                    on_click=lambda _e, t=tool: _reveal(t))
        else:
            btn = ft.FilledButton("실행", icon=ft.Icons.PLAY_ARROW,
                                  on_click=lambda _e, t=tool: _run(t),
                                  style=ft.ButtonStyle(bgcolor=MINT,
                                                       color="#ffffff"))
            run_btns[tool.key] = btn
        rows.append(ft.Row([btn], alignment=ft.MainAxisAlignment.END))
        return ft.Container(
            content=ft.Column(rows, spacing=8, tight=True),
            padding=16, border_radius=12,
            bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
            border=ft.Border.all(1, ft.Colors.with_opacity(
                .08, ft.Colors.ON_SURFACE)))

    cards = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
    for g in GROUPS:
        tools = [t for t in TOOLS if t.group == g]
        if not tools:
            continue
        cards.controls.append(ft.Text(g, size=13, weight=ft.FontWeight.BOLD,
                                      color=MINT))
        cards.controls += [_card(t) for t in tools]

    log_panel = ft.Container(
        content=ft.Column(
            [ft.Row([ft.Text("기록", size=14, weight=ft.FontWeight.BOLD,
                             color=MINT, expand=True), stop_btn],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
             status,
             ft.Divider(height=9, thickness=1,
                        color=ft.Colors.with_opacity(.10,
                                                     ft.Colors.ON_SURFACE)),
             log_list],
            spacing=6, expand=True),
        width=LOG_WIDTH, padding=14, border_radius=12,
        bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
        border=ft.Border.all(1, ft.Colors.with_opacity(.08,
                                                       ft.Colors.ON_SURFACE)))

    view = ft.Column(
        [ft.Text("도구", size=26, weight=ft.FontWeight.BOLD),
         ft.Text("가끔 돌리는 일들입니다. 명령어를 외우지 않아도 됩니다 — "
                 "'이럴 때' 를 보고 맞는 도구의 [실행] 을 누르세요.",
                 size=13, color=MUTE),
         ft.Divider(height=1),
         ft.Row([cards, log_panel], spacing=14, expand=True,
                vertical_alignment=ft.CrossAxisAlignment.STRETCH)],
        spacing=10, expand=True)
    # 테스트가 들여다볼 손잡이
    view.data = {"run": _run, "stop": on_stop, "controls": controls,
                 "status": status, "log": log_list, "state": st}
    return view
