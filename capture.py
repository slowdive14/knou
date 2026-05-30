"""Phase 6 — 동영상 프레임 캡처 & 요약 노트 임베드.

요약(Phase 5)이 뽑은 타임스탬프(`*.timestamps.json`)마다 강의 영상에서 화면
프레임을 ffmpeg로 추출해, 요약 노트의 해당 개념 줄 바로 아래에 `![[이미지]]`로
인라인 임베드한다. 영상 타임라인은 MP3(요약 기준)와 1:1 → MP3 길이에 가장
가까운 영상 클립을 골라 그 클립을 절대초로 seek 한다.

순수 로직(단위테스트 대상):
  - capture_filename(subject, seq, seconds, ext)
  - pick_clip_by_duration(clips, target_seconds)   : MP3 길이에 가장 가까운 클립
  - build_ffmpeg_cmd(url, seconds, out_path, ...)
  - needs_capture(path)
  - embed_captures(markdown, captures)             : 타임스탬프 줄 아래 ![[..]] 삽입

ffmpeg/브라우저/IO(수동 검증):
  - probe_duration(url)                            : ffprobe 길이
  - collect_clips(popup)                           : ifrmVODPlayer_dataN → [{title,hlsUrl}]
  - resolve_clips(page, lec)                       : 플레이어 열고 클립+길이 조회
  - capture_frame(url, seconds, out_path)          : ffmpeg 단일 프레임
  - capture_lecture(...)                           : 전체 오케스트레이션

⚠️ 영상 토큰(JWT)은 URL에 들어있고 시간제한이 있다 → 캡처 직전에 라이브로 조회.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from download import sanitize
from summarize import DEFAULT_MODEL, _TS_RE, seconds_to_timestamp, timestamp_to_seconds

DEFAULT_EXT = "jpg"
# ffmpeg/ffprobe 실행파일(PATH 에 있으면 이름만으로 충분)
FFMPEG = "ffmpeg"
FFPROBE = "ffprobe"
# 비전 검증: 개념 타임스탬프 기준 후보 프레임 오프셋(초).
# 6장(−40·−20·0·+20·+40·+60) — 말하는 시점 전후로 넓게 잡아 fallback 최소화.
VISION_OFFSETS = (-40, -20, 0, 20, 40, 60)


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def capture_filename(subject: str, seq: int, seconds: int, ext: str = DEFAULT_EXT) -> str:
    """'{과목}_{seq}강_{HH-MM-SS}.{ext}' (안전한 파일명, ':'→'-')."""
    hms = seconds_to_timestamp(seconds).replace(":", "-")
    ext = ext.lstrip(".").lower()
    return f"{sanitize(subject)}_{seq}강_{hms}.{ext}"


def pick_clip_by_duration(clips: list[dict], target_seconds: float):
    """길이가 target_seconds 에 가장 가까운 클립 반환(없으면 None).

    clips: [{"title","hlsUrl","duration"(초, float|None)}, ...]
    duration 이 유효한 클립만 후보. MP3(요약 기준) 길이와 1:1 매칭용.
    """
    cand = [c for c in clips if isinstance(c.get("duration"), (int, float))
            and c["duration"] > 0]
    if not cand:
        return None
    return min(cand, key=lambda c: abs(c["duration"] - float(target_seconds)))


def candidate_seconds(base, offsets=VISION_OFFSETS, clip_dur=None) -> list[int]:
    """개념 시점(base) 주변 후보 초 목록(시간순·중복제거).

    base + 각 offset 을 계산해, 0 미만이거나 clip_dur 초과인 후보는 버린다
    (검은 끝프레임/음수 seek 방지). 비전 검증에 보낼 후보 프레임 위치용.
    """
    base = int(base)
    out: set[int] = set()
    for off in offsets:
        s = base + int(off)
        if s < 0:
            continue
        if clip_dur is not None and s > float(clip_dur):
            continue
        out.add(s)
    return sorted(out)


def orphan_captures(existing: list[str], referenced, subject: str, seq: int) -> list[str]:
    """이 과목·차시 캡처 파일 중 노트에서 참조되지 않는 파일명 목록(삭제 후보).

    `{과목}_{seq}강_` 접두사를 가진 파일만 대상으로 해, 다른 차시/과목 캡처는
    절대 건드리지 않는다. referenced 는 노트의 `![[..]]` 임베드 파일명 집합.
    """
    prefix = f"{sanitize(subject)}_{seq}강_"
    ref = set(referenced or ())
    return [fn for fn in existing
            if fn.startswith(prefix) and fn not in ref]


def parse_vision_choice(raw, n_candidates: int):
    """비전 응답에서 고른 후보 인덱스(0~n-1) 추출. 없으면 None.

    허용 형태: `{"index":2,...}` / 코드펜스로 감싼 JSON / 맨숫자 "2".
    -1(=맞는 것 없음)·범위초과·깨진 응답은 모두 None(→ 호출부에서 fallback).
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    if s.startswith("```"):
        s = re.sub(r"^```[a-zA-Z]*\n?", "", s)
        s = re.sub(r"\n?```$", "", s).strip()
    idx = None
    try:
        data = json.loads(s)
        if isinstance(data, dict):
            idx = data.get("index")
        elif isinstance(data, bool):
            idx = None
        elif isinstance(data, (int, float)):
            idx = int(data)
    except (ValueError, TypeError):
        m = re.search(r"-?\d+", s)
        if m:
            idx = int(m.group(0))
    if idx is None:
        return None
    try:
        idx = int(idx)
    except (TypeError, ValueError):
        return None
    if 0 <= idx < n_candidates:
        return idx
    return None


