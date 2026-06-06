"""[runner] GUI ↔ 백엔드 다리 — 명령 빌더 · 로그 파서 · 작업 실행기.

GUI는 기존 `main.py`를 **하위 프로세스**로 구동하고 stdout 라인을 실시간으로 받아
진행바·상태·로그패널을 갱신한다. 백엔드는 한 줄도 고치지 않는다.

순수 로직(단위테스트):
  - build_command(...)        → main.py 실행 argv (비번·키 절대 미포함)
  - parse_progress_line(line) → 로그 한 줄을 이벤트 dict 로 해석
  - pct_for_stage(stage)      → 단계별 진행률(%) 추정
  - parse_lectures_snapshot   → lectures.json → [LectureRow]
  - note_path_for(cfg,...)    → 생성될 노트 경로(summarize.note_filename 재사용)
  - latest_log_path / read_log_tail → 예약이 남긴 최근 실행 로그 다시 보기

IO:
  - JobRunner                 → Popen + 워커 스레드(on_line/on_exit) + cancel()

⚠️ argv·로그·콜백 어디에도 비밀번호·GEMINI_API_KEY 평문이 흐르지 않는다
   (비밀값은 자식 프로세스가 .env 에서 직접 읽는다).
"""
from __future__ import annotations

import json
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

PROJECT_ROOT = Path(__file__).resolve().parent
MAIN_PY = PROJECT_ROOT / "main.py"
# main.py 의 setup_logger() 가 남기는 실행 로그 폴더(run_YYYYMMDD_HHMMSS.log).
LOG_DIR = PROJECT_ROOT / "logs"

# 콘솔 창 안 뜨게(Windows). 다른 OS/환경에선 0.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ---------------------------------------------------------------------------
# 명령 빌더 (순수)
# ---------------------------------------------------------------------------
def build_command(py, mode, course=None, seq=None, limit=None,
                  stages=None, state=None, unwatched: bool = False,
                  force: bool = False, main_py=MAIN_PY) -> list[str]:
    """`python -u main.py --mode … [필터]` argv 를 만든다.

    비밀번호·API 키는 인자로 넣지 않는다(자식이 .env 에서 읽음)."""
    argv = [str(py), "-u", str(main_py), "--mode", str(mode)]
    if course:
        argv += ["--course", str(course)]
    if seq is not None:
        argv += ["--seq", str(int(seq))]
    if unwatched:
        argv += ["--unwatched"]
    if force:
        argv += ["--force"]
    if limit is not None:
        argv += ["--limit", str(int(limit))]
    if stages:
        argv += ["--stages", *[str(s) for s in stages]]
    if state:
        argv += ["--state", str(state)]
    return argv


# ---------------------------------------------------------------------------
# 로그 파서 (순수)
# ---------------------------------------------------------------------------
# logging 포맷 "%(asctime)s %(levelname)s %(message)s" 의 앞부분(HH:MM:SS LEVEL )
_LOG_PREFIX = re.compile(
    r"^\d{2}:\d{2}:\d{2}\s+(?:INFO|WARNING|ERROR|DEBUG|CRITICAL)\s+")

_RE_LECTURE = re.compile(r"^──\s+(?P<course>.+?)\s+(?P<seq>\d+)강\s+'(?P<name>.*)'$")
_RE_DONE = re.compile(r"^✓\s+(?P<stage>\w+):\s+(?P<tag>.+)$")
_RE_SKIP = re.compile(r"^·\s+(?P<stage>\w+):")
_RE_FAIL = re.compile(r"^✗\s+(?P<stage>\w+)\s+(?:실패|예외):")
_RE_MATCH = re.compile(
    r"매칭\s+(?P<matched>\d+)\s+\+\s+전방채움\s+(?P<filled>\d+)\s+=\s+"
    r"(?P<plan>\d+)/(?P<total>\d+)개")
_RE_SUMMARY = re.compile(r"^===\s*요약\s*===")
# watch 진행 상태 줄: {'pos': 5.8, 'dur': 4972.2, 'rate': 2, 'paused': False, 'ended': False}
_RE_WATCH = re.compile(r"^\{.*?'pos':\s*([\d.]+).*?'dur':\s*([\d.]+)")


