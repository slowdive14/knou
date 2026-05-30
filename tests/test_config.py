"""config.load_config 단위 테스트."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

# 프로젝트 루트를 import 경로에 추가
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import Config, load_config  # noqa: E402


def _valid_env() -> dict:
    return {
        "KNOU_ID": "myid",
        "KNOU_PW": "secret",
        "GEMINI_API_KEY": "AIzaTEST123",
        "VAULT_PATH": "C:/vault",
    }


def test_missing_all_raises_with_key_names():
    with pytest.raises(ValueError) as exc:
        load_config(env={})
    msg = str(exc.value)
    for key in ("KNOU_ID", "KNOU_PW", "GEMINI_API_KEY", "VAULT_PATH"):
        assert key in msg


def test_missing_one_lists_only_that_key():
    env = _valid_env()
    del env["GEMINI_API_KEY"]
    with pytest.raises(ValueError) as exc:
        load_config(env=env)
    assert "GEMINI_API_KEY" in str(exc.value)
    assert "KNOU_ID" not in str(exc.value)


def test_empty_string_counts_as_missing():
    env = _valid_env()
    env["KNOU_PW"] = ""
    with pytest.raises(ValueError) as exc:
        load_config(env=env)
    assert "KNOU_PW" in str(exc.value)


def test_valid_env_loads_config():
    cfg = load_config(env=_valid_env())
    assert isinstance(cfg, Config)
    assert cfg.knou_id == "myid"
    assert cfg.knou_pw == "secret"
    assert cfg.gemini_api_key == "AIzaTEST123"
    assert cfg.vault_path == Path("C:/vault")


def test_defaults_applied():
    cfg = load_config(env=_valid_env())
    assert cfg.summary_subdir == "방송대"
    assert cfg.playback_speed == 2.0
    assert cfg.headless is False


def test_overrides_parsed():
    env = _valid_env()
    env.update({"PLAYBACK_SPEED": "1.5", "HEADLESS": "true", "SUMMARY_SUBDIR": "KNOU"})
    cfg = load_config(env=env)
    assert cfg.playback_speed == 1.5
    assert cfg.headless is True
    assert cfg.summary_subdir == "KNOU"


def test_summary_dir_joins_subdir():
    env = _valid_env()
    env["SUMMARY_SUBDIR"] = "방송대"
    cfg = load_config(env=env)
    assert cfg.summary_dir == Path("C:/vault") / "방송대"
