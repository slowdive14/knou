"""모든 테스트에 공통 — 진짜 기록 파일을 건드리지 않게 한다."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def _model_limits_in_tmp(tmp_path, monkeypatch):
    """모델 한도 기록(model_limits.json)은 테스트마다 임시 폴더에 둔다.

    가짜 클라이언트가 429·404·503 을 내면 generate 가 그 모델을 쉬게 하거나
    뒤로 돌린다고 적어 두는데, 그게 진짜 기록에 남으면 앱이 멀쩡한 모델을
    하루 동안 건너뛴다.
    """
    import summarize
    monkeypatch.setattr(summarize, "LIMITS_PATH",
                        tmp_path / "model_limits.json")
