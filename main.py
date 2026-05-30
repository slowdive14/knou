"""Phase 7 — 전과목 일괄 조율기.

브라우저 1회 기동 + 로그인 → 전과목 강의 순회 → 모드별 단계 실행
(watch=자동이수 / download=자료 / summarize=요약 / capture=비전검증 캡처) →
`state.json`에 단계별 완료 기록(재실행 시 done skip·중단 후 이어서) →
강의 단위 try/except 로 한 강의 실패해도 다음 강의 계속 → `logs/`에 실행 로그.

CLI:
   python main.py --mode 요약 --course 이산수학 --seq 1
   --mode  이수 | 요약 | 전체   (필수)
   --course 과목명(부분일치)     (선택)
   --seq   차시 번호            (선택)

순수 로직(단위테스트): stages_for_mode / lecture_key / stage_done /
lecture_done / mark_stage / select_lectures / pending_lectures.
오케스트레이션(브라우저·AI·ffmpeg)은 수동 스모크.

⚠️ 비밀번호·GEMINI_API_KEY 는 로그/콘솔에 절대 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parent
DEFAULT_STATE = PROJECT_DIR / "state.json"
LOG_DIR = PROJECT_DIR / "logs"

# 모드 → 실행 단계 순서
MODES: dict[str, list[str]] = {
    "이수": ["watch"],
    "요약": ["download", "summarize", "capture"],
    "전체": ["watch", "download", "summarize", "capture"],
}


# ---------------------------------------------------------------------------
# 순수 로직 (단위테스트 대상)
# ---------------------------------------------------------------------------
def stages_for_mode(mode: str) -> list[str]:
    """모드 이름 → 실행 단계 리스트(복사본). 모르는 모드면 ValueError."""
    if mode not in MODES:
        raise ValueError(f"알 수 없는 모드: {mode!r} (가능: {list(MODES)})")
    return list(MODES[mode])


def _seq_of(lec) -> int:
    """Lecture 객체/딕셔너리 양쪽에서 차시 번호 추출."""
    if isinstance(lec, dict):
        return int(lec["seq"])
    return int(getattr(lec, "seq"))


def _video_done_of(lec) -> bool:
    """Lecture 객체/딕셔너리에서 영상 시청완료 여부 추출(없으면 False=미시청)."""
    if isinstance(lec, dict):
        return bool(lec.get("video_done"))
    return bool(getattr(lec, "video_done", False))


def filter_unwatched(pairs) -> list:
    """(과목명, lec) 쌍 중 영상 미시청(video_done=False)인 것만.

    video_done 키/속성이 없으면 보수적으로 '미시청'으로 보고 포함한다
    (요약/예습 대상에서 빠지지 않게)."""
    return [(c, l) for c, l in pairs if not _video_done_of(l)]


def lecture_key(course: str, seq) -> str:
    """상태 저장용 안정 키: '{과목}|{seq}'."""
    return f"{course}|{int(seq)}"


def stage_done(state: dict, key: str, stage: str) -> bool:
    """state[key][stage].ok 가 참이면 True."""
    rec = (state.get(key, {}) or {}).get(stage) or {}
    return bool(rec.get("ok"))


def lecture_done(state: dict, key: str, stages) -> bool:
    """해당 강의의 요청 단계가 모두 완료면 True(단계가 비면 False)."""
    return bool(stages) and all(stage_done(state, key, s) for s in stages)


def mark_stage(state: dict, key: str, stage: str, ok: bool = True,
               error: str | None = None) -> dict:
    """state[key][stage] 기록(성공/실패+에러+시각). 다른 단계는 보존."""
    state.setdefault(key, {})[stage] = {
        "ok": bool(ok), "error": error,
        "at": datetime.now().isoformat(timespec="seconds"),
    }
    return state


def select_lectures(pairs, course: str | None = None, seq=None) -> list:
    """(과목명, lec) 쌍 목록을 과목(부분일치)·차시 필터로 추린다."""
    out = []
    for cname, lec in pairs:
        if course and course not in cname:
            continue
        if seq is not None and _seq_of(lec) != int(seq):
            continue
        out.append((cname, lec))
    return out


def pending_lectures(state: dict, pairs, stages) -> list:
    """요청 단계 기준 아직 완료되지 않은 강의만 선별."""
    return [(c, l) for c, l in pairs
            if not lecture_done(state, lecture_key(c, _seq_of(l)), stages)]


# ---------------------------------------------------------------------------
# 상태 / 로그 (IO)
# ---------------------------------------------------------------------------
def load_state(path=DEFAULT_STATE) -> dict:
    """state.json 로드(없거나 깨졌으면 빈 dict)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (ValueError, OSError):
        return {}