def parse_progress_line(line: str) -> dict | None:
    """로그/콘솔 한 줄 → 이벤트 dict (해석 불가면 None).

    인식 이벤트:
      {event:"lecture", course, seq, name}      강의 헤더
      {stage, status:"done"|"skip"}             단계 완료/건너뜀
      {stage, status:"error"}                   단계 실패/예외
      {event:"match", matched, filled, total}   슬라이드 매칭 결과
      {event:"summary"}                         최종 요약 줄
      {event:"watch", pos, dur, rate, paused, ended}  영상 이수 진행 상태
    """
    if not line:
        return None
    text = _LOG_PREFIX.sub("", line).strip()
    if not text:
        return None

    m = _RE_LECTURE.match(text)
    if m:
        return {"event": "lecture", "course": m["course"],
                "seq": int(m["seq"]), "name": m["name"]}

    m = _RE_DONE.match(text)
    if m:
        tag = m["tag"].strip()
        status = "skip" if "skip" in tag.lower() else "done"
        return {"stage": m["stage"], "status": status}

    m = _RE_SKIP.match(text)
    if m:
        return {"stage": m["stage"], "status": "skip"}

    m = _RE_FAIL.match(text)
    if m:
        return {"stage": m["stage"], "status": "error"}

    m = _RE_MATCH.search(text)
    if m:
        return {"event": "match", "matched": int(m["matched"]),
                "filled": int(m["filled"]), "total": int(m["total"])}

    if _RE_SUMMARY.match(text):
        ev: dict = {"event": "summary"}
        mp = re.search(r"'processed':\s*(\d+)", text)
        mf = re.search(r"'failed':\s*(\d+)", text)
        if mp:
            ev["processed"] = int(mp.group(1))
        if mf:
            ev["failed"] = int(mf.group(1))
        return ev

    m = _RE_WATCH.match(text)
    if m:
        ev = {"event": "watch", "pos": float(m.group(1)),
              "dur": float(m.group(2))}
        mr = re.search(r"'rate':\s*([\d.]+)", text)
        if mr:
            ev["rate"] = float(mr.group(1))
        mpz = re.search(r"'paused':\s*(True|False)", text)
        if mpz:
            ev["paused"] = (mpz.group(1) == "True")
        med = re.search(r"'ended':\s*(True|False)", text)
        if med:
            ev["ended"] = (med.group(1) == "True")
        return ev

    return None


# 단계 → 진행률(%) 추정. download 시작~capture 완료를 0~100 으로 본다.
_STAGE_PCT = {"download": 25, "summarize": 60, "capture": 90, "done": 100}


def pct_for_stage(stage: str) -> int | None:
    """단계 이름 → 대략적 진행률(%). 모르는 단계는 None."""
    return _STAGE_PCT.get(stage)


# ---------------------------------------------------------------------------
# 강의 목록 스냅샷 (순수)
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class LectureRow:
    """GUI 표시용 강의 한 줄(목록 스냅샷에서 평탄화)."""
    course: str
    seq: int
    name: str
    video_done: bool
    exam_done: bool
    watched_min: int = 0   # 이수 예상시간 계산용(없으면 0)
    total_min: int = 0


def parse_lectures_snapshot(data) -> list[LectureRow]:
    """lectures.json(문자열/바이트/dict) → [LectureRow]. 비면 []."""
    if isinstance(data, (str, bytes, bytearray)):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return []
    rows: list[LectureRow] = []
    for course in (data or {}).get("courses", []) or []:
        cname = course.get("name", "") or ""
        for lec in course.get("lectures", []) or []:
            rows.append(LectureRow(
                course=cname,
                seq=int(lec.get("seq", 0) or 0),
                name=lec.get("name", "") or "",
                video_done=bool(lec.get("video_done")),
                exam_done=bool(lec.get("exam_done")),
                watched_min=int(lec.get("watched_min", 0) or 0),
                total_min=int(lec.get("total_min", 0) or 0),
            ))
    return rows


def note_path_for(cfg, course: str, seq: int, name: str) -> Path:
    """생성될 예습 노트의 전체 경로(summarize.note_filename 규칙 그대로)."""
    from summarize import note_filename
    return Path(cfg.summary_dir) / note_filename(course, seq, name)


# ---------------------------------------------------------------------------
# 실행 로그 조회 — 예약(창 없이 실행)이 남긴 로그를 앱에서 다시 보기
# ---------------------------------------------------------------------------
def latest_log_path(logs_dir=LOG_DIR):
    """logs/ 에서 가장 최근 run_*.log 경로(없으면 None).

    파일명이 run_{YYYYMMDD_HHMMSS}.log 라 이름 내림차순 = 시간 내림차순이다.
    예약은 창 없이 백그라운드로 돌아 화면 로그가 없으므로, 이 파일이 사실상
    유일한 실행 흔적이다(앱 '실행' 탭에서 다시 본다).
    """
    d = Path(logs_dir)
    if not d.exists():
        return None
    logs = sorted(d.glob("run_*.log"), key=lambda p: p.name, reverse=True)
    return logs[0] if logs else None


def read_log_tail(path, max_lines: int = 500) -> list[str]:
    """로그 파일의 마지막 max_lines 줄(개행 제거). 없거나 못 읽으면 []."""
    p = Path(path) if path else None
    if not p or not p.exists():
        return []
    try:
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    return lines[-max_lines:] if max_lines and max_lines > 0 else lines


