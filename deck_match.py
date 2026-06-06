"""[deck_match] 범용 슬라이드 덱 매칭 캡처 — 모든 강의 공통 경로.

강의 영상에서 실제 슬라이드 덱을 추출(키프레임 디코드 + 본문 crop + fps=1
→ dHash dedup)하고, 요약노트의 각 개념을 Gemini 멀티모달 1회 호출로
'그 내용이 실제로 화면에 보이는' 슬라이드에 매칭한 뒤, 노트의 🎬 마커와
임베드를 슬라이드의 실제 등장 시각으로 재작성한다.

기존 capture.capture_lecture_verified(비전 윈도우)와 독립적인 새 경로다.
미매칭 개념(slide=0)은 노트 원본 마커/임베드를 그대로 둔다(기본값).
한 슬라이드로 몰리는 collapse를 막기 위함이며, 전방채움은 --fill로만 켠다.

⚠️ GEMINI_API_KEY/HLS URL(JWT)은 절대 출력하지 않는다.
⚠️ 노트 수정은 apply=True(또는 CLI --apply)일 때만 일어난다.

라이브러리(main.py용):
    deck_capture_lecture(page, lec, course, seq, name, *, cfg, client,
                         note_path, on_event=...) -> dict

CLI(검증/수동):
    .venv/Scripts/python.exe -u deck_match.py --course 이산수학 --seq 13
    .venv/Scripts/python.exe -u deck_match.py --course 이산수학 --seq 13 --apply
    --reuse-frames  : frames_{seq}/ 재사용(영상 재추출·로그인 생략)
    --reuse-match   : deck_{seq}_match.json 재사용(Gemini 재호출 생략)
    --fill          : 미매칭 개념 전방채움 활성화(기본=원본 유지)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from google.genai import types
from PIL import Image

from capture import (
    DEFAULT_EXT,
    FFMPEG,
    _EMBED_LINE_RE,
    capture_filename,
    collect_clips,
    orphan_captures,
    probe_duration,
)
from download import sanitize
from summarize import (
    _TS_RE,
    extract_timestamps,
    note_filename,
    seconds_to_timestamp,
    timestamp_to_seconds,
)

MODEL = "gemini-2.5-flash"
# 슬라이드 본문 crop=가로:세로:x:y (1280x720 영상 기준).
# 강의 슬라이드(흰 본문 패널)는 세로로 y≈58~668까지 차서, 예전 값(높이 470·y=80)은
# 패널 아래쪽(하단 도식·표)을 잘라먹었다. → 세로를 패널 전체(y 40~700)로 넓혔다.
# 가로: 발표자는 x≈880+ 에 서므로 그보다 왼쪽은 본문 전용 → 수식·축 라벨이 오른쪽
# 끝까지 가는 슬라이드(발표자 없는 본문)가 잘리지 않도록 가로 끝을 x=960 까지 둔다.
# (발표자 있는 표지 프레임엔 어깨 일부가 들어오지만, 본문 잘림 방지를 우선한다.)
DEFAULT_CROP = "920:660:40:40"
DEFAULT_THRESH = 20
# 빈 표지/구분 슬라이드 제외: 본문 영역 '잉크(글자·도형)' 비율이 이 값 미만이면
# 제목만 있고 본문이 텅 빈 슬라이드로 보고 덱에서 뺀다(노트에 임베드 안 함).
DEFAULT_EMPTY_THRESH = 0.01
# 본문 판별 영역(crop된 슬라이드 기준 비율): 제목 띠·바깥 여백·우측 발표자 제외.
_BODY_BOX_FRAC = (0.03, 0.20, 0.90, 0.94)


# ---------------------------------------------------------------------------
# 슬라이드 덱 추출 (영상 → 초단위 프레임 → dHash dedup)
# ---------------------------------------------------------------------------
def dhash(path: Path, size: int = 8) -> int:
    img = Image.open(path).convert("L").resize((size + 1, size), Image.BILINEAR)
    px = list(img.getdata())
    bits = 0
    w = size + 1
    for row in range(size):
        base = row * w
        for col in range(size):
            bits = (bits << 1) | (1 if px[base + col] > px[base + col + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def extract_frames(url: str, frames_dir: Path, crop: str,
                   timeout: float = 1800.0,
                   on_event=lambda m: None) -> int:
    """키프레임 디코드 + crop + fps=1 → 초단위 인덱스 프레임. 반환=프레임 수.

    f_000001.jpg = 0초, f_i.jpg = (i-1)초 (fps=1이라 파일순번 = 초).
    """
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("f_*.jpg"):
        old.unlink()
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-skip_frame", "nokey",
        "-i", str(url),
        "-vf", f"crop={crop},fps=1",
        "-q:v", "3",
        str(frames_dir / "f_%06d.jpg"),
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    dt = time.time() - t0
    n = len(list(frames_dir.glob("f_*.jpg")))
    on_event(f"프레임 추출: {n}장 ({dt:.0f}s, rc={r.returncode})")
    if r.returncode != 0 and n == 0:
        on_event(f"ffmpeg stderr(tail): {(r.stderr or '')[-300:]}")
    return n


def dedup_frames(frames_dir: Path, thresh: int) -> list[dict]:
    """frames_dir(초단위) → 덱 [{n, sec, ts, path}] (번호순).

    프레임을 순서대로 훑어 직전 경계 해시와 thresh 초과로 달라지면 새 슬라이드.
    점진적 bullet build 도 누적되면 경계를 넘어 분리된다(과분할은 안전).
    """
    frames = sorted(frames_dir.glob("f_*.jpg"))
    if not frames:
        return []
    hashes = [dhash(f) for f in frames]
    bounds: list[tuple[int, Path]] = [(0, frames[0])]
    ref = hashes[0]
    for i in range(1, len(hashes)):
        if hamming(hashes[i], ref) > thresh:
            bounds.append((i, frames[i]))   # 인덱스 i == i초
            ref = hashes[i]
    return [{"n": k, "sec": sec, "ts": seconds_to_timestamp(sec), "path": p}
            for k, (sec, p) in enumerate(bounds, 1)]


def body_ink_ratio(path, box_frac=_BODY_BOX_FRAC, step: int = 3) -> float:
    """본문 영역의 '잉크(글자·도형)' 비율(0~1). 빈 표지일수록 0에 가깝다.

    crop된 슬라이드 이미지의 본문(제목 띠·바깥 여백·우측 발표자 제외) 안에서
    '흰 배경이 아닌' 픽셀의 비율을 센다. 표지/구분 슬라이드는 본문이 거의
    흰색이라 0에 가깝고, 글자·도식이 있는 슬라이드는 뚜렷이 높다.
    읽기 실패 시 1.0(=내용 있음)으로 봐서 실수로 드롭하지 않는다.
    """
    try:
        im = Image.open(path).convert("RGB")
    except Exception:
        return 1.0
    W, H = im.size
    l, t, r, b = box_frac
    box = im.crop((int(W * l), int(H * t), int(W * r), int(H * b)))
    px = box.load()
    bw, bh = box.size
    ink = tot = 0
    for y in range(0, bh, step):
        for x in range(0, bw, step):
            rr, gg, bb = px[x, y]
            tot += 1
            if not (rr > 190 and gg > 190 and bb > 190):
                ink += 1
    return ink / tot if tot else 1.0


def is_empty_slide(path, thresh: float = DEFAULT_EMPTY_THRESH) -> bool:
    """제목만 있고 본문이 텅 빈 표지/구분 슬라이드면 True(임베드 가치 없음)."""
    return body_ink_ratio(path) < thresh


def drop_empty_slides(deck: list[dict], thresh: float = DEFAULT_EMPTY_THRESH,
                      on_event=lambda m: None) -> list[dict]:
    """덱에서 빈 표지 슬라이드를 빼고 번호(n)를 다시 매긴다.

    thresh<=0 이면 거르지 않는다(디버그용). 제거된 슬라이드는 매칭 후보에서
    빠져 노트에 임베드되지 않는다(해당 개념은 미매칭 → 원본 마커 유지).
    """
    if thresh is None or thresh <= 0:
        return deck
    kept = [s for s in deck if not is_empty_slide(s.get("path"), thresh)]
    dropped = len(deck) - len(kept)
    for i, s in enumerate(kept, 1):
        s["n"] = i
    if dropped:
        on_event(f"빈 표지 슬라이드 {dropped}개 제외 "
                 f"(덱 {len(deck)}→{len(kept)})")
    return kept


def scrub_empty_embeds(md: str, out_dir, thresh: float = DEFAULT_EMPTY_THRESH):
    """노트에서 '빈 슬라이드 이미지'를 가리키는 임베드 줄을 제거한다.

    덱 필터(drop_empty_slides)는 새 빈 임베드를 막지만, 필터 도입 전에 만들어져
    미매칭 개념에 남아있는 빈 임베드는 apply_to_note 가 건드리지 않아 그대로 남는다.
    이 함수가 그런 잔존 빈 임베드 줄을 지운다(이미지 파일은 이후 orphan 청소가 삭제).
    return: (new_md, removed_filenames:set)
    """
    out_dir = Path(out_dir)
    removed: set[str] = set()
    out: list[str] = []
    for line in (md or "").splitlines():
        m = re.match(r"^\s*!\[\[(.+?)\]\]\s*$", line)
        if m:
            p = out_dir / m.group(1)
            if p.exists() and is_empty_slide(p, thresh):
                removed.add(m.group(1))
                continue
        out.append(line)
    text = "\n".join(out)
    if md.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text, removed


def _pick_main_clip(popup, on_event=lambda m: None) -> dict | None:
    """플레이어 팝업에서 가장 긴(학습하기) 클립 1개 선택."""
    clips = collect_clips(popup)
    for c in clips:
        c["duration"] = probe_duration(c.get("hlsUrl") or "")
    valid = [c for c in clips
             if isinstance(c.get("duration"), (int, float)) and c["duration"] > 0]
    if not valid:
        return None
    main = max(valid, key=lambda c: c["duration"])
    on_event(f"대상 클립 [{main.get('idx')}] {main.get('title')} "
             f"({main['duration']:.0f}s)")
    return main


def build_deck_live(page, lec, frames_dir: Path, crop: str, thresh: int,
                    empty_thresh: float = DEFAULT_EMPTY_THRESH,
                    on_event=lambda m: None) -> list[dict]:
    """플레이어 열기→가장 긴 클립 HLS 추출→dedup→빈 표지 제외. 반환: 덱."""
    from watch import open_player
    popup = open_player(page, lec)
    try:
        main = _pick_main_clip(popup, on_event)
        if not main:
            on_event("유효 클립 없음")
            return []
        extract_frames(main["hlsUrl"], frames_dir, crop, on_event=on_event)
    finally:
        try:
            popup.close()
        except Exception:
            pass
    deck = dedup_frames(frames_dir, thresh)
    deck = drop_empty_slides(deck, empty_thresh, on_event=on_event)
    on_event(f"덱 {len(deck)}장 (thresh={thresh})")
    return deck


# ---------------------------------------------------------------------------
# 노트 개념 파싱
# ---------------------------------------------------------------------------
def _clean(text: str) -> str:
    text = re.sub(r"\*\*|🎬|`", "", text)
    text = re.sub(r"^\s*[\-\*\d\.>#]+\s*", "", text)
    return text.strip()


def parse_concepts(md: str) -> list[dict]:
    """노트 → 개념 블록 목록.

    각 🎬 마커 줄마다: 상위 heading, 직전 경계~마커 사이 본문(정의 등),
    현재 첫 마커 시각(secs), 마커 줄 인덱스, 바로 아래 embed 줄 인덱스(있으면).
    """
    lines = md.splitlines()
    concepts: list[dict] = []
    last_heading = ""
    boundary = -1   # 직전 heading 또는 마커 줄
    for i, line in enumerate(lines):
        if re.match(r"^#{1,6}\s", line):
            last_heading = _clean(line)
            boundary = i
            continue
        if "🎬" in line and _TS_RE.search(line):
            body = []
            for j in range(boundary + 1, i):
                t = lines[j].strip()
                if not t or _EMBED_LINE_RE.match(t):
                    continue
                body.append(_clean(t))
            secs = [timestamp_to_seconds(x) for x in _TS_RE.findall(line)]
            embed_idx = (i + 1 if i + 1 < len(lines)
                         and _EMBED_LINE_RE.match(lines[i + 1]) else None)
            concepts.append({
                "heading": last_heading,
                "body": " ".join(body)[:400],
                "cur_sec": secs[0] if secs else 0,
                "marker_idx": i,
                "embed_idx": embed_idx,
            })
            boundary = i
    return concepts


# ---------------------------------------------------------------------------
# Gemini 매칭 (멀티모달 1회)
# ---------------------------------------------------------------------------
def build_match_prompt(concepts: list[dict]) -> str:
    lines = [
        "너는 강의 슬라이드와 요약노트 개념을 '내용'으로 매칭하는 도우미다.",
        "위에 강의 슬라이드 이미지를 번호·시각과 함께 순서대로 제시했다.",
        "아래는 요약노트의 개념 목록이다. 각 개념에 대해, 그 개념의 정의/내용이",
        "'실제로 화면에 보이는' 가장 잘 맞는 슬라이드 1장을 골라라.",
        "- 슬라이드의 제목과 본문 텍스트를 읽고 개념 내용과 의미가 일치하는지 보라.",
        "- 도입부 애니메이션/표지처럼 해당 개념이 없으면 slide=0(없음)으로.",
        "- 여러 개념이 같은 슬라이드를 가리켜도 된다.",
        "",
        "개념 목록:",
    ]
    for k, c in enumerate(concepts, 1):
        lines.append(f"  개념 {k} [{c['heading']}]: {c['body']}")
    lines += [
        "",
        '반드시 JSON 배열로만 답하라. 각 원소: '
        '{"c": 개념번호, "slide": 슬라이드번호(없으면 0), '
        '"title": "읽은 슬라이드 제목", "reason": "짧은 근거"}',
    ]
    return "\n".join(lines)


def match_concepts(client, deck: list[dict], concepts: list[dict],
                   on_event=lambda m: None) -> list[dict]:
    contents: list = ["다음은 한 강의의 슬라이드 덱이다(번호·영상시각 순서대로):"]
    for s in deck:
        contents.append(f"슬라이드 {s['n']} (시각 {s['ts']}):")
        contents.append(types.Part.from_bytes(
            data=s["path"].read_bytes(), mime_type="image/jpeg"))
    contents.append(build_match_prompt(concepts))

    resp = client.models.generate_content(
        model=MODEL, contents=contents,
        config=types.GenerateContentConfig(response_mime_type="application/json"),
    )
    raw = (getattr(resp, "text", None) or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```[a-zA-Z]*\n?|\n?```$", "", raw).strip()
    try:
        data = json.loads(raw)
    except Exception as e:  # noqa: BLE001
        on_event(f"⚠️ JSON 파싱 실패: {str(e)[:100]}")
        return []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 매칭 결과 → 계획(plan) + 전방채움
# ---------------------------------------------------------------------------
def matched_plan(deck: list[dict], concepts: list[dict],
                 result: list[dict]) -> dict[int, int]:
    """Gemini 응답 → {concept_index(0base): slide_sec}. 매칭된 것만."""
    by_c = {int(r.get("c")): r for r in result
            if isinstance(r, dict) and "c" in r}
    sec_of = {s["n"]: s["sec"] for s in deck}
    plan: dict[int, int] = {}
    for k in range(1, len(concepts) + 1):
        slide = int((by_c.get(k, {}) or {}).get("slide", 0) or 0)
        if slide and slide in sec_of:
            plan[k - 1] = sec_of[slide]
    return plan


def forward_fill(concepts: list[dict],
                 matched: dict[int, int]) -> tuple[dict[int, int], set[int]]:
    """미매칭 개념을 가장 가까운 매칭 형제 슬라이드로 채운다.

    1차: 직전(앞) 매칭값으로 전방채움(보통 상위/형제 개념과 같은 슬라이드권).
    2차: 앞이 전혀 없는 선두 미매칭은 다음(뒤) 매칭값으로.
    반환: (전체 plan, 채워넣은 인덱스 집합).
    """
    n = len(concepts)
    plan = dict(matched)
    filled: set[int] = set()
    last = None
    for ci in range(n):
        if ci in matched:
            last = matched[ci]
        elif last is not None:
            plan[ci] = last
            filled.add(ci)
    nxt = None
    for ci in range(n - 1, -1, -1):
        if ci in matched:
            nxt = matched[ci]
        elif ci not in plan and nxt is not None:
            plan[ci] = nxt
            filled.add(ci)
    return plan, filled


# ---------------------------------------------------------------------------
# 노트 반영
# ---------------------------------------------------------------------------
def apply_to_note(md: str, concepts: list[dict], plan: dict[int, int],
                  course: str, seq: int) -> str:
    """plan: {concept_index(0base): slide_sec}. 마커 줄 + embed 줄 재작성."""
    lines = md.splitlines()
    for ci, c in enumerate(concepts):
        if ci not in plan:
            continue
        sec = plan[ci]
        ts = seconds_to_timestamp(sec)
        fn = capture_filename(course, seq, sec, DEFAULT_EXT)
        mi = c["marker_idx"]
        head = lines[mi].split("🎬")[0]
        lines[mi] = f"{head}🎬 [{ts}]"
        embed = f"![[{fn}]]"
        if c["embed_idx"] is not None:
            lines[c["embed_idx"]] = embed
        else:
            lines.insert(mi + 1, embed)
            for cc in concepts[ci + 1:]:
                cc["marker_idx"] += 1
                if cc["embed_idx"] is not None:
                    cc["embed_idx"] += 1
    text = "\n".join(lines)
    if md.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


def _write_preview(preview_dir: Path, deck: list[dict], concepts: list[dict],
                   plan: dict[int, int], filled: set[int]) -> None:
    """개념순 매칭 슬라이드를 모아 검증용 폴더로 복사."""
    if preview_dir.exists():
        shutil.rmtree(preview_dir)
    preview_dir.mkdir(parents=True, exist_ok=True)
    path_of = {s["sec"]: s["path"] for s in deck}
    for ci, c in enumerate(concepts):
        if ci not in plan:
            continue
        src = path_of.get(plan[ci])
        if not src:
            continue
        tag = "fill" if ci in filled else "ok"
        head = re.sub(r"[^\w가-힣]+", "_", c["heading"])[:20]
        shutil.copy2(src, preview_dir / f"{ci + 1:02d}_{tag}_{head}.jpg")


def _print_table(concepts: list[dict], deck: list[dict], plan: dict[int, int],
                 filled: set[int], result: list[dict],
                 emit=print) -> None:
    by_c = {int(r.get("c")): r for r in result
            if isinstance(r, dict) and "c" in r}
    n_of = {s["sec"]: s["n"] for s in deck}
    emit("\n=== 매칭 결과 ===")
    for ci, c in enumerate(concepts):
        head = c["heading"][:24]
        if ci not in plan:
            emit(f" {ci + 1:2d}. {head:24s} (매칭 없음·유지)")
            continue
        sec = plan[ci]
        cur = seconds_to_timestamp(c["cur_sec"])
        new = seconds_to_timestamp(sec)
        if ci in filled:
            kind = "⤵채움"
            extra = ""
        else:
            kind = "→" if sec != c["cur_sec"] else "="
            r = by_c.get(ci + 1, {})
            extra = f" (slide {n_of.get(sec)}: {str(r.get('title', ''))[:22]})"
        emit(f" {ci + 1:2d}. {head:24s} {cur} {kind} {new}{extra}")


# ---------------------------------------------------------------------------
# 매칭 + 반영 (덱이 준비된 뒤 공통)
# ---------------------------------------------------------------------------
def match_and_apply(client, deck: list[dict], note_path: Path,
                    course: str, seq: int, name: str, *,
                    apply: bool = False, fill_unmatched: bool = False,
                    result: list[dict] | None = None,
                    preview_dir: Path | None = None,
                    match_cache: Path | None = None,
                    on_event=lambda m: None) -> dict:
    """덱과 노트를 받아 개념 매칭→(옵션)노트 반영. 반환: 요약 dict."""
    md = note_path.read_text(encoding="utf-8")
    concepts = parse_concepts(md)
    on_event(f"덱 {len(deck)}장, 개념 {len(concepts)}개")

    if result is None:
        on_event("Gemini 매칭 중(멀티모달 1회)…")
        result = match_concepts(client, deck, concepts, on_event=on_event)
        if match_cache is not None and result:
            match_cache.write_text(
                json.dumps(result, ensure_ascii=False, indent=1),
                encoding="utf-8")

    matched = matched_plan(deck, concepts, result)
    if fill_unmatched:
        plan, filled = forward_fill(concepts, matched)
    else:
        plan, filled = dict(matched), set()

    _print_table(concepts, deck, plan, filled, result, emit=on_event)
    on_event(f"매칭 {len(matched)} + 전방채움 {len(filled)} "
             f"= {len(plan)}/{len(concepts)}개")

    if preview_dir is not None:
        _write_preview(preview_dir, deck, concepts, plan, filled)
        on_event(f"검증 미리보기: {preview_dir.name}")

    summary = {"deck": len(deck), "concepts": len(concepts),
               "matched": len(matched), "filled": len(filled),
               "applied": False}
    if not apply:
        on_event("[미리보기] 노트 미수정. 반영하려면 apply=True / --apply")
        return summary

    # 반영: 이미지 복사 → 노트 재작성 → 옛 캡처 정리 → timestamps 갱신
    out_dir = note_path.parent / "_captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    path_of = {s["sec"]: s["path"] for s in deck}
    for ci, sec in plan.items():
        src = path_of.get(sec)
        if src:
            shutil.copy2(src, out_dir / capture_filename(course, seq, sec,
                                                          DEFAULT_EXT))
    new_md = apply_to_note(md, concepts, plan, course, seq)
    new_md, scrubbed = scrub_empty_embeds(new_md, out_dir)
    if scrubbed:
        on_event(f"빈 슬라이드 임베드 {len(scrubbed)}개 청소")
    if new_md != md:
        note_path.write_text(new_md, encoding="utf-8")
        on_event(f"노트 반영: {note_path.name}")

    referenced = set(re.findall(r"!\[\[(.+?)\]\]", new_md))
    existing = [p.name for p in out_dir.glob(f"{sanitize(course)}_{seq}강_*")]
    pruned = 0
    for fn in orphan_captures(existing, referenced, course, seq):
        try:
            (out_dir / fn).unlink()
            pruned += 1
        except OSError:
            pass
    on_event(f"옛 캡처 정리: {pruned}개")

    ts_path = note_path.with_suffix(".timestamps.json")
    data = (json.loads(ts_path.read_text(encoding="utf-8"))
            if ts_path.exists() else
            {"subject": course, "seq": seq, "name": name})
    data["timestamps"] = extract_timestamps(new_md)
    ts_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    on_event(f"timestamps.json 갱신: {len(data['timestamps'])}개")
    summary["applied"] = True
    summary["pruned"] = pruned
    return summary


# ---------------------------------------------------------------------------
# 라이브러리 진입점 (main.py 단계 함수에서 호출)
# ---------------------------------------------------------------------------
def deck_capture_lecture(page, lec, course: str, seq: int, name: str, *,
                         cfg, client, note_path: Path,
                         thresh: int = DEFAULT_THRESH, crop: str = DEFAULT_CROP,
                         apply: bool = True,
                         on_event=lambda m: None) -> dict:
    """영상→덱→개념매칭→노트 반영(기본 apply=True). main.py capture 단계용.

    미매칭 개념은 노트 원본을 유지한다(match_and_apply 기본 fill_unmatched=False).
    """
    frames_dir = cfg.base_dir / f"frames_{seq}"
    deck = build_deck_live(page, lec, frames_dir, crop, thresh, on_event=on_event)
    if not deck:
        return {"ok": False, "error": "덱 추출 실패(클립/프레임 없음)"}
    summary = match_and_apply(
        client, deck, note_path, course, seq, name,
        apply=apply, on_event=on_event)
    summary["ok"] = True
    return summary


# ---------------------------------------------------------------------------
# CLI (단일 강의 검증/수동 실행)
# ---------------------------------------------------------------------------
def _find_note(cfg, course: str, seq: int) -> Path | None:
    matches = sorted(cfg.summary_dir.glob(f"{sanitize(course)} {seq}강 - *.md"))
    return matches[0] if matches else None


def _name_from_note(note_path: Path, course: str, seq: int) -> str:
    m = re.search(rf"{re.escape(sanitize(course))} {seq}강 - (.+)\.md$",
                  note_path.name)
    return m.group(1) if m else ""


def main() -> None:
    from config import load_config

    ap = argparse.ArgumentParser(description="범용 슬라이드 덱 매칭 캡처")
    ap.add_argument("--course", required=True, help="과목명(부분일치)")
    ap.add_argument("--seq", type=int, required=True, help="차시 번호")
    ap.add_argument("--apply", action="store_true", help="노트에 실제 반영")
    ap.add_argument("--thresh", type=int, default=DEFAULT_THRESH)
    ap.add_argument("--crop", default=DEFAULT_CROP)
    ap.add_argument("--fill", action="store_true",
                    help="미매칭 개념 전방채움 활성화(기본=원본 유지)")
    ap.add_argument("--reuse-frames", action="store_true",
                    help="frames_{seq}/ 재사용(영상 재추출·로그인 생략)")
    ap.add_argument("--reuse-match", action="store_true",
                    help="deck_{seq}_match.json 재사용(Gemini 재호출 생략)")
    ap.add_argument("--keep-empty", action="store_true",
                    help="빈 표지 슬라이드도 덱에 남김(기본=제외)")
    args = ap.parse_args()
    empty_thresh = 0 if args.keep_empty else DEFAULT_EMPTY_THRESH

    cfg = load_config()
    note_path = _find_note(cfg, args.course, args.seq)
    if not note_path:
        print(f"❌ 노트 없음: {args.course} {args.seq}강 (먼저 요약 필요)",
              flush=True)
        return
    name = _name_from_note(note_path, args.course, args.seq)
    frames_dir = cfg.base_dir / f"frames_{args.seq}"
    match_cache = cfg.base_dir / f"deck_{args.seq}_match.json"
    preview_dir = cfg.base_dir / f"match_preview_{args.seq}"

    def emit(m: str) -> None:
        print(f"  {m}", flush=True)

    # 덱 확보 (재사용 or 라이브 추출)
    if args.reuse_frames:
        if not list(frames_dir.glob("f_*.jpg")):
            print(f"❌ frames 없음: {frames_dir} (먼저 추출 필요)", flush=True)
            return
        emit(f"frames 재사용: {frames_dir.name}")
        deck = dedup_frames(frames_dir, args.thresh)
        deck = drop_empty_slides(deck, empty_thresh, on_event=emit)
        emit(f"덱 {len(deck)}장 (thresh={args.thresh})")
    else:
        deck = _build_deck_via_browser(cfg, args, frames_dir, emit, empty_thresh)
        if deck is None:
            return
    if not deck:
        print("❌ 덱이 비었음", flush=True)
        return

    # 매칭 캐시 재사용?
    cached = None
    if args.reuse_match and match_cache.exists():
        cached = json.loads(match_cache.read_text(encoding="utf-8"))
        emit(f"매칭 캐시 재사용: {match_cache.name}")

    from google import genai
    client = None if cached is not None else genai.Client(
        api_key=cfg.gemini_api_key)

    summary = match_and_apply(
        client, deck, note_path, args.course, args.seq, name,
        apply=args.apply, fill_unmatched=args.fill,
        result=cached, preview_dir=preview_dir, match_cache=match_cache,
        on_event=emit,
    )
    print(f"\n=== 요약 === {summary}", flush=True)


def _build_deck_via_browser(cfg, args, frames_dir: Path, emit,
                            empty_thresh: float = DEFAULT_EMPTY_THRESH
                            ) -> list[dict] | None:
    """CLI 라이브 모드: 자체 브라우저 컨텍스트로 덱 추출."""
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from discover import fetch_lectures, list_courses
    from recon import launch_context

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        course = next((c for c in list_courses(page)
                       if args.course in c.name), None)
        if not course:
            print(f"❌ 과목 없음: {args.course}", flush=True)
            ctx.close()
            return None
        lec = next((l for l in fetch_lectures(page, course)
                    if l.seq == args.seq), None)
        if not lec:
            print(f"❌ 차시 없음: {args.course} {args.seq}강", flush=True)
            ctx.close()
            return None
        emit(f"대상: {course.name} {lec.seq}강 '{lec.name}'")
        deck = build_deck_live(page, lec, frames_dir, args.crop, args.thresh,
                               empty_thresh=empty_thresh, on_event=emit)
        ctx.close()
    return deck


if __name__ == "__main__":
    main()