def save_state(path, state: dict) -> None:
    """state.json 저장(원자적: 임시파일→교체)."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    tmp.replace(p)


def setup_logger(name: str = "knou") -> logging.Logger:
    """콘솔 + logs/run_{ts}.log 동시 출력 로거. 비밀번호·키는 절대 기록 안 함."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s",
                            "%H:%M:%S")
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    fh = logging.FileHandler(LOG_DIR / f"run_{ts}.log", encoding="utf-8")
    fh.setFormatter(fmt)
    sh = logging.StreamHandler()
    sh.setFormatter(fmt)
    logger.addHandler(fh)
    logger.addHandler(sh)
    return logger


# ---------------------------------------------------------------------------
# 단계 실행기 (IO) — 각 단계 함수는 {"ok":bool,"skipped"?:bool,"error"?:str} 반환
# ---------------------------------------------------------------------------
class _Ctx:
    """단계 실행에 필요한 공유 자원(브라우저/AI/경로/로거)."""

    def __init__(self, cfg, ctx, page, client, logger):
        self.cfg = cfg
        self.ctx = ctx
        self.page = page
        self.client = client
        self.logger = logger
        self.downloads_dir = Path(cfg.downloads_dir)
        self.summary_dir = Path(cfg.summary_dir)
        self.posts_cache: dict[str, list] = {}  # 과목별 강의자료실 글목록 재사용


def _stage_watch(c: _Ctx, course: str, lec) -> dict:
    from watch import watch_lecture
    res = watch_lecture(c.page, lec, c.cfg,
                        on_progress=lambda m: c.logger.info("    %s", m))
    return {"ok": True, "detail": res}


def _stage_download(c: _Ctx, course: str, lec) -> dict:
    from download import download_lecture
    res = download_lecture(
        c.ctx, c.page, lec, course,
        posts=c.posts_cache.get(course), dest_dir=c.downloads_dir,
        on_event=lambda m: c.logger.info("    %s", m))
    c.posts_cache[course] = res.get("posts")
    mp3 = res.get("mp3") or {}
    if not mp3.get("ok"):
        return {"ok": False, "error": "MP3 다운로드 실패"}
    return {"ok": True, "detail": {"pdf": bool((res.get("pdf") or {}).get("ok"))}}


def _stage_summarize(c: _Ctx, course: str, lec) -> dict:
    from capture import probe_duration
    from download import build_filename
    from summarize import (needs_summary, note_filename, save_summary,
                           summarize_lecture)
    note = c.summary_dir / note_filename(course, lec.seq, lec.name)
    if not needs_summary(note):
        return {"ok": True, "skipped": True}
    mp3 = c.downloads_dir / build_filename(course, lec.seq, "mp3")
    pdf = c.downloads_dir / build_filename(course, lec.seq, "pdf")
    md = summarize_lecture(
        c.client, course, lec.seq, lec.name,
        mp3_path=mp3 if mp3.exists() else None,
        pdf_path=pdf if pdf.exists() else None,
        on_event=lambda m: c.logger.info("    %s", m))
    if not md:
        return {"ok": False, "error": "빈 요약 응답"}
    # MP3 길이로 Gemini 'MM:SS:00' 오형식 마커를 저장 전에 교정
    dur = probe_duration(str(mp3)) if mp3.exists() else None
    save_summary(md, c.summary_dir, course, lec.seq, lec.name, duration=dur)
    return {"ok": True}


def _stage_capture(c: _Ctx, course: str, lec) -> dict:
    from capture import capture_lecture_verified
    from download import build_filename
    from summarize import note_filename
    note = c.summary_dir / note_filename(course, lec.seq, lec.name)
    mp3 = c.downloads_dir / build_filename(course, lec.seq, "mp3")
    if not note.exists():
        return {"ok": False, "error": "요약 노트 없음(먼저 summarize)"}
    if not mp3.exists():
        return {"ok": False, "error": "MP3 없음(먼저 download)"}
    res = capture_lecture_verified(
        c.page, lec, course, lec.seq, lec.name,
        mp3_path=mp3, note_path=note, client=c.client,
        on_event=lambda m: c.logger.info("    %s", m))
    return {"ok": True, "detail": res}


STAGE_FUNCS = {
    "watch": _stage_watch,
    "download": _stage_download,
    "summarize": _stage_summarize,
    "capture": _stage_capture,
}


def _needs_gemini(stages) -> bool:
    return any(s in stages for s in ("summarize", "capture"))


