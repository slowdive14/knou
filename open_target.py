"""[open_target] 파일을 '어디서' 열지 정하는 곳 — 예습노트만 옵시디언으로.

  - 예습노트(.md) → **옵시디언**(obsidian:// URI). 옵시디언이 켜져 있으면 그 창에서
    열리고, 꺼져 있으면 윈도우가 옵시디언을 띄운 뒤 그 노트를 연다(둘 다 한 방식).
  - 그 밖(MP3 등)   → 윈도우 기본 프로그램.
  - 학습현황·퀴즈·PDF → 앱 안에서 직접 그리므로 여기 오지 않는다.

순수 로직(단위테스트):
  - obsidian_uri(path)     : 절대경로 → obsidian://open?path=…(퍼센트 인코딩)
  - is_note(path)          : 옵시디언으로 보낼 파일인가(.md/.markdown)
  - target_for(path)       : "obsidian" | "external"

IO(수동 검증):
  - open_path(path)        : 위 규칙대로 실제로 연다 → {"ok","how","error"?}

⚠️ 경로만 다루며 비밀값은 지나가지 않는다.
"""
from __future__ import annotations

import os
import subprocess
from pathlib import Path
from urllib.parse import quote

NOTE_EXTS = (".md", ".markdown")


def is_note(path) -> bool:
    """옵시디언으로 열 파일(마크다운 노트)인가."""
    return Path(path).suffix.lower() in NOTE_EXTS


def obsidian_uri(path) -> str:
    """절대경로 → `obsidian://open?path=…`.

    vault 이름 대신 절대경로(path)를 쓰면 옵시디언이 알아서 해당 볼트를 찾는다
    (볼트 이름을 몰라도 되고, 볼트를 옮겨도 그대로 동작).
    한글·공백·역슬래시가 섞여도 되도록 전부 퍼센트 인코딩한다.
    """
    p = str(Path(path))
    return "obsidian://open?path=" + quote(p, safe="")


def target_for(path) -> str:
    """이 파일을 어디로 보낼지: 'obsidian' | 'external'."""
    return "obsidian" if is_note(path) else "external"


# ---------------------------------------------------------------------------
# IO (수동 검증)
# ---------------------------------------------------------------------------
def _start(target: str) -> None:
    """윈도우 셸로 열기(URI·파일 모두). startfile 이 없으면 start 명령으로."""
    starter = getattr(os, "startfile", None)
    if starter is not None:
        starter(target)  # noqa: S606 - 사용자가 누른 파일/URI 열기
        return
    subprocess.run(["cmd", "/c", "start", "", target], check=False)


def open_path(path, prefer_obsidian: bool = True) -> dict:
    """규칙대로 파일을 연다. return: {"ok","how","path","error"?}

    노트인데 옵시디언 호출이 실패하면(미설치 등) 기본 프로그램으로 한 번 더 시도한다.
    """
    p = Path(path)
    if not p.exists():
        return {"ok": False, "how": "none", "path": str(p),
                "error": "파일이 없습니다"}
    if prefer_obsidian and is_note(p):
        try:
            _start(obsidian_uri(p))
            return {"ok": True, "how": "obsidian", "path": str(p)}
        except Exception as e:  # noqa: BLE001 - 옵시디언 미설치/프로토콜 미등록
            err = str(e)[:120]
            try:
                _start(str(p))
                return {"ok": True, "how": "external", "path": str(p),
                        "error": f"옵시디언 실행 실패({err}) → 기본 프로그램으로 열었습니다"}
            except Exception as e2:  # noqa: BLE001
                return {"ok": False, "how": "none", "path": str(p),
                        "error": str(e2)[:160]}
    try:
        _start(str(p))
        return {"ok": True, "how": "external", "path": str(p)}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "how": "none", "path": str(p), "error": str(e)[:160]}