# ---------------------------------------------------------------------------
# Phase 3: 실제 서버 이수(진도 적립) 안전장치 (순수)
# ---------------------------------------------------------------------------
# 영상 이수 단계(watch)는 실제 방송대 서버에 시청(이수) 기록을 남기고, 영상 중
# 돌발퀴즈에 자동 응답한다 → 실제 본인 계정에 반영되므로 사전 동의가 필요하다.
# (형성평가/연습문제 답안 자동 제출은 현재 이수 경로에 포함되지 않는다.)
_IRREVERSIBLE_MODES = {"이수", "전체"}


def requires_confirm(mode: str) -> bool:
    """해당 모드가 실제 서버에 반영되는 이수 동작을 포함하면 True."""
    return mode in _IRREVERSIBLE_MODES


def confirm_message(mode: str) -> str:
    """이수 실행 전 보여줄 경고문(실제 서버 이수 반영을 명시)."""
    return (
        f"'{mode}' 모드는 실제 방송대 서버에 영상 시청(이수) 기록을 남기고, "
        "영상 중 돌발퀴즈에 자동 응답합니다.\n"
        "⚠️ 실제 본인 계정에 반영되는 동작이며 되돌리기 어렵습니다. "
        "본인 계정·예습 목적임을 이해하고 동의하는 경우에만 진행하세요.\n"
        "(형성평가/연습문제 답안 제출은 포함되지 않습니다.)"
    )


def estimate_watch_text(total_min, watched_min, speed) -> str:
    """남은 영상 시청에 걸릴 실제(벽시계) 시간을 사람이 읽는 문구로.

    watch.remaining_minutes / wall_clock_seconds / clamp_speed 재사용.
    """
    from watch import clamp_speed, remaining_minutes, wall_clock_seconds
    rem = remaining_minutes(watched_min, total_min)
    if rem <= 0:
        return "이미 이수 완료 — 추가 시청 불필요"
    sp = clamp_speed(speed)
    secs = wall_clock_seconds(rem, sp)
    mins = max(1, round(secs / 60))
    return f"약 {mins}분 예상 (남은 {rem}분 · {sp:g}배속)"


def job_status(code: int, had_error: bool = False, failed: int = 0,
               processed=None) -> str:
    """작업 종료 결과 → 상태 문자열: 'cancelled' | 'done' | 'error'.

    main.py 는 강의 실패에도 종료코드 0 이므로 had_error/failed/processed 로 보강.
    """
    if code == -1:
        return "cancelled"
    if code != 0 or had_error or failed:
        return "error"
    if processed is not None and processed < 1:
        return "error"
    return "done"


def format_elapsed(seconds) -> str:
    """경과 초 → 사람이 읽는 'M:SS' 또는 'H:MM:SS' (이수 진행 안내용)."""
    s = max(0, int(seconds))
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


def watch_sleep_warning() -> str:
    """영상 이수 중 PC 절전 방지 안내(이수가 길어 중간에 끊기면 안 됨)."""
    return ("⚠️ 이수 중에는 PC가 절전/잠자기되지 않도록 하세요"
            "(모니터 화면만 꺼지는 것은 괜찮습니다).")


# ---------------------------------------------------------------------------
# 작업 실행기 (IO) — subprocess + 워커 스레드
# ---------------------------------------------------------------------------
class JobRunner:
    """main.py 하위 프로세스를 구동하고 stdout 을 라인별 콜백으로 흘린다.

    on_line(str)  : 자식이 한 줄 출력할 때마다(개행 제거)
    on_exit(int)  : 종료 시 종료코드(취소로 끝났으면 -1)
    cancel()      : 자식 프로세스 종료(취소)
    running       : 실행 중 여부
    """

    def __init__(self, on_line: Callable[[str], None] | None = None,
                 on_exit: Callable[[int], None] | None = None):
        self.on_line = on_line or (lambda s: None)
        self.on_exit = on_exit or (lambda code: None)
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._cancelled = False

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def start(self, argv: list[str], cwd=None) -> None:
        """argv 로 자식 프로세스 시작 + 워커 스레드로 stdout 펌프."""
        if self.running:
            raise RuntimeError("이미 실행 중인 작업이 있습니다")
        self._cancelled = False
        self._proc = subprocess.Popen(
            argv,
            cwd=str(cwd) if cwd else str(PROJECT_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_NO_WINDOW,
        )
        self._thread = threading.Thread(target=self._pump, daemon=True)
        self._thread.start()

    def _pump(self) -> None:
        proc = self._proc
        try:
            if proc and proc.stdout:
                for line in proc.stdout:
                    self.on_line(line.rstrip("\r\n"))
        finally:
            code = proc.wait() if proc else -1
            self.on_exit(-1 if self._cancelled else code)

    def cancel(self) -> None:
        """실행 중 작업을 멈춘다(자식 프로세스 terminate)."""
        self._cancelled = True
        if self.running and self._proc is not None:
            try:
                self._proc.terminate()
            except Exception:
                pass
