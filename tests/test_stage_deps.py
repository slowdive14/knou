"""단계 의존성 단위테스트 — 한 단계가 실패해도 무관한 단계는 계속 돌아야 한다.

실측 사례(logs/run_20260819_152412.log): '전체' 실행에서 capture(덱 추출)가
'유효 클립 없음'으로 실패했다. 예전 코드는 단계 실패 시 `break` 라서, 실패 단계
뒤에 오는 단계가 **의존관계와 무관하게** 통째로 취소됐다. 여기서는 산출물이 없어
정말 못 도는 단계만 막히는지 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from main import STAGE_DEPS, dependent_stages, stages_for_mode  # noqa: E402

FULL = stages_for_mode("전체")     # watch, exam, download, summarize, capture


# --- 무관한 단계는 막히지 않는다 -------------------------------------------
def test_capture_failure_blocks_nothing_in_full_run():
    # 덱 추출은 파이프라인의 끝 — 실패해도 막을 후속 단계가 없다
    assert dependent_stages("capture", FULL) == set()


def test_exam_failure_does_not_block_notes():
    # 형성평가가 실패해도 다운로드·요약·덱 매칭은 그대로 진행돼야 한다
    blocked = dependent_stages("exam", FULL)
    assert blocked == set()


def test_watch_failure_does_not_block_notes():
    assert dependent_stages("watch", FULL) == set()


# --- 진짜 의존하는 단계만 막힌다 -------------------------------------------
def test_download_failure_blocks_summarize_and_capture():
    # mp3 가 없으면 요약이 불가능하고, 요약 노트가 없으면 덱 매칭도 불가능(전이)
    assert dependent_stages("download", FULL) == {"summarize", "capture"}


def test_summarize_failure_blocks_capture_only():
    blocked = dependent_stages("summarize", FULL)
    assert blocked == {"capture"}
    assert "exam" not in blocked and "download" not in blocked


def test_transitive_block_is_closed():
    # download → summarize → capture 로 두 칸 건너뛴 의존도 닫혀야 한다
    assert "capture" in dependent_stages("download", ["download", "summarize",
                                                      "capture"])


# --- 범위/형태 --------------------------------------------------------------
def test_only_stages_in_this_run_are_returned():
    # 이번 실행에 없는 단계는 결과에 끼면 안 된다
    assert dependent_stages("download", ["download", "summarize"]) == {"summarize"}


def test_unknown_stage_blocks_nothing():
    assert dependent_stages("없는단계", FULL) == set()


def test_deps_reference_real_stages():
    from main import STAGE_FUNCS
    for stage, needs in STAGE_DEPS.items():
        assert stage in STAGE_FUNCS
        for n in needs:
            assert n in STAGE_FUNCS


def test_watch_and_exam_have_no_deps():
    # 이 둘은 LMS 플레이어만 있으면 되므로 어떤 단계에도 매이면 안 된다
    assert "watch" not in STAGE_DEPS and "exam" not in STAGE_DEPS
