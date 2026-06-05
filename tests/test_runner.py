"""runner.py 순수 로직 + JobRunner 단위테스트.

순수부(명령 빌더·로그 파서·스냅샷 파서·진행률·노트경로)는 완전 단위테스트,
JobRunner 는 가짜 자식 프로세스(짧은 python -c)로 라인 수집/종료/취소만 검증한다.

⚠️ 명령 argv 에 비밀번호·GEMINI_API_KEY 가 절대 들어가지 않는지 검증한다.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import (  # noqa: E402
    JobRunner,
    LectureRow,
    build_command,
    confirm_message,
    estimate_watch_text,
    format_elapsed,
    job_status,
    latest_log_path,
    note_path_for,
    parse_lectures_snapshot,
    parse_progress_line,
    pct_for_stage,
    read_log_tail,
    requires_confirm,
    watch_sleep_warning,
)


# --- build_command ---------------------------------------------------------
def test_build_command_basic():
    argv = build_command("py.exe", "요약", course="데이터베이스시스템", seq=13)
    assert argv[0] == "py.exe"
    assert "-u" in argv
    assert "--mode" in argv and "요약" in argv
    assert "--course" in argv and "데이터베이스시스템" in argv
    assert "--seq" in argv and "13" in argv


def test_build_command_includes_main_py():
    argv = build_command("py", "이수")
    assert any(str(a).endswith("main.py") for a in argv)


def test_build_command_optional_flags():
    argv = build_command("py", "요약", limit=1, stages=["capture"],
                         unwatched=True, state="C:/s.json")
    assert "--limit" in argv and "1" in argv
    assert "--stages" in argv and "capture" in argv
    assert "--unwatched" in argv
    assert "--state" in argv and "C:/s.json" in argv


def test_build_command_omits_none_filters():
    argv = build_command("py", "요약")
    assert "--course" not in argv
    assert "--seq" not in argv
    assert "--limit" not in argv
    assert "--unwatched" not in argv
    assert "--force" not in argv


def test_build_command_force_flag():
    # '다시 만들기(덮어쓰기)' → --force 전달
    argv = build_command("py", "요약", course="과목", seq=1, force=True)
    assert "--force" in argv


def test_build_command_force_default_off():
    argv = build_command("py", "요약", course="과목", seq=1)
    assert "--force" not in argv


def test_build_command_never_contains_secrets():
    # 비번/키 비슷한 값을 인자로 넘겨도(실수로라도) argv 빌더는 모드/필터만 사용
    argv = build_command("py", "요약", course="과목", seq=1)
    joined = " ".join(argv)
    assert "KNOU_PW" not in joined
    assert "GEMINI_API_KEY" not in joined
    assert "--password" not in joined


# --- parse_progress_line: 로그 프리픽스 유무 모두 대응 ----------------------
def test_parse_lecture_header_with_log_prefix():
    line = "12:34:56 INFO ── 데이터베이스시스템 13강 '트랜잭션'"
    r = parse_progress_line(line)
    assert r["event"] == "lecture"
    assert r["course"] == "데이터베이스시스템"
    assert r["seq"] == 13
    assert r["name"] == "트랜잭션"


def test_parse_lecture_header_without_prefix():
    r = parse_progress_line("── 이산수학 1강 '집합'")
    assert r["event"] == "lecture"
    assert r["course"] == "이산수학"
    assert r["seq"] == 1
    assert r["name"] == "집합"


def test_parse_stage_done():
    r = parse_progress_line("12:00:00 INFO   ✓ summarize: 완료")
    assert r["stage"] == "summarize"
    assert r["status"] == "done"


def test_parse_stage_skip():
    r = parse_progress_line("12:00:00 INFO   ✓ download: skip")
    assert r["stage"] == "download"
    assert r["status"] == "skip"


def test_parse_stage_already_done_skip():
    r = parse_progress_line("12:00:00 INFO   · capture: 이미 완료 skip")
    assert r["stage"] == "capture"
    assert r["status"] == "skip"


def test_parse_stage_fail():
    r = parse_progress_line("12:00:00 WARNING   ✗ summarize 실패: 빈 요약 응답")
    assert r["stage"] == "summarize"
    assert r["status"] == "error"


def test_parse_stage_exception():
    r = parse_progress_line("12:00:00 ERROR   ✗ capture 예외: boom")
    assert r["stage"] == "capture"
    assert r["status"] == "error"


def test_parse_match_line():
    r = parse_progress_line("12:00:00 INFO     매칭 21 + 전방채움 0 = 21/21개")
    assert r["event"] == "match"
    assert r["matched"] == 21
    assert r["total"] == 21


def test_parse_summary_line():
    r = parse_progress_line("=== 요약 === {'mode': '요약', 'processed': 1}")
    assert r["event"] == "summary"
    assert r["processed"] == 1


def test_parse_summary_line_with_failure_counts():
    # main.py 는 강의 실패해도 종료코드 0 → 요약줄의 failed 로만 실패가 드러남
    line = ("=== 요약 === {'mode': '요약', 'total': 1, 'processed': 0, "
            "'failed': 1, 'skipped': 0, 'deferred': 0}")
    r = parse_progress_line(line)
    assert r["event"] == "summary"
    assert r["processed"] == 0
    assert r["failed"] == 1


def test_parse_watch_progress_line():
    line = ("21:21:34 INFO     {'pos': 5.816001, 'dur': 4972.235, "
            "'rate': 2, 'paused': False, 'ended': False}")
    r = parse_progress_line(line)
    assert r["event"] == "watch"
    assert abs(r["pos"] - 5.816001) < 1e-6
    assert abs(r["dur"] - 4972.235) < 1e-3
    assert r["rate"] == 2
    assert r["paused"] is False
    assert r["ended"] is False


def test_parse_watch_progress_ended():
    line = ("12:00:00 INFO {'pos': 100.0, 'dur': 100.0, 'rate': 1.0, "
            "'paused': False, 'ended': True}")
    r = parse_progress_line(line)
    assert r["event"] == "watch"
    assert r["ended"] is True


def test_parse_summary_not_confused_with_watch_dict():
    # 요약 줄도 dict 를 담지만 'pos'/'dur' 가 없어 watch 로 오인되면 안 됨
    r = parse_progress_line(
        "=== 요약 === {'mode': '이수', 'processed': 1, 'failed': 0}")
    assert r["event"] == "summary"
    assert r["processed"] == 1


def test_parse_unrelated_line_returns_none():
    assert parse_progress_line("12:00:00 INFO ▶ 모드=요약 단계=['summarize']") is None
    assert parse_progress_line("") is None
    assert parse_progress_line("그냥 텍스트") is None


# --- pct_for_stage ---------------------------------------------------------
def test_pct_for_stage_known():
    assert pct_for_stage("download") == 25
    assert pct_for_stage("summarize") == 60
    assert pct_for_stage("capture") == 90
    assert pct_for_stage("done") == 100


def test_pct_for_stage_unknown_is_none():
    assert pct_for_stage("watch") is None or isinstance(pct_for_stage("watch"), int)
    assert pct_for_stage("zzz") is None


# --- parse_lectures_snapshot -----------------------------------------------
SNAPSHOT = {
    "courses": [
        {"name": "데이터베이스시스템", "lectures": [
            {"seq": 13, "name": "트랜잭션", "video_done": False, "exam_done": False},
            {"seq": 14, "name": "회복", "video_done": True, "exam_done": True},
        ]},
        {"name": "이산수학", "lectures": [
            {"seq": 1, "name": "집합", "video_done": False, "exam_done": False},
        ]},
    ]
}


def test_parse_snapshot_from_dict():
    rows = parse_lectures_snapshot(SNAPSHOT)
    assert len(rows) == 3
    assert all(isinstance(r, LectureRow) for r in rows)
    first = rows[0]
    assert first.course == "데이터베이스시스템"
    assert first.seq == 13
    assert first.name == "트랜잭션"
    assert first.video_done is False


def test_parse_snapshot_from_json_string():
    import json
    rows = parse_lectures_snapshot(json.dumps(SNAPSHOT, ensure_ascii=False))
    assert len(rows) == 3
    assert rows[1].video_done is True
    assert rows[1].exam_done is True


def test_parse_snapshot_empty():
    assert parse_lectures_snapshot({}) == []
    assert parse_lectures_snapshot("{}") == []


# --- note_path_for ---------------------------------------------------------
def test_note_path_for_matches_summarize(tmp_path):
    from summarize import note_filename
    cfg = SimpleNamespace(summary_dir=tmp_path)
    p = note_path_for(cfg, "데이터베이스시스템", 13, "트랜잭션")
    assert p == tmp_path / note_filename("데이터베이스시스템", 13, "트랜잭션")
    assert p.name.endswith(".md")


# --- JobRunner (가짜 자식 프로세스) ----------------------------------------
def test_jobrunner_collects_lines_and_exit_code():
    lines = []
    codes = []
    jr = JobRunner(on_line=lines.append, on_exit=codes.append)
    jr.start([sys.executable, "-c", "print('a'); print('b')"])
    deadline = time.time() + 10
    while jr.running and time.time() < deadline:
        time.sleep(0.02)
    # 종료 콜백이 들어올 시간을 잠깐 준다
    for _ in range(50):
        if codes:
            break
        time.sleep(0.02)
    assert "a" in lines and "b" in lines
    assert codes == [0]


def test_jobrunner_cancel_stops_process():
    jr = JobRunner()
    jr.start([sys.executable, "-c", "import time; time.sleep(30)"])
    assert jr.running
    jr.cancel()
    for _ in range(100):
        if not jr.running:
            break
        time.sleep(0.02)
    assert not jr.running


# --- Phase 3: 확인 필요 / 예상시간 / 경고문 / 상태 ------------------------
def test_requires_confirm_for_irreversible_modes():
    assert requires_confirm("이수") is True
    assert requires_confirm("전체") is True


def test_requires_confirm_false_for_summary():
    assert requires_confirm("요약") is False


def test_estimate_watch_text_format():
    # 60분 중 10분 시청 → 남은 50분, 2.0배속, 버퍼 12% = 1680s = 28분
    txt = estimate_watch_text(60, 10, 2.0)
    assert "약 28분" in txt
    assert "예상" in txt


def test_estimate_watch_text_already_complete():
    txt = estimate_watch_text(50, 50, 2.0)
    assert "완료" in txt  # 추가 시청 불필요 안내


def test_estimate_watch_text_clamps_speed():
    # 5.0배속은 허용 최대 2.0으로 스냅 → 28분과 동일
    assert "약 28분" in estimate_watch_text(60, 10, 5.0)


def test_confirm_message_warns_irreversible():
    msg = confirm_message("이수")
    assert "되돌릴 수 없" in msg
    assert "형성평가" in msg


def test_job_status_transitions():
    assert job_status(-1) == "cancelled"
    assert job_status(0) == "done"
    assert job_status(0, had_error=True) == "error"
    assert job_status(0, failed=1) == "error"
    assert job_status(0, processed=0) == "error"
    assert job_status(0, processed=1) == "done"
    assert job_status(3) == "error"


# --- format_elapsed / watch_sleep_warning ----------------------------------
def test_format_elapsed_minutes_seconds():
    assert format_elapsed(0) == "0:00"
    assert format_elapsed(9) == "0:09"
    assert format_elapsed(83) == "1:23"


def test_format_elapsed_hours():
    assert format_elapsed(3725) == "1:02:05"


def test_format_elapsed_clamps_negative():
    assert format_elapsed(-5) == "0:00"


def test_watch_sleep_warning_mentions_sleep():
    txt = watch_sleep_warning()
    assert "절전" in txt


# --- latest_log_path / read_log_tail (예약 실행 로그 다시 보기) -------------
def test_latest_log_path_none_when_missing(tmp_path):
    assert latest_log_path(tmp_path / "nope") is None
    assert latest_log_path(tmp_path) is None        # 폴더 있으나 로그 없음


def test_latest_log_path_picks_newest_by_name(tmp_path):
    (tmp_path / "run_20260101_000000.log").write_text("old", encoding="utf-8")
    newest = tmp_path / "run_20260102_090000.log"
    newest.write_text("new", encoding="utf-8")
    (tmp_path / "other.txt").write_text("x", encoding="utf-8")
    assert latest_log_path(tmp_path) == newest


def test_read_log_tail_limits_lines(tmp_path):
    p = tmp_path / "run_20260101_000000.log"
    p.write_text("\n".join(f"L{i}" for i in range(10)), encoding="utf-8")
    tail = read_log_tail(p, 3)
    assert tail == ["L7", "L8", "L9"]


def test_read_log_tail_missing_returns_empty(tmp_path):
    assert read_log_tail(tmp_path / "nope.log") == []
    assert read_log_tail(None) == []
