"""[extra_video] 한 차시에 영상이 2개 이상일 때 — 두 번째 영상 예습노트.

방송대 한 차시(회차)는 플레이어 안에 클립이 1~3개 들어간다(docs/lms-map.md §4).
LMS 가 주는 MP3(strVidoAudoUrl)는 **차시당 1개**뿐이라, 기본 요약 파이프라인은
가장 긴 클립(본강의) 하나만 노트가 된다. 이 모듈은 나머지 '진짜 영상' 클립의
오디오를 HLS 에서 ffmpeg 로 뽑아 별도 예습노트로 저장한다.

순수 로직(단위테스트):
  - pick_extra_clips(clips)          : 본강의(최장) 제외 + 길이 충분한 클립만
  - clip_brief(clip)                 : state.json 에 남길 안전 요약(토큰 제거)
  - extra_note_name(name, part)      : '배열' + 2 → '배열 (2)'
  - extra_audio_filename(course, …)  : '자료구조_1강_2.mp3'
  - build_audio_cmd(url, out)        : HLS → MP3 ffmpeg 인자
  - pending_extras(state, …)         : 아직 노트 안 만든 두 번째 영상 목록
  - extra_prompt_text(clips)         : GUI 확인 다이얼로그 문구

IO(수동 검증):
  - extract_audio(url, out)          : ffmpeg 실행
  - make_extra_notes(page, lec, …)   : 플레이어 열기→오디오 추출→요약→노트 저장

⚠️ hlsUrl 에는 만료되는 JWT 토큰이 붙어 있다. **state.json·로그에 남기지 않는다**
   (clip_brief 로 idx/제목/길이만 남긴다).
"""
from __future__ import annotations

import subprocess

from proc_util import run_hidden
from pathlib import Path

from capture import FFMPEG, probe_duration
from download import sanitize

# 이보다 짧은 클립은 공지·인트로·맺음말 조각으로 보고 노트를 만들지 않는다
# (실측: 15강 clip1 = 138초짜리 안내 영상).
MIN_EXTRA_SEC = 300

# state.json 에 탐지 결과를 남길 필드명 / 노트 생성 단계 이름
STATE_FIELD = "extra_videos"
STAGE = "extra"


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def _dur(clip) -> float:
    """클립 길이(초). 숫자가 아니면 0."""
    d = (clip or {}).get("duration")
    return float(d) if isinstance(d, (int, float)) else 0.0


def pick_extra_clips(clips, min_seconds: int = MIN_EXTRA_SEC) -> list[dict]:
    """본강의(가장 긴 클립)를 뺀 나머지 중 '진짜 영상'만 idx 순으로.

    클립이 1개뿐이거나 길이를 못 잰 경우엔 빈 목록(= 두 번째 영상 없음).
    """
    valid = [c for c in (clips or []) if _dur(c) > 0]
    if len(valid) < 2:
        return []
    main = max(valid, key=_dur)
    extras = [c for c in valid
              if c is not main and _dur(c) >= float(min_seconds)]
    return sorted(extras, key=lambda c: int(c.get("idx") or 0))


def clip_brief(clip: dict) -> dict:
    """state.json 저장용 요약 — hlsUrl(토큰)은 절대 담지 않는다."""
    clip = clip or {}
    return {"idx": int(clip.get("idx") or 0),
            "title": str(clip.get("title") or ""),
            "duration": round(_dur(clip), 1)}


def extra_note_name(name: str, part: int) -> str:
    """두 번째 영상 노트의 차시명: '배열' + 2 → '배열 (2)'."""
    return f"{(name or '').strip()} ({int(part)})".strip()


def extra_audio_filename(course: str, seq, part: int) -> str:
    """'{과목}_{seq}강_{part}.mp3' — 기본 MP3({과목}_{seq}강.mp3)와 안 겹친다."""
    return f"{sanitize(course)}_{int(seq)}강_{int(part)}.mp3"


def build_audio_cmd(url: str, out_path, bitrate: str = "64k") -> list[str]:
    """HLS 스트림에서 오디오만 뽑아 MP3 로 저장하는 ffmpeg 인자.

    -vn(영상 제외) + libmp3lame 모노 64k → Gemini 업로드에 충분하고 가볍다.
    """
    return [FFMPEG, "-y", "-loglevel", "error",
            "-i", str(url), "-vn", "-ac", "1", "-b:a", str(bitrate),
            "-acodec", "libmp3lame", str(out_path)]


def _lecture_key(course: str, seq) -> str:
    """main.lecture_key 와 같은 규칙({과목}|{seq}) — GUI 가 main 을 임포트하지
    않고도 state.json 을 읽을 수 있게 여기 한 줄로 둔다."""
    return f"{course}|{int(seq)}"


