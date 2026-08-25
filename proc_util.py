"""[proc_util] 하위 프로세스를 **콘솔 창 없이** 돌리기 위한 공통 도구.

Windows 에서 ffmpeg/ffprobe 같은 콘솔 프로그램을 그냥 띄우면 실행할 때마다
검은 창이 번쩍인다. 이들은 한 강의를 처리하는 동안 수십~수백 번 불린다
(개념마다 후보 프레임 6장 → 개념 16개면 ffmpeg 만 96번, 여기에 클립별
ffprobe 까지) → 앱을 쓰는 내내 창이 깜빡여 작업을 방해한다.

`CREATE_NO_WINDOW` 를 주면 콘솔을 아예 만들지 않는다. 파이프(capture_output)는
그대로 동작하므로 stdout/stderr 를 읽는 코드는 바뀔 게 없다.

  - NO_WINDOW           : Windows 면 CREATE_NO_WINDOW, 다른 OS 면 0(무해)
  - run_hidden(cmd, …)  : subprocess.run 과 같되 콘솔 창을 띄우지 않는다
  - popen_hidden(cmd, …): subprocess.Popen 의 같은 판본

⚠️ 인자에 비밀값(비밀번호·API 키)이나 시한부 토큰(HLS JWT)이 들어갈 수 있으니
   호출 측은 cmd 를 그대로 로그에 남기지 않는다.
"""
from __future__ import annotations

import subprocess

# Windows 에만 있는 상수 — 다른 OS 에서는 0(플래그 없음)이라 그대로 넘겨도 된다.
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def run_hidden(cmd, **kwargs):
    """subprocess.run + 콘솔 창 숨김.

    호출 측이 creationflags 를 직접 준 경우에는 그 값을 존중한다(덮어쓰지 않음).
    """
    kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.run(cmd, **kwargs)


def popen_hidden(cmd, **kwargs):
    """subprocess.Popen + 콘솔 창 숨김."""
    kwargs.setdefault("creationflags", NO_WINDOW)
    return subprocess.Popen(cmd, **kwargs)
