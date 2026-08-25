"""절전 깨우기(wake timer) 단위테스트 — 예약이 자는 PC를 깨울 수 있는가.

작업 XML 의 <WakeToRun>true</WakeToRun> 만으로는 부족하고, Windows 전원 정책의
'절전 모드 해제 타이머 허용'(RTCWAKE)이 '사용'(1)이어야 실제로 깨어난다. 이
파일은 그 판정·안내 로직(순수)과 create_task 로의 전달을 검증한다.

⚠️ 전원 정책을 **바꾸는** 코드는 없어야 한다(시스템 설정 변경은 사용자 몫) —
   조회 argv 가 읽기 전용인지도 함께 검증한다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import schedule_win as sw  # noqa: E402
from schedule_win import (  # noqa: E402
    WAKE_IMPORTANT_ONLY,
    WAKE_OFF,
    WAKE_ON,
    build_powercfg_enable_commands,
    build_powercfg_query_args,
    build_task_xml,
    create_task,
    parse_wake_timer_setting,
    wake_timer_hint,
    wake_timers_allowed,
)

# 한국어 Windows 의 실제 powercfg 출력(이 PC에서 채취 — 둘 다 '사용 안 함')
KO_OUTPUT = """전원 구성표 GUID: 381b4222-f694-41f0-9685-ff5bb260df2e  (균형 조정)
  GUID 별칭: SCHEME_BALANCED
  하위 그룹 GUID: 238c9fa8-0aad-41ed-83f4-97be242c8f20  (절전)
    GUID 별칭: SUB_SLEEP
    전원 설정 GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (절전 모드 해제 타이머 허용)
      GUID 별칭: RTCWAKE
      가능한 설정 색인: 000
      가능한 설정 이름: 사용 안 함
      가능한 설정 색인: 001
      가능한 설정 이름: 사용
      가능한 설정 색인: 002
      가능한 설정 이름: 중요 절전 모드 해제 타이머만
    현재 AC 전원 설정 색인: 0x00000000
    현재 DC 전원 설정 색인: 0x00000000
"""

EN_OUTPUT = """Power Setting GUID: bd3b718a-0680-4d9d-8ab2-e1d2b4ac806d  (Allow wake timers)
      GUID Alias: RTCWAKE
      Possible Setting Index: 000
      Possible Setting Friendly Name: Disable
    Current AC Power Setting Index: 0x00000001
    Current DC Power Setting Index: 0x00000002
