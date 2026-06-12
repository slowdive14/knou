"""schedule_win.py 순수 로직 단위테스트 (Phase 4 — Windows 작업 스케줄러).

실제 `schtasks` 등록은 수동 검증. 여기서는 인자/스크립트 빌더 · CSV 파서 ·
시각 검증만 테스트한다(Windows 외 환경에서도 순수부는 통과해야 함).

⚠️ 예약 스크립트(.bat)·schtasks argv 어디에도 비밀번호·GEMINI_API_KEY 가
   절대 들어가지 않는지 검증한다(비밀값은 자식이 .env 에서 직접 읽음).
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from datetime import datetime  # noqa: E402

from schedule_win import (  # noqa: E402
    TASK_PREFIX,
    build_run_command,
    build_run_exec,
    build_run_script,
    build_schtasks_change_args,
    build_schtasks_create_args,
    build_schtasks_create_xml_args,
    build_schtasks_delete_args,
    build_schtasks_query_args,
    build_task_xml,
    build_vbs_launcher,
    is_disabled_status,
    next_occurrence,
    parse_schtasks_list,
    script_filename,
    task_display_name,
    valid_time,
)


# --- valid_time ------------------------------------------------------------
def test_valid_time_accepts_hhmm():
    assert valid_time("02:00")
    assert valid_time("23:59")
    assert valid_time("9:05")          # 한 자리 시도 허용


def test_valid_time_rejects_bad():
    assert not valid_time("24:00")
    assert not valid_time("12:60")
    assert not valid_time("2")
    assert not valid_time("")
    assert not valid_time("ab:cd")


# --- task_display_name -----------------------------------------------------
def test_task_display_name_prefix_and_mode():
    n = task_display_name("요약")
    assert n.startswith(TASK_PREFIX)
    assert "요약" in n


def test_task_display_name_with_course_seq():
    n = task_display_name("이수", course="데이터베이스시스템", seq=13)
    assert n.startswith(TASK_PREFIX)
    assert "데이터베이스시스템" in n
    assert "13" in n


# --- script_filename (ASCII 안전 .bat 이름) --------------------------------
def test_script_filename_is_ascii_and_bat():
    fn = script_filename("이수", course="데이터베이스시스템", seq=13)
    assert fn.endswith(".bat")
    fn.encode("ascii")                 # 한글 없어야 함(예외 없으면 통과)


def test_script_filename_distinct_per_filter():
    a = script_filename("요약", course="이산수학", seq=1)
    b = script_filename("요약", course="이산수학", seq=2)
    c = script_filename("요약")
    assert a != b
    assert a != c


# --- build_run_script ------------------------------------------------------
def test_build_run_script_contains_python_and_main():
    s = build_run_script("C:/venv/python.exe", "C:/proj", "요약",
                         course="이산수학", seq=1)
    assert "python.exe" in s
    assert "main.py" in s
    assert "--mode" in s and "요약" in s
    assert "--course" in s and "이산수학" in s
    assert "--seq" in s and "1" in s


def test_build_run_script_routes_through_keep_awake():
    # 예약 실행은 main.py 를 직접 부르지 않고 keep_awake.py 를 거쳐야 한다
    # (실행 동안 PC 절전 억제 → 야간 무인 이수가 중간에 멈추지 않음).
    s = build_run_script("py", "C:/proj", "요약")
    assert "keep_awake.py" in s
    # keep_awake.py 가 main.py 보다 먼저 와야 한다(래퍼 → 대상 순서).
    assert s.index("keep_awake.py") < s.index("main.py")


def test_build_run_script_sets_utf8_and_cd():
    s = build_run_script("py", "C:/proj", "이수")
    assert "chcp 65001" in s           # 한글 인자 보존
    assert "cd /d" in s and "C:/proj" in s
    assert s.lstrip().startswith("@echo off")


def test_build_run_script_unwatched_and_no_filter():
    s = build_run_script("py", "C:/proj", "이수", unwatched=True)
    assert "--unwatched" in s
    assert "--course" not in s
    assert "--seq" not in s


def test_build_run_script_never_contains_secrets():
    s = build_run_script("py", "C:/proj", "전체", course="과목", seq=2)
    assert "KNOU_PW" not in s
    assert "GEMINI_API_KEY" not in s
    assert "--password" not in s


# --- build_vbs_launcher / build_run_command (창 없이 실행) ------------------
def test_build_vbs_launcher_runs_hidden():
    vbs = build_vbs_launcher(r"C:\proj\schedule_scripts\run_summary.bat")
    assert "WScript.Shell" in vbs
    assert ".Run" in vbs
    assert ", 0, False" in vbs               # 0 = 창 숨김(SW_HIDE)
    assert "run_summary.bat" in vbs


def test_build_run_command_uses_wscript_and_vbs():
    cmd = build_run_command(r"C:\proj\schedule_scripts\run_summary.vbs")
    assert "wscript" in cmd.lower()
    assert "//B" in cmd                       # 배치 모드(오류 팝업 억제)
    assert "run_summary.vbs" in cmd
    assert cmd.count('"') == 2                # 경로는 큰따옴표로 감쌈


def test_create_args_tr_is_verbatim():
    # /TR 은 받은 명령을 그대로 넣어야 한다(추가 따옴표 가공 없음)
    cmd = 'wscript.exe //B //Nologo "C:/proj/run_summary.vbs"'
    argv = build_schtasks_create_args("KNOU_요약", "02:00", cmd)
    tr_i = argv.index("/TR")
    assert argv[tr_i + 1] == cmd


# --- build_schtasks_change_args / is_disabled_status (사용/중지) ------------
def test_change_args_enable_disable():
    on = build_schtasks_change_args("KNOU_요약", True)
    assert on[0] == "schtasks"
    assert "/Change" in on
    assert "/TN" in on and "KNOU_요약" in on
    assert "/ENABLE" in on and "/DISABLE" not in on
    off = build_schtasks_change_args("KNOU_요약", False)
    assert "/DISABLE" in off and "/ENABLE" not in off


def test_is_disabled_status():
    assert is_disabled_status("사용 안 함") is True
    assert is_disabled_status("Disabled") is True
    assert is_disabled_status("준비") is False
    assert is_disabled_status("실행 중") is False
    assert is_disabled_status("") is False


# --- build_schtasks_create_args --------------------------------------------
def test_create_args_basic_daily():
    argv = build_schtasks_create_args("KNOU_요약", "02:00",
                                      "C:/proj/run_summary.bat")
    assert argv[0] == "schtasks"
    assert "/Create" in argv
    assert "/TN" in argv and "KNOU_요약" in argv
    assert "/SC" in argv and "DAILY" in argv
    assert "/ST" in argv and "02:00" in argv
    assert "/F" in argv
    tr_i = argv.index("/TR")
    assert "run_summary.bat" in argv[tr_i + 1]


def test_create_args_once_and_highest():
    argv = build_schtasks_create_args("KNOU_이수", "03:30",
                                      "C:/proj/run_watch.bat",
                                      freq="ONCE", highest=True)
    assert "ONCE" in argv
    assert "/RL" in argv and "HIGHEST" in argv


def test_create_args_never_contains_secrets():
    argv = build_schtasks_create_args("KNOU_요약", "02:00",
                                      "C:/proj/run_summary.bat")
    joined = " ".join(argv)
    assert "KNOU_PW" not in joined
    assert "GEMINI_API_KEY" not in joined


# --- next_occurrence (미래 시각 보장) --------------------------------------
def test_next_occurrence_today_when_future():
    now = datetime(2026, 6, 12, 1, 0, 0)        # 01:00, 목표 02:00 → 오늘
    assert next_occurrence("02:00", now=now) == "2026-06-12T02:00:00"


def test_next_occurrence_tomorrow_when_past():
    now = datetime(2026, 6, 12, 9, 30, 0)       # 09:30, 목표 02:00 → 내일
    assert next_occurrence("02:00", now=now) == "2026-06-13T02:00:00"


def test_next_occurrence_invalid_raises():
    import pytest
    with pytest.raises(ValueError):
        next_occurrence("nope")


# --- build_run_exec --------------------------------------------------------
def test_build_run_exec_splits_command_and_args():
    cmd, args = build_run_exec(r"C:\proj\schedule_scripts\run_watch.vbs")
    assert cmd == "wscript.exe"
    assert "//B" in args and "//Nologo" in args
    assert "run_watch.vbs" in args


# --- build_task_xml (안정성 설정) ------------------------------------------
def test_build_task_xml_daily_robust_defaults():
    xml = build_task_xml("wscript.exe", '//B "x.vbs"', "2026-06-13T02:00:00",
                         freq="DAILY")
    assert "<CalendarTrigger>" in xml and "<DaysInterval>1</DaysInterval>" in xml
    assert "<StartBoundary>2026-06-13T02:00:00</StartBoundary>" in xml
    # 놓친 예약 보충 + 배터리에서도 실행(=Disallow/Stop false)
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>" in xml
    assert "<WakeToRun>false</WakeToRun>" in xml
    assert "<Command>wscript.exe</Command>" in xml


def test_build_task_xml_once_uses_time_trigger():
    xml = build_task_xml("wscript.exe", "a", "2026-06-13T02:00:00", freq="ONCE")
    assert "<TimeTrigger>" in xml
    assert "<CalendarTrigger>" not in xml


def test_build_task_xml_highest_runlevel():
    xml = build_task_xml("c", "a", "2026-06-13T02:00:00", highest=True)
    assert "<RunLevel>HighestAvailable</RunLevel>" in xml
    low = build_task_xml("c", "a", "2026-06-13T02:00:00", highest=False)
    assert "<RunLevel>LeastPrivilege</RunLevel>" in low


def test_build_task_xml_escapes_arguments():
    xml = build_task_xml("wscript.exe", '//B "C:\\a & b\\x.vbs"',
                         "2026-06-13T02:00:00")
    assert "&amp;" in xml and "&quot;" in xml
    assert " & " not in xml             # 원시 & 가 남으면 XML 깨짐


def test_build_task_xml_no_secrets():
    xml = build_task_xml("wscript.exe", '//B "run.vbs"', "2026-06-13T02:00:00")
    assert "KNOU_PW" not in xml and "GEMINI_API_KEY" not in xml


def test_build_schtasks_create_xml_args():
    argv = build_schtasks_create_xml_args("KNOU_요약", r"C:\s\run.xml")
    assert argv[0] == "schtasks"
    assert "/Create" in argv and "/F" in argv
    assert "/TN" in argv and "KNOU_요약" in argv
    assert "/XML" in argv
    xi = argv.index("/XML")
    assert argv[xi + 1].endswith("run.xml")


# --- build_schtasks_delete_args / query ------------------------------------
def test_delete_args():
    argv = build_schtasks_delete_args("KNOU_요약")
    assert argv[0] == "schtasks"
    assert "/Delete" in argv
    assert "/TN" in argv and "KNOU_요약" in argv
    assert "/F" in argv


def test_query_args_csv_noheader():
    argv = build_schtasks_query_args()
    assert argv[0] == "schtasks"
    assert "/Query" in argv
    assert "/FO" in argv and "CSV" in argv
    assert "/NH" in argv


# --- parse_schtasks_list ---------------------------------------------------
SAMPLE_CSV = (
    '"\\KNOU_요약","2026-06-03 2:00:00","준비"\n'
    '"\\KNOU_이수_데이터베이스시스템_13강","2026-06-03 3:30:00","준비"\n'
    '"\\OtherTask","N/A","사용 안 함"\n'
    '"\\Microsoft\\Windows\\SomeJob","2026-06-03 1:00:00","준비"\n'
)


def test_parse_filters_our_prefix_only():
    rows = parse_schtasks_list(SAMPLE_CSV)
    assert len(rows) == 2
    names = [r["name"] for r in rows]
    assert all(n.startswith(TASK_PREFIX) for n in names)
    assert all(not n.startswith("\\") for n in names)   # 선행 백슬래시 제거


def test_parse_extracts_next_run_and_status():
    rows = parse_schtasks_list(SAMPLE_CSV)
    first = rows[0]
    assert first["next_run"] == "2026-06-03 2:00:00"
    assert first["status"] == "준비"


def test_parse_empty_or_info():
    assert parse_schtasks_list("") == []
    assert parse_schtasks_list("INFO: 예약된 작업이 없습니다.") == []