def build_vision_prompt(label: str, n: int) -> str:
    """개념 라벨과 후보 N장을 비전 모델에 제시하는 한국어 프롬프트."""
    return (
        f"아래는 한 강의 영상에서 '{label}' 개념을 설명하는 부근에서 시간 순서대로 "
        f"뽑은 슬라이드 화면 {n}장입니다(0번부터 {n - 1}번까지). "
        f"각 슬라이드의 제목과 본문 텍스트를 읽고, 이 개념의 내용과 가장 잘 일치하는 "
        f"슬라이드 한 장의 번호를 고르세요. 명확히 맞는 것이 없으면 -1 을 고르세요. "
        f'반드시 JSON 한 줄로만 답하세요: {{"index": <정수>, "reason": "<짧은 이유>"}}'
    )


def build_ffmpeg_cmd(url: str, seconds, out_path, quality: int = 2) -> list[str]:
    """타임스탬프 1프레임 추출용 ffmpeg 인자 리스트.

    -ss 를 -i 앞에 둬 입력 단계 fast seek(키프레임 기준, HLS에서 빠름).
    타임스탬프는 근사치라 키프레임 스냅으로 충분. -y 로 재실행 시 덮어쓰기.
    """
    return [
        FFMPEG, "-y", "-loglevel", "error",
        "-ss", str(int(seconds)),
        "-i", str(url),
        "-frames:v", "1",
        "-q:v", str(int(quality)),
        "-an",
        str(out_path),
    ]


def needs_capture(path) -> bool:
    """캡처 이미지가 없거나 비어 있으면 True."""
    p = Path(path)
    try:
        return (not p.exists()) or p.stat().st_size == 0
    except OSError:
        return True


_EMBED_LINE_RE = re.compile(r"^\s*!\[\[.+?\]\]\s*$")