"""


# --- powercfg 출력 파싱 -----------------------------------------------------
def test_parse_korean_output():
    assert parse_wake_timer_setting(KO_OUTPUT) == {"ac": WAKE_OFF, "dc": WAKE_OFF}


def test_parse_english_output():
    # 로케일이 달라도 AC/DC 토큰과 16진 값만 보므로 그대로 읽힌다
    assert parse_wake_timer_setting(EN_OUTPUT) == {
        "ac": WAKE_ON, "dc": WAKE_IMPORTANT_ONLY}


def test_parse_ignores_guid_lines():
    # GUID 줄에는 0x 값이 없어 설정값으로 오인되면 안 된다
    got = parse_wake_timer_setting(KO_OUTPUT)
    assert got["ac"] is not None and got["ac"] < 3


def test_parse_empty_is_unknown():
    assert parse_wake_timer_setting("") == {"ac": None, "dc": None}
    assert parse_wake_timer_setting("아무 상관 없는 출력") == {"ac": None, "dc": None}


# --- 깨울 수 있는 상태인가(순수 판정) ---------------------------------------
def test_allowed_only_when_enabled():
    assert wake_timers_allowed({"ac": WAKE_ON, "dc": WAKE_ON}) is True
    assert wake_timers_allowed({"ac": WAKE_OFF, "dc": WAKE_ON}) is False


def test_important_only_is_not_enough():
    # '중요 절전 모드 해제 타이머만'(2)은 우리 예약 작업을 깨우지 못한다
    assert wake_timers_allowed({"ac": WAKE_IMPORTANT_ONLY, "dc": WAKE_ON}) is False


def test_battery_uses_dc_value():
    s = {"ac": WAKE_ON, "dc": WAKE_OFF}
    assert wake_timers_allowed(s, on_battery=False) is True
    assert wake_timers_allowed(s, on_battery=True) is False


def test_unknown_value_does_not_block():
    # 읽기 실패(None)로 기능을 잠그지 않는다 — 안내문만 따로 뜬다
    assert wake_timers_allowed({"ac": None, "dc": None}) is True


# --- 사용자 안내문 ----------------------------------------------------------
def test_hint_empty_when_all_enabled():
    assert wake_timer_hint({"ac": WAKE_ON, "dc": WAKE_ON}) == ""


def test_hint_names_the_bad_power_source():
    hint = wake_timer_hint({"ac": WAKE_OFF, "dc": WAKE_ON})
    assert "콘센트" in hint and "배터리" not in hint


def test_hint_includes_runnable_commands():
    hint = wake_timer_hint({"ac": WAKE_OFF, "dc": WAKE_OFF})
    for cmd in build_powercfg_enable_commands():
        assert cmd in hint


def test_hint_when_unreadable():
    hint = wake_timer_hint({"ac": None, "dc": None})
    assert hint and "읽지 못했" in hint


# --- powercfg argv ---------------------------------------------------------
def test_query_args_are_read_only():
    argv = build_powercfg_query_args()
    assert argv[:2] == ["powercfg", "/query"]
    joined = " ".join(argv).upper()
    # 조회에는 값을 바꾸는 스위치가 절대 섞이면 안 된다
    assert "SETACVALUEINDEX" not in joined and "SETDCVALUEINDEX" not in joined


def test_query_args_target_rtcwake_subgroup():
    joined = " ".join(build_powercfg_query_args()).upper()
    assert "238C9FA8-0AAD-41ED-83F4-97BE242C8F20" in joined   # SUB_SLEEP
    assert "BD3B718A-0680-4D9D-8AB2-E1D2B4AC806D" in joined   # RTCWAKE


def test_enable_commands_cover_ac_dc_and_apply():
    cmds = build_powercfg_enable_commands()
    joined = " ".join(cmds).upper()
    assert "SETACVALUEINDEX" in joined and "SETDCVALUEINDEX" in joined
    assert "SETACTIVE" in joined            # 바꾼 값을 현재 구성표에 적용


# --- 작업 XML --------------------------------------------------------------
def test_xml_wake_true():
    xml = build_task_xml("wscript.exe", "a", "2026-06-13T02:00:00", wake=True)
    assert "<WakeToRun>true</WakeToRun>" in xml


def test_xml_keeps_start_when_available_as_fallback():
    # 깨우기를 안 켜도 놓친 예약은 다음에 켤 때 실행돼야 한다
    xml = build_task_xml("wscript.exe", "a", "2026-06-13T02:00:00", wake=False)
    assert "<WakeToRun>false</WakeToRun>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml


# --- create_task 가 wake 를 XML 까지 전달하는가 -----------------------------
class _FakeProc:
    returncode = 0
    stdout = ""
    stderr = ""


def _capture_xml(monkeypatch, tmp_path, **kwargs):
    """create_task 를 schtasks 없이 돌리고 기록된 XML 을 돌려준다."""
    monkeypatch.setattr(sw, "_run_schtasks", lambda argv: _FakeProc())
    res = create_task("py.exe", str(tmp_path), "요약", "02:00",
                      scripts_dir=tmp_path, **kwargs)
    xml_files = list(Path(tmp_path).glob("*.xml"))
    assert len(xml_files) == 1
    return res, xml_files[0].read_text(encoding="utf-16")


def test_create_task_wake_reaches_xml(monkeypatch, tmp_path):
    res, xml = _capture_xml(monkeypatch, tmp_path, wake=True)
    assert res["wake"] is True
    assert "<WakeToRun>true</WakeToRun>" in xml


def test_create_task_defaults_to_no_wake(monkeypatch, tmp_path):
    res, xml = _capture_xml(monkeypatch, tmp_path)
    assert res["wake"] is False
    assert "<WakeToRun>false</WakeToRun>" in xml


def test_create_task_xml_still_has_no_secrets(monkeypatch, tmp_path):
    _res, xml = _capture_xml(monkeypatch, tmp_path, wake=True)
    assert "KNOU_PW" not in xml and "GEMINI_API_KEY" not in xml


# --- 등록됐다는 말을 곧이곧대로 믿지 않는다 ---------------------------------
# 실측 사건: 사용자가 예약을 걸었다고 알고 새벽 실행을 기다렸으나, 작업 스케줄러에
# KNOU_* 작업이 **한 건도** 없었다(시스템 전체 284건 중 0건). 등록 직후 목록으로
# 되짚어 확인해야 이런 조용한 실패를 잡는다.
def test_task_registered_true_when_listed(monkeypatch):
    monkeypatch.setattr(sw, "list_tasks",
                        lambda: [{"name": "KNOU_전체", "next_run": "", "status": ""}])
    assert sw.task_registered("KNOU_전체") is True


def test_task_registered_false_when_absent(monkeypatch):
    monkeypatch.setattr(sw, "list_tasks", lambda: [])
    assert sw.task_registered("KNOU_전체") is False


def test_task_registered_false_on_other_names(monkeypatch):
    monkeypatch.setattr(sw, "list_tasks",
                        lambda: [{"name": "KNOU_요약"}])
    assert sw.task_registered("KNOU_전체") is False


def test_task_registered_empty_name_is_false():
    assert sw.task_registered("") is False


def test_task_registered_survives_query_failure(monkeypatch):
    # 조회 자체가 실패했다면 '등록 안 됨'이라고 단정하지 않는다(오탐 방지)
    def _boom():
        raise OSError("schtasks 없음")

    monkeypatch.setattr(sw, "list_tasks", _boom)
    assert sw.task_registered("KNOU_전체") is True
