"""콘솔 창 숨김 단위테스트 — 실행 중 검은 창이 번쩍이지 않아야 한다.

실측 불편: 한 강의를 처리하는 동안 ffmpeg/ffprobe 가 수십~수백 번 불리는데
(개념 16개 × 후보 프레임 6장 = ffmpeg 96번 + 클립별 ffprobe), Windows 에서
콘솔 프로그램을 그냥 띄우면 그때마다 창이 번쩍인다. CREATE_NO_WINDOW 를 주면
콘솔을 아예 만들지 않으면서 파이프(capture_output)는 그대로 동작한다.

여기서는 (1) run_hidden 이 플래그를 붙이는지, (2) ffmpeg/ffprobe 를 부르는
자리들이 **bare subprocess.run 으로 되돌아가지 않았는지** 를 지킨다.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import capture  # noqa: E402
import deck_match  # noqa: E402
import extra_video  # noqa: E402
import proc_util  # noqa: E402
from proc_util import NO_WINDOW, run_hidden  # noqa: E402


class _Done:
    returncode = 0
    stdout = "12.5"
    stderr = ""


# --- run_hidden 자체 --------------------------------------------------------
def test_run_hidden_adds_no_window_flag(monkeypatch):
    seen = {}

    def _fake(cmd, **kw):
        seen.update(kw)
        return _Done()

    monkeypatch.setattr(proc_util.subprocess, "run", _fake)
    run_hidden(["ffmpeg"], capture_output=True)
    assert seen["creationflags"] == NO_WINDOW
    assert seen["capture_output"] is True     # 다른 인자는 그대로 전달


def test_run_hidden_respects_explicit_flags(monkeypatch):
    seen = {}
    monkeypatch.setattr(proc_util.subprocess, "run",
                        lambda cmd, **kw: (seen.update(kw), _Done())[1])
    run_hidden(["x"], creationflags=123)
    assert seen["creationflags"] == 123        # 호출 측 지정을 덮어쓰지 않는다


def test_no_window_matches_platform():
    if sys.platform == "win32":
        assert NO_WINDOW == subprocess.CREATE_NO_WINDOW
    else:
        assert NO_WINDOW == 0                  # 다른 OS 에선 무해한 0


# --- ffmpeg/ffprobe 호출부가 숨김 경로를 쓰는가 ------------------------------
def _record(monkeypatch, module):
    calls = []

    def _fake(cmd, **kw):
        calls.append(list(cmd))
        return _Done()

    monkeypatch.setattr(module, "run_hidden", _fake)
    return calls


def test_probe_duration_uses_hidden_runner(monkeypatch):
    calls = _record(monkeypatch, capture)
    assert capture.probe_duration("http://x/v.m3u8") == 12.5
    assert calls and calls[0][0] == capture.FFPROBE


def test_capture_frame_uses_hidden_runner(monkeypatch, tmp_path):
    calls = _record(monkeypatch, capture)
    out = tmp_path / "f.jpg"
    out.write_bytes(b"jpegdata")               # ffmpeg 가 만든 셈 치고
    capture.capture_frame("http://x/v.m3u8", 10, out)
    assert calls and calls[0][0] == capture.FFMPEG


def test_extract_audio_uses_hidden_runner(monkeypatch, tmp_path):
    calls = _record(monkeypatch, extra_video)
    out = tmp_path / "a.mp3"
    out.write_bytes(b"mp3data")
    res = extra_video.extract_audio("http://x/v.m3u8", out)
    assert res["ok"] is True
    assert calls and calls[0][0] == extra_video.FFMPEG


# --- 되돌아가기 방지(소스 수준) ---------------------------------------------
_ALLOWED_BARE = {
    "proc_util.py",       # 여기가 감싸는 당사자
    "runner.py",          # creationflags 를 직접 준다
    "schedule_win.py",    # creationflags 를 직접 준다
    "deploy.py",          # creationflags 를 직접 준다
    "open_target.py",     # os.startfile 우선, cmd 는 비-Windows 폴백
}


def test_no_bare_subprocess_in_media_modules():
    """ffmpeg/ffprobe 를 부르는 모듈이 bare subprocess.run 으로 돌아가지 않게."""
    root = Path(__file__).resolve().parent.parent
    for name in ("capture.py", "deck_match.py", "extra_video.py",
                 "keep_awake.py", "recon.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "subprocess.run(" not in src, f"{name} 에 bare subprocess.run"
        assert "run_hidden" in src, f"{name} 이 run_hidden 을 안 쓴다"


def test_allowed_modules_pass_flags_themselves():
    root = Path(__file__).resolve().parent.parent
    for name in ("runner.py", "schedule_win.py", "deploy.py"):
        src = (root / name).read_text(encoding="utf-8")
        assert "creationflags" in src, f"{name} 에 창 숨김 플래그가 없다"