def read_state(path) -> dict:
    """state.json 로드(없거나 깨졌으면 빈 dict)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        import json
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _lecture_rec(state: dict, course: str, seq) -> dict:
    return (state or {}).get(_lecture_key(course, seq), {}) or {}


def pending_extras(state: dict, course: str, seq) -> list[dict]:
    """이 차시에서 '노트 아직 없음'인 두 번째 영상 목록(없으면 빈 목록).

    capture 단계가 남긴 STATE_FIELD 기록을 읽고, extra 단계가 이미 성공했으면
    빈 목록을 돌려준다(같은 회차를 두 번 묻지 않게).
    """
    rec = _lecture_rec(state, course, seq)
    if (rec.get(STAGE) or {}).get("ok"):
        return []
    return list(rec.get(STATE_FIELD) or [])


def extra_prompt_text(clips, course: str = "", seq=None) -> str:
    """GUI 확인 다이얼로그 본문 — 몇 분짜리 영상이 몇 개 더 있는지."""
    clips = list(clips or [])
    head = f"{course} {seq}강".strip() if (course and seq is not None) else ""
    lines = [(f"{head} 회차에 영상이 {len(clips) + 1}개입니다." if head
              else f"이 회차에 영상이 {len(clips) + 1}개입니다.")]
    for i, c in enumerate(clips, start=2):
        mins = int(round(_dur(c) / 60))
        title = (c.get("title") or "").strip() or f"영상 {i}"
        lines.append(f"  · {i}번째 영상: {title} (약 {mins}분)")
    lines += ["", "두 번째 영상도 예습노트를 만들어 저장할까요?",
              "(오디오를 내려받아 요약합니다 — 영상 길이만큼 시간이 걸릴 수 있어요)"]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# IO (수동 검증)
# ---------------------------------------------------------------------------
def extract_audio(url: str, out_path, timeout: float = 3600.0,
                  bitrate: str = "64k") -> dict:
    """HLS → MP3 추출. return: {"ok","path","error"?}"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_audio_cmd(url, out_path, bitrate)
    try:
        r = run_hidden(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:  # noqa: BLE001 - ffmpeg 부재/타임아웃 모두 실패로
        return {"ok": False, "path": str(out_path), "error": str(e)[:160]}
    ok = (r.returncode == 0) and out_path.exists() and out_path.stat().st_size > 0
    res = {"ok": ok, "path": str(out_path)}
    if not ok:
        res["error"] = (r.stderr or "").strip()[:200] or "ffmpeg 출력 없음"
    return res


def detect_extra_clips(popup, on_event=lambda m: None) -> list[dict]:
    """열려 있는 플레이어 팝업에서 두 번째 영상(클립) 목록을 뽑는다.

    capture 단계가 이미 연 팝업을 재사용하려고 분리해 둔 함수.
    """
    from capture import collect_clips
    clips = collect_clips(popup)
    for c in clips:
        if c.get("duration") is None:
            c["duration"] = probe_duration(c.get("hlsUrl") or "")
    extras = pick_extra_clips(clips)
    on_event(f"클립 {len(clips)}개 · 두 번째 영상 {len(extras)}개")
    return extras


def make_extra_notes(page, lec, course: str, *, client,
                     downloads_dir, out_dir, on_event=lambda m: None) -> dict:
    """두 번째(이후) 영상의 예습노트를 만들어 저장한다. main.py 'extra' 단계용.

    플레이어를 열어 클립 목록을 얻고(hlsUrl 토큰은 팝업이 살아있는 동안만 유효
    하므로 오디오 추출까지 팝업 유지), 본강의를 뺀 클립마다:
      HLS→MP3 → Gemini 요약 → '{과목} {seq}강 - {차시명} (N).md' 저장.
    두 번째 영상이 없으면 skip(ok) 로 끝난다.
    """
    from summarize import (needs_summary, note_filename, save_summary,
                           summarize_lecture)
    from watch import open_player

    downloads_dir, out_dir = Path(downloads_dir), Path(out_dir)
    seq, name = lec.seq, lec.name

    popup = open_player(page, lec)
    jobs: list[tuple[int, Path]] = []      # (part, mp3 경로)
    try:
        extras = detect_extra_clips(popup, on_event)
        if not extras:
            return {"ok": True, "skipped": True, "detail": "두 번째 영상 없음"}

        for part, clip in enumerate(extras, start=2):
            disp = extra_note_name(name, part)
            note = out_dir / note_filename(course, seq, disp)
            if not needs_summary(note):
                on_event(f"  [{part}] 노트 이미 있음 skip: {note.name}")
                continue
            mp3 = downloads_dir / extra_audio_filename(course, seq, part)
            if mp3.exists() and mp3.stat().st_size > 0:
                on_event(f"  [{part}] 오디오 이미 있음: {mp3.name}")
            else:
                on_event(f"  [{part}] 오디오 추출: {mp3.name} "
                         f"({_dur(clip) / 60:.0f}분)")
                r = extract_audio(clip["hlsUrl"], mp3)
                if not r["ok"]:
                    return {"ok": False,
                            "error": f"오디오 추출 실패({part}): {r.get('error')}"}
            jobs.append((part, mp3))
    finally:
        try:
            popup.close()
        except Exception:
            pass

    # 요약·저장은 토큰이 필요 없으므로 플레이어를 닫고 진행한다.
    made = []
    for part, mp3 in jobs:
        disp = extra_note_name(name, part)
        pdf = downloads_dir / f"{sanitize(course)}_{seq}강.pdf"   # 강의록은 회차 공용
        on_event(f"  [{part}] 요약 생성: {disp}")
        md = summarize_lecture(client, course, seq, disp,
                               mp3_path=mp3 if mp3.exists() else None,
                               pdf_path=pdf if pdf.exists() else None,
                               on_event=on_event)
        if not md:
            return {"ok": False, "error": f"빈 요약 응답({part})"}
        dur = probe_duration(str(mp3)) if mp3.exists() else None
        res = save_summary(md, out_dir, course, seq, disp, duration=dur)
        on_event(f"  [{part}] 노트 저장: {Path(res['md']).name}")
        made.append(Path(res["md"]).name)

    if not made:
        return {"ok": True, "skipped": True, "detail": "이미 만들어진 노트"}
    return {"ok": True, "detail": {"notes": made}}