def embed_captures(markdown: str, captures: dict) -> str:
    """타임스탬프가 있는 줄 바로 아래에 `![[파일명]]` 임베드를 삽입/갱신한다.

    captures: {seconds(int): filename(str)}.
    - 같은 줄 타임스탬프의 초가 captures 에 있으면 그 줄 다음에 임베드 한 줄 추가.
    - 바로 아래에 이미 임베드 줄이 있으면 새 파일명으로 **교체**(같으면 그대로 멱등).
      → 비전 검증 재실행으로 선택 프레임이 바뀌어도 중복 삽입되지 않음.
    - 타임스탬프 없는 줄/매칭 없는 줄은 그대로.
    """
    lines = (markdown or "").splitlines()
    out: list[str] = []
    i, n = 0, len(lines)
    while i < n:
        line = lines[i]
        out.append(line)
        m = _TS_RE.search(line)
        if m:
            fn = captures.get(timestamp_to_seconds(m.group(1)))
            if fn:
                out.append(f"![[{fn}]]")
                # 바로 아래가 기존 임베드 줄이면 그 줄은 소비(교체)
                if i + 1 < n and _EMBED_LINE_RE.match(lines[i + 1]):
                    i += 2
                    continue
        i += 1
    text = "\n".join(out)
    if markdown.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


# ---------------------------------------------------------------------------
# ffmpeg / 브라우저 / IO (수동 검증)
# ---------------------------------------------------------------------------

# 팝업 메인 프레임의 전역 ifrmVODPlayer_dataN → [{idx,title,fileId,hlsUrl}]
_COLLECT_JS = """
() => {
  const out = [];
  for (let i = 0; i < 30; i++) {
    const d = window['ifrmVODPlayer_data' + i];
    if (!d) continue;
    let title = '', hls = '', fid = '';
    try { title = d.source[0].fileTitle; } catch(e){}
    try { hls = d.source[0].stream[0].hlsUrl; } catch(e){}
    try { fid = d.lectPldcTocNo || d.source[0].fileId || ''; } catch(e){}
    out.push({idx: i, title: title, fileId: fid, hlsUrl: hls});
  }
  return JSON.stringify(out);
}
"""


def probe_duration(url: str, timeout: float = 120.0):
    """ffprobe 로 스트림 길이(초) 측정. 실패 시 None."""
    try:
        r = subprocess.run(
            [FFPROBE, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(url)],
            capture_output=True, text=True, timeout=timeout,
        )
        s = (r.stdout or "").strip()
        return float(s) if s else None
    except Exception:
        return None


def collect_clips(popup) -> list[dict]:
    """플레이어 팝업에서 클립 목록(제목+hlsUrl) 수집."""
    raw = popup.evaluate(_COLLECT_JS)
    return json.loads(raw) if raw else []


def resolve_clips(page, lec, with_duration: bool = True, on_event=None) -> list[dict]:
    """플레이어를 열어 클립 목록을 가져오고(옵션) 각 클립 길이를 ffprobe 로 측정.

    return: [{"idx","title","fileId","hlsUrl","duration"(float|None)}, ...]
    """
    from watch import open_player  # 지연 임포트(플레이어 제어는 IO 계층)

    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    popup = open_player(page, lec)
    try:
        clips = collect_clips(popup)
        log(f"클립 {len(clips)}개 조회")
        if with_duration:
            for c in clips:
                c["duration"] = probe_duration(c.get("hlsUrl") or "")
                log(f"  [{c['idx']}] {c.get('title')} dur={c.get('duration')}")
        # hlsUrl 토큰은 팝업이 살아있는 동안 유효 → 캡처까지 popup 유지 위해 반환
        return clips
    finally:
        try:
            popup.close()
        except Exception:
            pass


