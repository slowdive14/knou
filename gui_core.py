"""GUI 순수 로직 — .env 안전 읽기/쓰기, 비밀값 마스킹, 설정 검증, 첫 실행 판정.

⚠️ 비밀번호·GEMINI_API_KEY 등 비밀값을 로그/콘솔에 절대 평문 출력하지 않는다.
이 모듈은 파일 IO만 하며 값을 print 하지 않는다(호출 측은 표시 시 mask_secret 사용).

함수:
  - read_env_file(path)            : .env → dict (없으면 {})
  - write_env_file(path, updates)  : 기존 주석·미지 키·줄 순서 보존하며 지정 키만 갱신
  - mask_secret(value, keep=4)     : 화면 표시용 마스킹("AIza…(가림)")
  - validate_settings(d)           : 누락 필수키 리스트(config.REQUIRED 재사용)
  - first_run_needed(path)         : .env에 필수키가 빠졌으면 True(설정 마법사 유도)
"""
from __future__ import annotations

from pathlib import Path

from config import BASE_DIR, REQUIRED

# 기본 .env 경로(프로젝트 루트). 함수는 path 인자로 재정의 가능(테스트 용이).
ENV_PATH = BASE_DIR / ".env"

# 설정 화면에서 다루는 키(표시 순서). 필수 4개 + 선택 2개.
SETTINGS_KEYS = [
    "KNOU_ID", "KNOU_PW", "GEMINI_API_KEY",
    "VAULT_PATH", "SUMMARY_SUBDIR", "PLAYBACK_SPEED",
]
# 화면에서 가려야 하는 비밀 키.
SECRET_KEYS = {"KNOU_PW", "GEMINI_API_KEY"}


def _strip_quotes(v: str) -> str:
    """값을 감싼 짝 따옴표(' 또는 ")가 있으면 제거."""
    if len(v) >= 2 and v[0] == v[-1] and v[0] in ("'", '"'):
        return v[1:-1]
    return v


def read_env_file(path=ENV_PATH) -> dict:
    """`.env`를 읽어 {KEY: VALUE} dict로. 파일이 없으면 {}.

    주석(#)·빈 줄·'='이 없는 줄은 무시. 값은 첫 '=' 뒤 전체
    (앞뒤 공백 제거 후 감싼 따옴표 제거). 값 안의 '='는 그대로 보존.
    """
    p = Path(path)
    if not p.exists():
        return {}
    out: dict[str, str] = {}
    for raw in p.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        if not key:
            continue
        out[key] = _strip_quotes(val.strip())
    return out


def write_env_file(path, updates: dict) -> None:
    """`.env`에 updates를 반영하되 기존 주석·미지 키·줄 순서를 보존.

    - 이미 있는 키: 그 줄의 값만 교체(키 표기 보존)
    - 없는 키: 파일 끝에 'KEY=value'로 추가
    파일이 없으면 새로 만든다. (값은 그대로 기록하며 로그 출력하지 않음)
    """
    p = Path(path)
    updates = dict(updates)  # 호출자 dict 보호
    lines: list[str] = []
    if p.exists():
        lines = p.read_text(encoding="utf-8").splitlines()

    applied: set[str] = set()
    out_lines: list[str] = []
    for raw in lines:
        stripped = raw.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            key = stripped.partition("=")[0].strip()
            if key in updates and key not in applied:
                out_lines.append(f"{key}={updates[key]}")
                applied.add(key)
                continue
        out_lines.append(raw)

    # 아직 반영되지 않은 신규 키는 파일 끝에 추가
    for key, val in updates.items():
        if key not in applied:
            out_lines.append(f"{key}={val}")

    p.parent.mkdir(parents=True, exist_ok=True)
    text = "\n".join(out_lines)
    if text and not text.endswith("\n"):
        text += "\n"
    p.write_text(text, encoding="utf-8")


def mask_secret(value, keep: int = 4) -> str:
    """비밀값을 화면 표시용으로 마스킹.

    빈값은 ''. 길이가 keep 이하이면 앞부분도 노출하지 않는다.
    """
    if not value:
        return ""
    s = str(value)
    if len(s) <= keep:
        return "…(가림)"
    return f"{s[:keep]}…(가림)"


def validate_settings(d: dict) -> list:
    """누락(빈 문자열/공백 포함) 필수키 리스트. config.REQUIRED 재사용."""
    return [k for k in REQUIRED if not str(d.get(k) or "").strip()]


def first_run_needed(path=ENV_PATH) -> bool:
    """`.env`에 필수키가 하나라도 빠졌으면 True → 설정 마법사로 유도."""
    return bool(validate_settings(read_env_file(path)))
