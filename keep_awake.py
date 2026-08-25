"""[keep_awake] 예약 실행 '동안만' Windows 시스템 절전을 억제하는 얇은 런처.

야간 무인 자동 이수 중에는 키보드·마우스 입력이 없어 Windows 유휴 절전 타이머가
작동해 PC가 잠들 수 있다. 절전에 들어가면 영상 재생이 멈춰 시청 시간이 안 쌓이고
(이수 실패), HLS 영상의 시한부 토큰도 만료돼 깨어나도 세션이 죽는다.

이 런처는 main.py 를 자식 프로세스로 돌리는 동안에만 SetThreadExecutionState 로
"시스템을 깨운 채로 둬"(ES_SYSTEM_REQUIRED) 라고 Windows 에 요청한다. main.py 가
끝나면 즉시 해제 → 평소엔 PC가 정상적으로 절전된다. 전역 전원 설정은 건드리지
않으며, 화면(모니터) 절전도 막지 않는다(숨겨진 실행이라 화면은 켤 필요가 없음).

main.py(백엔드)도 손대지 않는다 — 여기서 하위 프로세스로 부를 뿐이다.

사용:  python keep_awake.py <스크립트.py> [인자...]
       (예약 .bat 이 'python.exe -u keep_awake.py main.py --mode 요약 …' 로 호출)
"""
from __future__ import annotations

import subprocess

from proc_util import run_hidden
import sys

# SetThreadExecutionState 플래그
ES_CONTINUOUS = 0x80000000        # 다음 호출 전까지 요청 상태 유지
ES_SYSTEM_REQUIRED = 0x00000001   # 시스템(슬립) 억제
# 숨겨진 실행이라 화면은 켜둘 필요 없음 → ES_DISPLAY_REQUIRED 는 쓰지 않는다.


def _set_state(flags: int) -> bool:
    """SetThreadExecutionState 호출(Windows 전용). 성공 시 True.

    Windows 가 아니거나 API 가 없으면 조용히 False(절전 억제 없이 그대로 진행) —
    런처가 어떤 환경에서도 main.py 실행 자체를 막지 않도록 한다.
    """
    try:
        import ctypes
        res = ctypes.windll.kernel32.SetThreadExecutionState(flags)  # type: ignore[attr-defined]
        return bool(res)
    except (AttributeError, OSError):
        return False


def begin_keep_awake() -> bool:
    """실행 동안 시스템 절전을 억제하기 시작(이 스레드가 살아 있는 한 유지)."""
    return _set_state(ES_CONTINUOUS | ES_SYSTEM_REQUIRED)


def end_keep_awake() -> None:
    """절전 억제 해제(평소 전원 동작으로 복귀). 프로세스 종료 시 자동 해제도 됨."""
    _set_state(ES_CONTINUOUS)


def build_child_command(args: list[str], python: str | None = None) -> list[str]:
    """래퍼가 실행할 자식 명령 argv. args[0]=스크립트, 이후는 그 스크립트 인자.

    python 기본값은 현재 인터프리터(sys.executable) — 예약 .bat 이 venv python
    으로 이 런처를 부르므로 같은 venv 로 main.py 가 실행된다. '-u' 로 자식도
    버퍼링 없이 즉시 로그를 남긴다.
    """
    py = python or sys.executable
    return [py, "-u", *args]


def run(args: list[str]) -> int:
    """절전 억제를 켠 채 자식(main.py)을 끝까지 실행하고 종료코드를 그대로 반환.

    절전 억제 실패(비 Windows 등)와 무관하게 자식은 항상 실행한다. finally 로
    어떤 경우에도(예외·중단) 절전 억제를 반드시 해제한다.
    """
    if not args:
        return 2
    begin_keep_awake()
    try:
        return run_hidden(build_child_command(args)).returncode
    finally:
        end_keep_awake()


if __name__ == "__main__":
    raise SystemExit(run(sys.argv[1:]))