# ---------------------------------------------------------------------------
# 오케스트레이션 (IO)
# ---------------------------------------------------------------------------
def run(mode: str, course: str | None = None, seq=None,
        state_path=DEFAULT_STATE, cfg=None, unwatched: bool = False,
        limit: int | None = None) -> dict:
    """전과목 순회 오케스트레이션. 반환: 실행 요약 dict.

    unwatched=True 면 영상 미시청 강의만 / limit 이 있으면 처리 대상을 N개로 제한.
    """
    from google import genai
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from discover import fetch_lectures, list_courses
    from recon import launch_context

    stages = stages_for_mode(mode)
    cfg = cfg or load_config()
    logger = setup_logger()
    state = load_state(state_path)

    logger.info("▶ 모드=%s 단계=%s 필터(course=%s, seq=%s, unwatched=%s, limit=%s)",
                mode, stages, course, seq, unwatched, limit)

    processed = skipped_lec = failed_lec = 0
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        client = genai.Client(api_key=cfg.gemini_api_key) \
            if _needs_gemini(stages) else None
        c = _Ctx(cfg, ctx, page, client, logger)

        # 전과목 강의 수집
        pairs = []
        for course_obj in list_courses(page):
            try:
                for lec in fetch_lectures(page, course_obj):
                    pairs.append((course_obj.name, lec))
            except Exception as e:  # noqa: BLE001
                logger.warning("과목 '%s' 강의목록 조회 실패: %s",
                               course_obj.name, str(e)[:120])
        pairs = select_lectures(pairs, course=course, seq=seq)
        if unwatched:
            before = len(pairs)
            pairs = filter_unwatched(pairs)
            logger.info("미시청 필터: %d개 중 미시청 %d개", before, len(pairs))
        todo_all = pending_lectures(state, pairs, stages)
        todo = todo_all if limit is None else todo_all[:limit]
        deferred = len(todo_all) - len(todo)
        logger.info("대상 강의: 전체 %d개 중 처리 %d개 "
                    "(완료 skip %d개%s)",
                    len(pairs), len(todo), len(pairs) - len(todo_all),
                    f", limit 보류 {deferred}개" if deferred else "")

        try:
            for cname, lec in todo:
                key = lecture_key(cname, lec.seq)
                logger.info("── %s %d강 '%s'", cname, lec.seq, lec.name)
                lec_failed = False
                for stage in stages:
                    if stage_done(state, key, stage):
                        logger.info("  · %s: 이미 완료 skip", stage)
                        continue
                    try:
                        r = STAGE_FUNCS[stage](c, cname, lec)
                    except Exception as e:  # noqa: BLE001 - 강의단위 격리
                        mark_stage(state, key, stage, ok=False,
                                   error=str(e)[:200])
                        save_state(state_path, state)
                        logger.error("  ✗ %s 예외: %s", stage, str(e)[:160])
                        lec_failed = True
                        break
                    mark_stage(state, key, stage, ok=r["ok"],
                               error=r.get("error"))
                    save_state(state_path, state)
                    if r["ok"]:
                        tag = "skip" if r.get("skipped") else "완료"
                        logger.info("  ✓ %s: %s", stage, tag)
                    else:
                        logger.warning("  ✗ %s 실패: %s", stage,
                                       r.get("error"))
                        lec_failed = True
                        break
                if lec_failed:
                    failed_lec += 1
                else:
                    processed += 1
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    skipped_lec = len(pairs) - len(todo_all)
    deferred = len(todo_all) - len(todo)
    logger.info("■ 완료: 처리 %d / 실패 %d / 사전skip %d / limit보류 %d",
                processed, failed_lec, skipped_lec, deferred)
    return {"mode": mode, "total": len(pairs), "processed": processed,
            "failed": failed_lec, "skipped": skipped_lec, "deferred": deferred}


def parse_args(argv=None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(
        description="방송대 LMS 자동화 — 전과목 조율(이수/요약/캡처)")
    ap.add_argument("--mode", required=True, choices=list(MODES),
                    help="이수 | 요약 | 전체")
    ap.add_argument("--course", default=None, help="과목명 부분일치 필터")
    ap.add_argument("--seq", type=int, default=None, help="차시 번호 필터")
    ap.add_argument("--unwatched", action="store_true",
                    help="영상 미시청(video_done=False) 강의만 처리")
    ap.add_argument("--limit", type=int, default=None,
                    help="처리할 강의 최대 개수(예: 1 → 한 강의만)")
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help="상태 파일 경로(기본 state.json)")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    summary = run(args.mode, course=args.course, seq=args.seq,
                  state_path=args.state, unwatched=args.unwatched,
                  limit=args.limit)
    print(f"\n=== 요약 === {summary}", flush=True)


if __name__ == "__main__":
    main()
