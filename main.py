"""Phase 7 — 전과목 일괄 조율기.

브라우저 1회 기동 + 로그인 → 전과목 강의 순회 → 모드별 단계 실행
(watch=자동이수 / download=자료 / summarize=요약 / capture=슬라이드 덱 매칭) →
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
# watch=영상 이수(+돌발퀴즈), exam=형성평가(연습문제) 자동 풀이.
MODES: dict[str, list[str]] = {
    "이수": ["watch", "exam"],
    "요약": ["download", "summarize", "capture"],
    "전체": ["watch", "exam", "download", "summarize", "capture"],
}

# 단계 사이의 **진짜** 의존관계 — 앞 단계의 산출물이 있어야 돌아가는 것만 적는다.
# 한 단계가 실패해도 여기에 걸리지 않는 단계는 계속 실행한다(실측 사례: 덱 추출이
# 실패했다고 형성평가·요약까지 통째로 날아가면 안 된다).
STAGE_DEPS: dict[str, list[str]] = {
    "summarize": ["download"],    # 요약은 download 가 받은 mp3/pdf 를 읽는다
    "capture": ["summarize"],     # 덱 매칭은 요약 노트에 마커·이미지를 심는다
    "extra": ["summarize"],       # 두 번째 영상 노트도 요약 파이프라인을 탄다
}


# ---------------------------------------------------------------------------
# 순수 로직 (단위테스트 대상)
# ---------------------------------------------------------------------------
def stages_for_mode(mode: str) -> list[str]:
    """모드 이름 → 실행 단계 리스트(복사본). 모르는 모드면 ValueError."""
    if mode not in MODES:
        raise ValueError(f"알 수 없는 모드: {mode!r} (가능: {list(MODES)})")
    return list(MODES[mode])


def first_missing_stage(state: dict, key: str, stages) -> int:
    """이 강의에서 **처음으로 안 끝난 단계**의 자리(0-based). 다 끝났으면 len.

    작을수록 파이프라인 앞쪽이 비어 있다 = 더 근본적인 게 없다는 뜻
    (예: 노트(summarize)가 없는 강의 < 이미지(capture)만 없는 강의).
    """
    for i, s in enumerate(stages or ()):
        if not stage_done(state, key, s):
            return i
    return len(stages or ())


def order_todo(state: dict, pairs, stages) -> list:
    """처리 순서를 정한다 — **이어서 할 강의 먼저, 그 중에서도 앞 단계가 빈 것부터**.

    실측 불편: 실패 기록이 있는 2강(이미지만 없음)과 7강(노트부터 없음)이 함께
    대기하는데 차시 번호 순이라 2강이 먼저 잡혔다. 한 번에 1강만 도는 설정에서는
    정작 급한 7강의 노트가 계속 밀린다.

    규칙(결정적이라 예측 가능하다):
      1) 실패 기록이 있는 강의(=이어서 하기)를 새 강의보다 먼저
      2) 그 안에서는 **앞 단계가 비어 있는 것부터**(노트 없음 < 이미지만 없음)
      3) 같으면 차시 순
    새로 시작하는 과목은 1)에 걸리는 강의가 없어 예전과 똑같이 차시 순이다.
    """
    def sort_key(item):
        cname, lec = item
        key = lecture_key(cname, _seq_of(lec))
        resume = has_failed_stage(state, key, stages)
        return (0 if resume else 1,
                first_missing_stage(state, key, stages) if resume else 0,
                _seq_of(lec))

    return sorted(pairs, key=sort_key)


def dependent_stages(failed: str, stages, deps=None) -> set[str]:
    """`failed` 단계가 실패했을 때 **실행하면 안 되는** 후속 단계들(전이 포함).

    산출물이 없어 어차피 못 도는 단계만 골라낸다. 나머지 단계는 실패와 무관하게
    계속 실행한다 — 예: capture(덱 추출) 실패는 exam·download·summarize 를
    막지 않고, exam 실패는 노트 생성을 막지 않는다.
    """
    deps = STAGE_DEPS if deps is None else deps
    blocked: set[str] = set()
    changed = True
    while changed:                     # 전이 의존(요약→덱→…)까지 닫아둔다
        changed = False
        for stage in stages:
            if stage in blocked:
                continue
            need = deps.get(stage) or []
            if failed in need or blocked.intersection(need):
                blocked.add(stage)
                changed = True
    return blocked


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


def has_failed_stage(state: dict, key: str, stages) -> bool:
    """요청 단계 중 **실패로 기록된** 단계가 하나라도 있으면 True.

    '미이수만' 필터가 이어서 하기를 막지 않게 하려고 쓴다(아래 filter_unwatched).
    """
    rec = state.get(key) or {}
    for s in stages or ():
        r = rec.get(s)
        if isinstance(r, dict) and r.get("ok") is False:
            return True
    return False


def filter_unwatched(pairs, state=None, stages=None) -> list:
    """(과목명, lec) 쌍 중 영상 미시청(video_done=False)인 것만.

    video_done 키/속성이 없으면 보수적으로 '미시청'으로 보고 포함한다
    (요약/예습 대상에서 빠지지 않게).

    ⚠️ 단, **실패 기록이 있는 강의는 이미 이수했더라도 남긴다**. 영상 이수는
    성공했는데 요약이 실패한 강의는 LMS 상 video_done=True 가 되어 이 필터에
    걸러지고, 그러면 실패한 단계를 영영 이어서 할 수 없다(실측: 7강 summarize
    가 429 로 실패했는데 다음 실행에서 대상에서 빠졌다).
    """
    out = []
    for c, l in pairs:
        if not _video_done_of(l):
            out.append((c, l))
            continue
        if state is not None and has_failed_stage(
                state, lecture_key(c, _seq_of(l)), stages):
            out.append((c, l))          # 이어서 할 게 남은 강의는 통과
    return out


def lecture_key(course: str, seq) -> str:
    """상태 저장용 안정 키: '{과목}|{seq}'."""
    return f"{course}|{int(seq)}"


def stage_done(state: dict, key: str, stage: str) -> bool:
    """state[key][stage].ok 가 참이면 True."""
    rec = (state.get(key, {}) or {}).get(stage) or {}
    return bool(rec.get("ok"))


def should_run_stage(state: dict, key: str, stage: str,
                     force: bool = False) -> bool:
    """이 단계를 실행해야 하면 True.

    기본은 '아직 완료 안 된 단계'만 실행한다. force=True(다시 만들기/덮어쓰기)면
    완료 기록을 무시하고 무조건 실행한다.
    """
    return bool(force) or not stage_done(state, key, stage)


def lecture_done(state: dict, key: str, stages) -> bool:
    """해당 강의의 요청 단계가 모두 완료면 True(단계가 비면 False)."""
    return bool(stages) and all(stage_done(state, key, s) for s in stages)


def mark_stage(state: dict, key: str, stage: str, ok: bool = True,
               error: str | None = None, skipped: bool = False) -> dict:
    """state[key][stage] 기록(성공/실패+에러+시각). 다른 단계는 보존.

    skipped=True 는 '할 게 없어서 건너뜀'이다(예: 그 차시에 형성평가가 아예
    없음). 실패와도, 실제로 처리한 것과도 다르므로 따로 남긴다 — 현황 화면에서
    '돌렸는데 서버는 미완료'와 '애초에 없음'을 구분해 보여주기 위함.
    """
    state.setdefault(key, {})[stage] = {
        "ok": bool(ok), "error": error, "skipped": bool(skipped),
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


def pending_lectures(state: dict, pairs, stages, force: bool = False) -> list:
    """요청 단계 기준 아직 완료되지 않은 강의만 선별.

    force=True(다시 만들기/덮어쓰기)면 완료 여부와 무관하게 전부 포함한다.
    """
    if force:
        return list(pairs)
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

    def _capture_quiz(popup):
        # 돌발퀴즈 복습 캡처(부수효과·예외 격리) — 정답·해설 노출 직후 호출됨.
        from quiz_capture import scan_quiz
        from quiz_page import persist_questions
        qs = scan_quiz(popup, source="돌발퀴즈")
        if persist_questions(c.cfg, course, lec.seq, lec.name, qs):
            c.logger.info("    퀴즈 캡처: 돌발퀴즈 %d문항 저장", len(qs))

    res = watch_lecture(c.page, lec, c.cfg,
                        on_progress=lambda m: c.logger.info("    %s", m),
                        on_quiz=_capture_quiz)
    return {"ok": True, "detail": res}


def _stage_exam(c: _Ctx, course: str, lec) -> dict:
    """형성평가(연습문제) 자동 풀이 — 정오답 무관으로 답안 등록.

    ⚠️ 실제 방송대 서버에 답안이 제출되는 되돌릴 수 없는 동작이다(완료기준상 정오답
    무관). 플레이어를 열어 `.exam-content-box` 의 문항을 모두 응답 등록하고 닫는다.
    연습문제가 없는 차시는 skip(ok)으로 처리한다.
    """
    from exercise import (EXAM_WAIT_MS, _exam_frame, solve_exercises,
                          wait_for_exam_frame)
    from watch import open_player

    popup = open_player(c.page, lec)
    dialog_msgs: list[str] = []

    def _on_dialog(d):
        try:
            dialog_msgs.append(d.message)
        finally:
            try:
                d.accept()
            except Exception:
                pass

    try:
        popup.on("dialog", _on_dialog)
    except Exception:
        pass
    try:
        # 연습문제 박스가 뜰 때까지 기다린다(늦게 붙는 차시가 있어 폴링).
        if wait_for_exam_frame(popup) is None:
            c.logger.info("    형성평가 없음(skip · %d초 대기 후)",
                          EXAM_WAIT_MS // 1000)
            return {"ok": True, "skipped": True, "detail": "연습문제 없음"}
        res = solve_exercises(popup, dialog_msgs=dialog_msgs,
                              on_event=lambda m: c.logger.info("    %s", m))
        c.logger.info("    형성평가: %s (%s/%s 응답)", res.get("status"),
                      res.get("answered"), res.get("total"))
        # 퀴즈 복습용 캡처(부수효과·예외 격리) — 풀이 후라 정답·해설이 드러나 있다.
        try:
            from quiz_capture import scan_quiz
            from quiz_page import persist_questions
            fr = _exam_frame(popup)
            qs = scan_quiz(fr, source="형성평가") if fr is not None else []
            if persist_questions(c.cfg, course, lec.seq, lec.name, qs):
                c.logger.info("    퀴즈 캡처: 형성평가 %d문항 저장", len(qs))
        except Exception as e:  # noqa: BLE001 - 캡처 실패가 이수를 막지 않게
            c.logger.info("    퀴즈 캡처 건너뜀: %s", str(e)[:80])
        if res.get("status") in ("ok", "no_questions", "no_exam_box"):
            return {"ok": True, "detail": res}
        return {"ok": False, "error": f"형성평가 status={res.get('status')}"}
    finally:
        try:
            popup.close()
        except Exception:
            pass


def _mp3_from_video(c: _Ctx, course: str, lec) -> bool:
    """LMS 에 MP3 링크가 없는 과목: **영상에서 오디오만** 뽑아 MP3 를 만든다.

    'AI네이티브가되기위한기초소양' 처럼 strVidoAudoUrl 이 비어 있는 과목이 있다
    (영상·강의록은 멀쩡히 있다). 두 번째 영상 노트에서 쓰던 HLS→ffmpeg 경로를
    그대로 재사용해 같은 이름의 MP3 를 만들어 두면, 이후 요약 단계는 평소와
    똑같이 돈다(노트 품질도 다른 과목과 같아진다).

    ⚠️ hlsUrl 에는 시한부 JWT 가 들어 있어 로그에 남기지 않는다(길이만 기록).
    """
    from capture import probe_duration, wait_for_clips
    from download import build_filename
    from extra_video import extract_audio
    from watch import open_player

    out = c.downloads_dir / build_filename(course, lec.seq, "mp3")
    if out.exists() and out.stat().st_size > 0:
        return True
    popup = open_player(c.page, lec)
    try:
        clips = wait_for_clips(popup)
        for cl in clips:
            if cl.get("duration") is None:
                cl["duration"] = probe_duration(cl.get("hlsUrl") or "")
        valid = [cl for cl in clips
                 if isinstance(cl.get("duration"), (int, float))
                 and cl["duration"] > 0]
        if not valid:
            c.logger.info("    영상 클립도 없어 MP3 를 만들 수 없음")
            return False
        main = max(valid, key=lambda x: x["duration"])
        c.logger.info("    MP3 링크 없음 → 영상에서 오디오 추출(%.0f분, 몇 분 걸림)",
                      main["duration"] / 60)
        r = extract_audio(main.get("hlsUrl") or "", out)
        if r.get("ok"):
            c.logger.info("    오디오 추출 완료: %s", out.name)
            return True
        c.logger.warning("    오디오 추출 실패: %s", (r.get("error") or "")[:120])
        return False
    finally:
        try:
            popup.close()
        except Exception:
            pass


def _stage_download(c: _Ctx, course: str, lec) -> dict:
    from download import download_lecture
    res = download_lecture(
        c.ctx, c.page, lec, course,
        posts=c.posts_cache.get(course), dest_dir=c.downloads_dir,
        on_event=lambda m: c.logger.info("    %s", m))
    c.posts_cache[course] = res.get("posts")
    mp3 = res.get("mp3") or {}
    pdf_ok = bool((res.get("pdf") or {}).get("ok"))
    if mp3.get("ok"):
        return {"ok": True, "detail": {"pdf": pdf_ok}}
    # ① MP3 링크가 없거나 받기 실패 → 영상에서 오디오를 직접 뽑아 본다
    if _mp3_from_video(c, course, lec):
        return {"ok": True, "detail": {"pdf": pdf_ok, "mp3_from_video": True}}
    # ② 그것도 안 되면 강의록만으로 요약한다 — 노트를 통째로 포기하지 않는다
    if pdf_ok:
        c.logger.info("    음성을 못 구함 → 강의록(PDF)만으로 요약 진행")
        return {"ok": True, "detail": {"pdf": True, "audio": False},
                "audio": False}
    return {"ok": False, "error": "강의 음성·강의록을 모두 구하지 못함"}


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
    """슬라이드 덱 매칭 캡처(deck_match). 영상→덱→개념매칭→노트 마커/이미지 보정.

    옛 비전윈도우 경로(capture.capture_lecture_verified)는 보존되어 있으나
    더 정확한 콘텐츠 매칭을 위해 이 경로로 대체했다(롤백은 이 함수만 되돌림).
    """
    from deck_match import deck_capture_lecture
    from summarize import note_filename
    note = c.summary_dir / note_filename(course, lec.seq, lec.name)
    if not note.exists():
        return {"ok": False, "error": "요약 노트 없음(먼저 summarize)"}
    clips: list = []          # 이 차시의 전체 클립(플레이어를 이미 여는 김에)
    res = deck_capture_lecture(
        c.page, lec, course, lec.seq, lec.name,
        cfg=c.cfg, client=c.client, note_path=note,
        on_event=lambda m: c.logger.info("    %s", m), out_clips=clips)
    # 두 번째 영상 탐지 결과를 함께 돌려준다(실행 후 GUI 가 물어볼 근거).
    # hlsUrl(토큰)은 담지 않는다 — clip_brief 로 idx/제목/길이만.
    try:
        from extra_video import clip_brief, pick_extra_clips
        extras = pick_extra_clips(clips)
        res["extra_videos"] = [clip_brief(x) for x in extras]
        if extras:
            c.logger.info("    두 번째 영상 %d개 감지(예습노트 별도 생성 가능)",
                          len(extras))
    except Exception as e:  # noqa: BLE001 - 탐지 실패가 캡처를 막지 않게
        c.logger.info("    두 번째 영상 탐지 건너뜀: %s", str(e)[:80])
    return res


def _stage_extra(c: _Ctx, course: str, lec) -> dict:
    """두 번째(이후) 영상 예습노트 — HLS 오디오 추출 → 요약 → 별도 노트 저장.

    기본 모드에는 들어있지 않다. 실행이 끝난 뒤 사용자가 '만들기'를 고르면
    `--stages extra` 로 이 단계만 따로 돈다(app/views/run_view.py).
    """
    from extra_video import make_extra_notes
    return make_extra_notes(
        c.page, lec, course, client=c.client,
        downloads_dir=c.downloads_dir, out_dir=c.summary_dir,
        on_event=lambda m: c.logger.info("    %s", m))


STAGE_FUNCS = {
    "watch": _stage_watch,
    "extra": _stage_extra,
    "exam": _stage_exam,
    "download": _stage_download,
    "summarize": _stage_summarize,
    "capture": _stage_capture,
}


def _needs_gemini(stages) -> bool:
    return any(s in stages for s in ("summarize", "capture", "extra"))


# ---------------------------------------------------------------------------
# 오케스트레이션 (IO)
# ---------------------------------------------------------------------------
def run(mode: str, course: str | None = None, seq=None,
        state_path=DEFAULT_STATE, cfg=None, unwatched: bool = False,
        limit: int | None = None, only_stages: list[str] | None = None,
        force: bool = False) -> dict:
    """전과목 순회 오케스트레이션. 반환: 실행 요약 dict.

    unwatched=True 면 영상 미시청 강의만 / limit 이 있으면 처리 대상을 N개로 제한.
    only_stages 가 있으면 모드 단계 중 그 단계만 실행(예: ["capture"]).
    force=True(다시 만들기/덮어쓰기)면 이미 완료된 차시·단계도 무시하고 다시 처리한다.
    """
    from google import genai
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from discover import fetch_lectures, list_courses
    from recon import launch_context

    stages = stages_for_mode(mode)
    if only_stages:
        bad = [s for s in only_stages if s not in STAGE_FUNCS]
        if bad:
            raise ValueError(f"알 수 없는 단계: {bad} "
                             f"(가능: {list(STAGE_FUNCS)})")
        stages = [s for s in stages if s in only_stages] or list(only_stages)
    cfg = cfg or load_config()
    logger = setup_logger()
    state = load_state(state_path)

    logger.info("▶ 모드=%s 단계=%s 필터(course=%s, seq=%s, unwatched=%s, "
                "limit=%s, force=%s)",
                mode, stages, course, seq, unwatched, limit, force)

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
            # 실패 기록이 있는 강의는 이미 이수했어도 남긴다(이어서 하기)
            pairs = filter_unwatched(pairs, state=state, stages=stages)
            resume = sum(1 for c, l in pairs if _video_done_of(l))
            logger.info("미시청 필터: %d개 중 대상 %d개%s", before, len(pairs),
                        f" (이수했지만 이어서 할 강의 {resume}개 포함)"
                        if resume else "")
        todo_all = pending_lectures(state, pairs, stages, force=force)
        # 이어서 할 강의를 앞으로(노트 없는 것 → 이미지만 없는 것 → 새 강의)
        todo_all = order_todo(state, todo_all, stages)
        todo = todo_all if limit is None else todo_all[:limit]
        deferred = len(todo_all) - len(todo)
        logger.info("대상 강의: 전체 %d개 중 처리 %d개 "
                    "(완료 skip %d개%s%s)",
                    len(pairs), len(todo), len(pairs) - len(todo_all),
                    f", limit 보류 {deferred}개" if deferred else "",
                    ", 다시 만들기(덮어쓰기) ON" if force else "")

        try:
            for cname, lec in todo:
                key = lecture_key(cname, lec.seq)
                logger.info("── %s %d강 '%s'", cname, lec.seq, lec.name)
                lec_failed = False
                # 실패한 단계에 **의존하는** 단계만 건너뛴다(나머지는 계속 진행)
                blocked: set[str] = set()
                for stage in stages:
                    if stage in blocked:
                        logger.info("  · %s: 앞 단계 실패로 건너뜀", stage)
                        continue
                    if not should_run_stage(state, key, stage, force):
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
                        blocked |= dependent_stages(stage, stages)
                        continue
                    mark_stage(state, key, stage, ok=r["ok"],
                               error=r.get("error"),
                               skipped=bool(r.get("skipped")))
                    if r.get("extra_videos") is not None:
                        # 두 번째 영상 탐지 결과 보존(단계 기록과 별개 필드)
                        rec = state.setdefault(key, {})
                        rec["extra_videos"] = r["extra_videos"]
                    save_state(state_path, state)
                    if r["ok"]:
                        tag = "skip" if r.get("skipped") else "완료"
                        logger.info("  ✓ %s: %s", stage, tag)
                    else:
                        logger.warning("  ✗ %s 실패: %s", stage,
                                       r.get("error"))
                        lec_failed = True
                        blocked |= dependent_stages(stage, stages)
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
    ap.add_argument("--stages", nargs="+", default=None,
                    help="모드 단계 중 일부만 실행(예: --stages capture)")
    ap.add_argument("--force", action="store_true",
                    help="이미 완료된 차시·단계도 무시하고 다시 처리(덮어쓰기)")
    ap.add_argument("--state", default=str(DEFAULT_STATE),
                    help="상태 파일 경로(기본 state.json)")
    return ap.parse_args(argv)


def main(argv=None) -> None:
    args = parse_args(argv)
    summary = run(args.mode, course=args.course, seq=args.seq,
                  state_path=args.state, unwatched=args.unwatched,
                  limit=args.limit, only_stages=args.stages,
                  force=args.force)
    print(f"\n=== 요약 === {summary}", flush=True)


if __name__ == "__main__":
    main()