def capture_frame(url: str, seconds: int, out_path, quality: int = 2,
                  timeout: float = 180.0) -> dict:
    """ffmpeg 로 url 의 seconds 지점 1프레임을 out_path 에 저장.

    return: {"ok","seconds","path","error"?}
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = build_ffmpeg_cmd(url, seconds, out_path, quality)
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception as e:
        return {"ok": False, "seconds": seconds, "path": str(out_path),
                "error": str(e)[:120]}
    ok = (r.returncode == 0) and out_path.exists() and out_path.stat().st_size > 0
    res = {"ok": ok, "seconds": seconds, "path": str(out_path)}
    if not ok:
        res["error"] = (r.stderr or "").strip()[:200] or "no output"
    return res


def load_timestamps(ts_path) -> list[dict]:
    """`*.timestamps.json` 로드 → timestamps 리스트."""
    data = json.loads(Path(ts_path).read_text(encoding="utf-8"))
    return data.get("timestamps", [])


def capture_lecture(page, lec, subject, seq, name, mp3_path, note_path,
                    timestamps=None, out_dir=None, ext=DEFAULT_EXT,
                    overwrite=False, on_event=None) -> dict:
    """한 차시: 영상 클립 조회 → MP3 길이로 매칭 → 타임스탬프별 프레임 캡처 →
    요약 노트에 인라인 임베드.

    timestamps 가 None 이면 note_path 의 `*.timestamps.json`(또는 .md→.timestamps.json)
    에서 로드. out_dir 기본값 = note_path 폴더의 `_captures` 하위.
    플레이어 팝업을 캡처 끝날 때까지 열어 둔 채 진행한다(토큰 세션 안전).

    return: {"clip","ts_count","captured","skipped","failed","out_dir","note"}
    """
    from watch import open_player

    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    note_path = Path(note_path)
    if timestamps is None:
        ts_path = note_path.with_suffix(".timestamps.json")
        timestamps = load_timestamps(ts_path)
    if out_dir is None:
        out_dir = note_path.parent / "_captures"
    out_dir = Path(out_dir)

    target = probe_duration(str(mp3_path))
    log(f"MP3 길이: {target}s")

    popup = open_player(page, lec)
    captured = skipped = failed = 0
    chosen = None
    captures: dict[int, str] = {}
    try:
        clips = collect_clips(popup)
        for c in clips:
            c["duration"] = probe_duration(c.get("hlsUrl") or "")
        chosen = pick_clip_by_duration(clips, target) if target else None
        if not chosen:
            log("⚠️ 매칭되는 영상 클립을 찾지 못함")
            return {"clip": None, "ts_count": len(timestamps), "captured": 0,
                    "skipped": 0, "failed": 0, "out_dir": str(out_dir),
                    "note": str(note_path)}
        log(f"선택 클립: [{chosen['idx']}] {chosen.get('title')} "
            f"({chosen.get('duration')}s, MP3와 차이 "
            f"{abs(chosen['duration'] - target):.1f}s)")

        for t in timestamps:
            sec = int(t["seconds"])
            fn = capture_filename(subject, seq, sec, ext)
            captures[sec] = fn
            dest = out_dir / fn
            if not overwrite and not needs_capture(dest):
                skipped += 1
                continue
            r = capture_frame(chosen["hlsUrl"], sec, dest)
            if r["ok"]:
                captured += 1
                log(f"  ✅ {seconds_to_timestamp(sec)} → {fn}")
            else:
                failed += 1
                log(f"  ❌ {seconds_to_timestamp(sec)}: {r.get('error','')[:80]}")
    finally:
        try:
            popup.close()
        except Exception:
            pass

    # 노트에 인라인 임베드(캡처 성공/기존 존재한 것만)
    embeddable = {sec: fn for sec, fn in captures.items()
                  if not needs_capture(out_dir / fn)}
    if embeddable and note_path.exists():
        md = note_path.read_text(encoding="utf-8")
        new_md = embed_captures(md, embeddable)
        if new_md != md:
            note_path.write_text(new_md, encoding="utf-8")
            log(f"노트 임베드 갱신: {note_path.name}")

    return {"clip": chosen.get("title") if chosen else None,
            "ts_count": len(timestamps), "captured": captured,
            "skipped": skipped, "failed": failed,
            "out_dir": str(out_dir), "note": str(note_path)}


# ---------------------------------------------------------------------------
# 비전 검증(옵션 2) — 후보 프레임 중 개념과 맞는 슬라이드를 Gemini 가 선택
# ---------------------------------------------------------------------------
def select_best_frame(client, label, image_paths, model=DEFAULT_MODEL,
                      on_event=None) -> dict:
    """후보 프레임(image_paths, 시간순) 중 개념(label)과 맞는 1장을 비전이 선택.

    이미지는 인라인 바이트로 전송(한글 파일명 업로드 트랩 회피).
    return: {"index": int|None, "reason": str, "raw"?: str, "error"?: str}
      index=None → 맞는 것 없음(-1)/파싱 실패/호출 실패 (호출부에서 fallback).
    ⚠️ API 키는 client 내부에만 존재 — 로그/출력 금지.
    """
    from google.genai import types  # 지연 임포트(AI 계층)

    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    n = len(image_paths)
    if n == 0:
        return {"index": None, "reason": "후보 없음"}
    try:
        parts = []
        for p in image_paths:
            parts.append(types.Part.from_bytes(
                data=Path(p).read_bytes(), mime_type="image/jpeg"))
        parts.append(build_vision_prompt(label, n))
        resp = client.models.generate_content(
            model=model, contents=parts,
            config=types.GenerateContentConfig(
                response_mime_type="application/json"),
        )
        raw = (getattr(resp, "text", None) or "").strip()
    except Exception as e:  # noqa: BLE001 - 어떤 실패든 fallback 으로
        return {"index": None, "reason": "비전 호출 실패",
                "error": str(e)[:120]}
    idx = parse_vision_choice(raw, n)
    reason = ""
    try:
        d = json.loads(re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw).strip())
        if isinstance(d, dict):
            reason = str(d.get("reason", ""))[:80]
    except Exception:
        pass
    return {"index": idx, "reason": reason, "raw": raw}


def _existing_embed_secs(markdown: str, out_dir: Path) -> set[int]:
    """노트에서 '타임스탬프 줄 + 바로 아래 유효 이미지 임베드'가 이미 있는
    개념의 base 초 집합. (재실행 시 비전 비용 재지출 방지용 skip 판정)."""
    secs: set[int] = set()
    lines = (markdown or "").splitlines()
    for i, line in enumerate(lines):
        m = _TS_RE.search(line)
        if not m:
            continue
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        em = re.match(r"^!\[\[(.+?)\]\]$", nxt)
        if not em:
            continue
        fn = em.group(1)
        if not needs_capture(out_dir / fn):
            secs.add(timestamp_to_seconds(m.group(1)))
    return secs


def capture_lecture_verified(page, lec, subject, seq, name, mp3_path, note_path,
                             client, timestamps=None, out_dir=None,
                             offsets=VISION_OFFSETS, ext=DEFAULT_EXT,
                             overwrite=False, prune=True, on_event=None) -> dict:
    """비전 검증판 캡처: 개념마다 후보 N프레임 → Gemini 비전이 맞는 슬라이드 선택
    → 그 1장만 `_captures/`에 남기고 노트 임베드. -1/실패 시 t정각 fallback.

    capture_lecture 와 동작 흐름은 같되, 타임스탬프마다 candidate_seconds 만큼
    후보를 _captures/_cand/에 임시 캡처하고 선택 후 나머지는 삭제한다.
    return: {"clip","ts_count","picked","fallback","skipped","failed",
             "out_dir","note"}
    """
    from watch import open_player

    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    note_path = Path(note_path)
    if timestamps is None:
        timestamps = load_timestamps(note_path.with_suffix(".timestamps.json"))
    if out_dir is None:
        out_dir = note_path.parent / "_captures"
    out_dir = Path(out_dir)
    staging = out_dir / "_cand"

    md0 = note_path.read_text(encoding="utf-8") if note_path.exists() else ""
    already = set() if overwrite else _existing_embed_secs(md0, out_dir)

    target = probe_duration(str(mp3_path))
    log(f"MP3 길이: {target}s")

    popup = open_player(page, lec)
    picked = fallback = skipped = failed = 0
    chosen = None
    captures: dict[int, str] = {}
    try:
        clips = collect_clips(popup)
        for c in clips:
            c["duration"] = probe_duration(c.get("hlsUrl") or "")
        chosen = pick_clip_by_duration(clips, target) if target else None
        if not chosen:
            log("⚠️ 매칭되는 영상 클립을 찾지 못함")
            return {"clip": None, "ts_count": len(timestamps), "picked": 0,
                    "fallback": 0, "skipped": 0, "failed": 0,
                    "out_dir": str(out_dir), "note": str(note_path)}
        clip_dur = chosen.get("duration")
        log(f"선택 클립: [{chosen['idx']}] {chosen.get('title')} "
            f"({clip_dur}s, MP3와 차이 {abs(clip_dur - target):.1f}s)")

        for t in timestamps:
            base = int(t["seconds"])
            label = (t.get("label") or "").strip()
            if base in already:
                skipped += 1
                continue

            secs = candidate_seconds(base, offsets, clip_dur=clip_dur)
            cand: list[tuple[int, Path]] = []
            for s in secs:
                cp = staging / f"{sanitize(subject)}_{seq}_{base}_c{s}.{ext}"
                if capture_frame(chosen["hlsUrl"], s, cp)["ok"]:
                    cand.append((s, cp))
            if not cand:
                failed += 1
                log(f"  ❌ {seconds_to_timestamp(base)}: 후보 캡처 실패")
                continue

            cap_secs = [s for s, _ in cand]
            cand_map = {s: p for s, p in cand}
            used_fallback = False
            if len(cand) == 1:
                chosen_sec = cand[0][0]
                why = "유일후보"
            else:
                sel = select_best_frame(
                    client, label, [p for _, p in cand], on_event=on_event)
                idx = sel.get("index")
                if idx is None:
                    chosen_sec = base if base in cap_secs else cap_secs[0]
                    used_fallback = True
                    why = "fallback(t정각)"
                else:
                    chosen_sec = cand[idx][0]
                    why = f"비전 pick: {sel.get('reason', '')}".strip()

            final_fn = capture_filename(subject, seq, chosen_sec, ext)
            final_path = out_dir / final_fn
            if final_path.exists():
                try:
                    final_path.unlink()
                except OSError:
                    pass
            shutil.move(str(cand_map[chosen_sec]), str(final_path))
            for s, p in cand:  # 나머지 후보 정리
                if s != chosen_sec and Path(p).exists():
                    try:
                        Path(p).unlink()
                    except OSError:
                        pass
            captures[base] = final_fn
            if used_fallback:
                fallback += 1
            else:
                picked += 1
            off = chosen_sec - base
            log(f"  ✅ {seconds_to_timestamp(base)} "
                f"→ {seconds_to_timestamp(chosen_sec)} (Δ{off:+d}s) [{why}]")
    finally:
        try:
            popup.close()
        except Exception:
            pass
        shutil.rmtree(staging, ignore_errors=True)

    embeddable = {sec: fn for sec, fn in captures.items()
                  if not needs_capture(out_dir / fn)}
    final_md = ""
    if embeddable and note_path.exists():
        md = note_path.read_text(encoding="utf-8")
        final_md = embed_captures(md, embeddable)
        if final_md != md:
            note_path.write_text(final_md, encoding="utf-8")
            log(f"노트 임베드 갱신: {note_path.name}")
    elif note_path.exists():
        final_md = note_path.read_text(encoding="utf-8")

    # orphan 청소: 노트가 더 이상 참조 않는 이 차시 캡처 삭제
    pruned = 0
    if prune and out_dir.exists():
        referenced = set(re.findall(r"!\[\[(.+?)\]\]", final_md))
        existing = [p.name for p in out_dir.glob(f"{sanitize(subject)}_{seq}강_*")]
        for fn in orphan_captures(existing, referenced, subject, seq):
            try:
                (out_dir / fn).unlink()
                pruned += 1
            except OSError:
                pass
        if pruned:
            log(f"orphan 캡처 {pruned}개 삭제")

    return {"clip": chosen.get("title") if chosen else None,
            "ts_count": len(timestamps), "picked": picked,
            "fallback": fallback, "skipped": skipped, "failed": failed,
            "pruned": pruned, "out_dir": str(out_dir), "note": str(note_path)}
