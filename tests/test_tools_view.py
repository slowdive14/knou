"""도구 화면 — 가끔 돌리는 명령을 설명과 함께 눌러서 실행한다.

'이럴 때는 python ○○.py 를 돌리세요' 라는 안내를 한 번 쓰고 나면 잊는다.
명령마다 이럴 때·하는 일을 적고, 값만 채워 [실행] 을 누르게 한다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

from app.views import tools_view as tv  # noqa: E402

PY = "C:/py/python.exe"


def _tool(key):
    t = tv.tool_by_key(key)
    assert t is not None, key
    return t


# --- 목록 -------------------------------------------------------------------
def test_every_tool_says_when_and_what():
    for t in tv.TOOLS:
        assert t.when and t.does, t.key


def test_every_script_exists():
    """목록에 적힌 명령이 실제로 있어야 누를 수 있다."""
    for t in tv.TOOLS:
        target = t.reveal or t.script
        assert (tv.PROJECT_ROOT / target).exists(), target


def test_the_commands_we_told_about_are_all_here():
    scripts = {t.script for t in tv.TOOLS} | {t.reveal for t in tv.TOOLS}
    for s in ("index_exam_files.py", "build_exam_bank.py", "verify_exams.py",
              "fetch_exam_figures.py", "tag_lectures.py", "build_variants.py",
              "check_variants.py", "fetch_intros.py", "import_docs.py",
              "fetch_knouon_slides.py", "resize_embeds.py", "import_kakao.py",
              "install_compiler.bat"):
        assert s in scripts, s


def test_installing_software_is_left_to_the_person():
    """시스템에 프로그램을 까는 일은 앱이 대신하지 않는다."""
    t = _tool("compiler")
    assert t.reveal and not t.script


# --- 명령 줄 ----------------------------------------------------------------
def test_a_filled_value_becomes_an_option():
    argv = tv.build_argv(_tool("verify"), {"course": "컴퓨터구조",
                                           "year": "2015"}, PY)
    assert argv[:2] == [PY, "-u"]
    assert Path(argv[2]).name == "verify_exams.py"
    assert argv[3:] == ["--course", "컴퓨터구조", "--year", "2015"]


def test_an_empty_value_is_left_out():
    argv = tv.build_argv(_tool("verify"), {"course": "", "year": ""}, PY)
    assert argv[3:] == []


def test_a_ticked_box_adds_its_flag():
    argv = tv.build_argv(_tool("verify"), {"fix": True}, PY)
    assert "--fix" in argv
    assert "--fix" not in tv.build_argv(_tool("verify"), {"fix": False}, PY)


def test_an_inverted_box_adds_its_flag_when_off():
    """한글 변환은 오래 걸려 기본으로 끈다 — 켜야만 바꾼다."""
    t = _tool("figures")
    assert "--no-hwp" in tv.build_argv(t, {"hwp": False}, PY)
    assert "--no-hwp" not in tv.build_argv(t, {"hwp": True}, PY)


def test_positional_values_come_first():
    argv = tv.build_argv(_tool("import_docs"),
                         {"src": "C:/받은 강의록", "course": "바이오통계학",
                          "dry": True}, PY)
    assert argv[3:] == ["C:/받은 강의록", "바이오통계학", "--dry-run"]


def test_the_shown_command_is_short():
    argv = tv.build_argv(_tool("verify"), {"course": "컴퓨터구조"}, PY)
    assert tv.command_text(argv) == "python verify_exams.py --course 컴퓨터구조"


def test_a_path_with_spaces_is_quoted_in_the_shown_command():
    argv = tv.build_argv(_tool("import_docs"),
                         {"src": "C:/받은 강의록", "course": "바이오통계학"}, PY)
    assert '"C:/받은 강의록"' in tv.command_text(argv)


def test_required_values_are_asked_for():
    t = _tool("local_exam")
    assert tv.missing(t, {"course": "C프로그래밍"}) == ["시험지 파일", "연도", "학기"]
    assert tv.missing(t, {"file": "a.hwp", "course": "C프로그래밍",
                          "year": "2014", "term": "1"}) == []


def test_badly_written_values_are_caught():
    t = _tool("local_exam")
    assert tv.bad_values(t, {"year": "14", "term": "3"}) == [
        "연도는 2014 처럼 네 자리로 적어 주세요", "학기는 1 또는 2 입니다"]


def test_the_child_prints_korean_in_utf8():
    env = tv.child_env()
    assert env["PYTHONIOENCODING"] == "utf-8"


def test_only_repeating_values_are_remembered():
    """켜 둔 '바로잡기' 가 다음에도 켜져 있으면 모르고 고치게 된다."""
    got = tv.remembered(_tool("verify"), {"course": "자료구조", "fix": True})
    assert got == {"course": "자료구조"}
    got = tv.remembered(_tool("kakao"), {"file": "C:/대화.txt", "nick": "잔향"})
    assert got == {"nick": "잔향"}


# --- 화면 -------------------------------------------------------------------
class FakeRunner:
    started: list = []

    def __init__(self, on_line=None, on_exit=None):
        self.on_line, self.on_exit = on_line, on_exit
        self.running = False

    def start(self, argv, cwd=None, env=None):
        FakeRunner.started.append(argv)
        self.running = True
        self.on_line("한 줄")
        self.running = False
        self.on_exit(0)

    def cancel(self):
        self.on_exit(-1)


def _snapshot(tmp_path):
    f = tmp_path / "lectures.json"
    f.write_text(json.dumps({"courses": [
        {"name": "컴퓨터구조", "lectures": [{}] * 15},
        {"name": "자료구조", "lectures": [{}] * 15}]}, ensure_ascii=False),
        encoding="utf-8")
    return f


def _view(tmp_path, opened=None):
    FakeRunner.started = []
    return tv.build_tools_view(
        runner_factory=FakeRunner, prefs_path=tmp_path / "prefs.json",
        snapshot_path=_snapshot(tmp_path),
        opener=(opened.append if opened is not None else None))


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _texts(view):
    return [str(t.value or "") for t in _walk(view) if isinstance(t, ft.Text)]


def test_every_tool_has_a_card(tmp_path):
    said = _texts(_view(tmp_path))
    for t in tv.TOOLS:
        assert t.title in said


def test_running_a_tool_shows_its_output(tmp_path):
    v = _view(tmp_path)
    c = v.data["controls"]
    c[("verify", "course")].value = "컴퓨터구조"
    v.data["run"](_tool("verify"))
    assert FakeRunner.started[0][3:] == ["--course", "컴퓨터구조"]
    logged = [str(t.value) for t in v.data["log"].controls]
    assert logged[0] == "$ python verify_exams.py --course 컴퓨터구조"
    assert "한 줄" in logged
    assert v.data["status"].value == "끝났습니다: 기출 문항 확인·바로잡기"


def test_a_missing_value_stops_the_run(tmp_path):
    v = _view(tmp_path)
    v.data["run"](_tool("local_exam"))
    assert FakeRunner.started == []
    assert v.data["status"].value.startswith("먼저 채워 주세요: 시험지 파일")


def test_the_next_step_is_told_after_the_run(tmp_path):
    v = _view(tmp_path)
    c = v.data["controls"]
    c[("local_exam", "file")].value = "C:/241.hwp"
    c[("local_exam", "course")].value = "컴퓨터구조"
    c[("local_exam", "year")].value = "2014"
    c[("local_exam", "term")].value = "2"
    v.data["run"](_tool("local_exam"))
    logged = [str(t.value) for t in v.data["log"].controls]
    assert any("기출 문항 확인" in t and t.startswith("→") for t in logged)


def test_the_values_come_back_next_time(tmp_path):
    v = _view(tmp_path)
    v.data["controls"][("kakao", "nick")].value = "잔향"
    v.data["controls"][("kakao", "file")].value = "C:/대화.txt"
    v.data["run"](_tool("kakao"))
    again = tv.build_tools_view(runner_factory=FakeRunner,
                                prefs_path=tmp_path / "prefs.json",
                                snapshot_path=_snapshot(tmp_path))
    assert again.data["controls"][("kakao", "nick")].value == "잔향"
    assert again.data["controls"][("kakao", "file")].value == ""


def test_the_course_list_comes_from_the_lectures(tmp_path):
    v = _view(tmp_path)
    dd = v.data["controls"][("verify", "course")]
    assert [o.key for o in dd.options] == ["", "컴퓨터구조", "자료구조"]


def test_the_compiler_card_only_opens_the_folder(tmp_path):
    opened = []
    v = _view(tmp_path, opened)
    btn = next(b for b in _walk(v) if isinstance(b, ft.OutlinedButton)
               and str(b.content) == "파일 위치 열기")
    btn.on_click(None)
    assert opened == [tv.PROJECT_ROOT / "install_compiler.bat"]
    assert FakeRunner.started == []
