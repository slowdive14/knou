"""실행 내내 절전을 억제하는가 — 앱에서 누른 실행도 포함해서.

실측 사고(logs/run_20260904_103640.log · C프로그래밍 8강, 80분 영상):

    12:17:36  ── C프로그래밍 8강 '배열과 포인터(1)'
    16:17:46  ✓ watch: 완료          ← 4시간

2배속이면 40분이면 끝날 영상인데 3시간 넘게 잠들어 있었다. 예약 실행만
keep_awake.py 를 거쳤고, 앱에서 누른 실행은 억제가 전혀 걸리지 않았기 때문이다.
이제 main.run() 이 어떤 경로로 실행되든 직접 억제를 건다.

⚠️ 이 억제는 **유휴 절전**만 막는다. 뚜껑을 닫는 것처럼 사람이 명시적으로
   지시한 절전은 Windows 정책상 프로그램이 막을 수 없다.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


@pytest.fixture
def calls(monkeypatch):
    """begin/end 호출 순서를 기록하는 가짜 keep_awake."""
    seen: list[str] = []
    import keep_awake

    monkeypatch.setattr(keep_awake, "begin_keep_awake",
                        lambda: (seen.append("begin"), True)[1])
    monkeypatch.setattr(keep_awake, "end_keep_awake",
                        lambda: seen.append("end"))
    return seen


def test_run_holds_the_system_awake(calls, monkeypatch):
    monkeypatch.setattr(main, "_run", lambda *a, **kw: {"processed": 1})
    assert main.run("요약")["processed"] == 1
    assert calls == ["begin", "end"]


def test_release_happens_even_on_failure(calls, monkeypatch):
    def _boom(*a, **kw):
        raise RuntimeError("로그인 실패")

    monkeypatch.setattr(main, "_run", _boom)
    with pytest.raises(RuntimeError):
        main.run("요약")
    assert calls == ["begin", "end"]      # 실패해도 반드시 해제한다


def test_arguments_pass_through(calls, monkeypatch):
    got = {}

    def _spy(*a, **kw):
        got.update(kw)
        got["args"] = a
        return {}

    monkeypatch.setattr(main, "_run", _spy)
    main.run("전체", course="컴퓨터구조", seq=10, force=True)
    assert got["args"] == ("전체",)
    assert got["course"] == "컴퓨터구조" and got["seq"] == 10
    assert got["force"] is True
    assert got["awake"] is True           # 로그 표시용으로 전달된다


def test_run_is_not_the_same_object_as_inner():
    # 래퍼를 거치지 않고 _run 이 직접 노출되면 억제가 빠진다
    assert main.run is not main._run
