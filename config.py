"""환경설정 로드.

.env 파일이나 환경변수에서 설정을 읽어 Config 객체로 돌려준다.
필수 값이 없으면 어떤 키가 빠졌는지 명확히 알려준다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Mapping

from dotenv import load_dotenv

# 반드시 있어야 하는 환경변수
REQUIRED = ["KNOU_ID", "KNOU_PW", "GEMINI_API_KEY", "VAULT_PATH"]

BASE_DIR = Path(__file__).resolve().parent


def _to_bool(value: str) -> bool:
    return str(value).strip().lower() in ("1", "true", "yes", "y", "on")


@dataclass(frozen=True)
class Config:
    knou_id: str
    knou_pw: str
    gemini_api_key: str
    vault_path: Path
    summary_subdir: str = "방송대"
    playback_speed: float = 2.0
    headless: bool = False
    base_dir: Path = BASE_DIR
    auth_dir: Path = field(default_factory=lambda: BASE_DIR / ".auth")
    downloads_dir: Path = field(default_factory=lambda: BASE_DIR / "downloads")
    logs_dir: Path = field(default_factory=lambda: BASE_DIR / "logs")

    @property
    def summary_dir(self) -> Path:
        """요약 노트를 저장할 볼트 내 폴더."""
        return self.vault_path / self.summary_subdir


def load_config(
    env: Mapping[str, str] | None = None,
    *,
    use_dotenv: bool = True,
) -> Config:
    """설정을 로드한다.

    env가 주어지면 그 매핑에서 읽고(테스트용), 아니면 .env + os.environ에서 읽는다.
    필수 키가 비어 있으면 ValueError를 던진다.
    """
    if env is None:
        if use_dotenv:
            load_dotenv(BASE_DIR / ".env")
        src: Mapping[str, str] = os.environ
    else:
        src = env

    missing = [k for k in REQUIRED if not src.get(k)]
    if missing:
        raise ValueError(
            f"필수 환경변수 누락: {', '.join(missing)} — .env 파일을 확인하세요 "
            f"(.env.example 참고)."
        )

    return Config(
        knou_id=src["KNOU_ID"],
        knou_pw=src["KNOU_PW"],
        gemini_api_key=src["GEMINI_API_KEY"],
        vault_path=Path(src["VAULT_PATH"]),
        summary_subdir=src.get("SUMMARY_SUBDIR") or "방송대",
        playback_speed=float(src.get("PLAYBACK_SPEED") or 2.0),
        headless=_to_bool(src.get("HEADLESS") or "false"),
    )


if __name__ == "__main__":
    # 직접 실행하면 현재 설정을 확인 (비밀번호는 가림)
    cfg = load_config()
    print("✅ 설정 로드 성공")
    print(f"  KNOU_ID      : {cfg.knou_id}")
    print(f"  KNOU_PW      : {'*' * len(cfg.knou_pw)}")
    print(f"  GEMINI_API   : {cfg.gemini_api_key[:6]}...(가림)")
    print(f"  VAULT_PATH   : {cfg.vault_path}")
    print(f"  요약 폴더    : {cfg.summary_dir}")
    print(f"  배속         : {cfg.playback_speed}x")
    print(f"  headless     : {cfg.headless}")
