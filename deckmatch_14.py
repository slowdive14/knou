"""[deckmatch] 개념→슬라이드 콘텐츠 매칭 — DB14 검증.

슬라이드 덱(deck_14/, 실제 시각 포함)과 노트 개념을 Gemini가 1회 멀티모달 호출로
콘텐츠 매칭 → 각 개념에 '실제로 그 내용이 보이는 슬라이드'를 배정.

흐름:
  1) deck_14/slide_NNN__HH-MM-SS.jpg 로드(번호·시각·이미지)
  2) 노트에서 🎬 마커별 '개념 블록'(상위 heading + 본문 + 현재 마커시각 + embed줄) 파싱
  3) Gemini 멀티모달 1회: 덱 이미지(시각 라벨) + 개념 목록 → 개념별 best 슬라이드 JSON
  4) 매핑 표 출력 + 검증용 미리보기(개념순 매칭 슬라이드 몽타주)
  5) --apply 시에만: 매칭 슬라이드 이미지를 볼트 _captures 로 복사 +
     노트 마커/embed 를 슬라이드 실제 시각으로 재작성 + timestamps.json 갱신

⚠️ GEMINI_API_KEY/HLS URL 미출력. 노트 수정은 --apply 플래그가 있을 때만.
실행: .venv/Scripts/python.exe -u deckmatch_14.py            # 미리보기(매칭만)
      .venv/Scripts/python.exe -u deckmatch_14.py --apply    # 노트 반영
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from google import genai
from google.genai import types

from capture import DEFAULT_EXT, capture_filename, orphan_captures, _EMBED_LINE_RE
from config import load_config
from download import sanitize
from summarize import (
    _TS_RE,
    extract_timestamps,
    seconds_to_timestamp,
    timestamp_to_seconds,
)

COURSE = "데이터베이스시스템"
SEQ = 14
NAME = "동시성 제어"
MODEL = "gemini-2.5-flash"
_SLIDE_FN_RE = re.compile(r"slide_(\d+)__(\d{2})-(\d{2})-(\d{2})\.jpg$")


# ---------------------------------------------------------------------------
# 덱 / 노트 파싱
# ---------------------------------------------------------------------------
def load_deck(deck_dir: Path) -> list[dict]:
    """deck_dir → [{n, sec, ts, path}] (번호순)."""
    out = []
    for p in sorted(deck_dir.glob("slide_*.jpg")):
        m = _SLIDE_FN_RE.search(p.name)
        if not m:
            continue
        n = int(m.group(1))
        sec = int(m.group(2)) * 3600 + int(m.group(3)) * 60 + int(m.group(4))
        out.append({"n": n, "sec": sec, "ts": seconds_to_timestamp(sec), "path": p})
    return out


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
# Gemini 매칭(멀티모달 1회)
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


def match_concepts(client, deck: list[dict], concepts: list[dict]) -> list[dict]:
    contents: list = [
        "다음은 한 강의의 슬라이드 덱이다(번호·영상시각 순서대로):",
    ]
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
    except Exception as e:
        print("⚠️ JSON 파싱 실패:", str(e)[:100], flush=True)
        print(raw[:800], flush=True)
        return []
    return data if isinstance(data, list) else []


# ---------------------------------------------------------------------------
# 노트 반영
# ---------------------------------------------------------------------------
def apply_to_note(md: str, concepts: list[dict], plan: dict) -> str:
    """plan: {concept_index(0base): slide_sec}. 마커 줄 + embed 줄 재작성."""
    lines = md.splitlines()
    for ci, c in enumerate(concepts):
        if ci not in plan:
            continue
        sec = plan[ci]
        ts = seconds_to_timestamp(sec)
        fn = capture_filename(COURSE, SEQ, sec, DEFAULT_EXT)
        mi = c["marker_idx"]
        # 마커 줄: 첫 🎬 앞부분 유지 + 단일 교정 마커
        head = lines[mi].split("🎬")[0]
        lines[mi] = f"{head}🎬 [{ts}]"
        # embed 줄 교체/삽입
        embed = f"![[{fn}]]"
        if c["embed_idx"] is not None:
            lines[c["embed_idx"]] = embed
        else:
            lines.insert(mi + 1, embed)
            # 삽입으로 이후 인덱스 +1 → 같은 노트 재파싱 회피 위해 후속 보정
            for cc in concepts[ci + 1:]:
                cc["marker_idx"] += 1
                if cc["embed_idx"] is not None:
                    cc["embed_idx"] += 1
    text = "\n".join(lines)
    if md.endswith("\n") and not text.endswith("\n"):
        text += "\n"
    return text


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="노트에 실제 반영")
    ap.add_argument("--deck", default="deck_14", help="덱 폴더명")
    args = ap.parse_args()

    cfg = load_config()
    deck_dir = cfg.base_dir / args.deck
    note_path = (cfg.summary_dir /
                 f"{COURSE} {SEQ}강 - {NAME}.md")

    deck = load_deck(deck_dir)
    md = note_path.read_text(encoding="utf-8")
    concepts = parse_concepts(md)
    print(f"덱 {len(deck)}장, 개념 {len(concepts)}개", flush=True)

    client = genai.Client(api_key=cfg.gemini_api_key)
    print("Gemini 매칭 중(멀티모달 1회)…", flush=True)
    result = match_concepts(client, deck, concepts)
    by_c = {int(r.get("c")): r for r in result if isinstance(r, dict) and "c" in r}

    sec_of = {s["n"]: s["sec"] for s in deck}
    plan: dict[int, int] = {}
    print("\n=== 매칭 결과 ===", flush=True)
    for k, c in enumerate(concepts, 1):
        r = by_c.get(k, {})
        slide = int(r.get("slide", 0) or 0)
        if slide and slide in sec_of:
            sec = sec_of[slide]
            plan[k - 1] = sec
            cur = seconds_to_timestamp(c["cur_sec"])
            new = seconds_to_timestamp(sec)
            mark = "→" if sec != c["cur_sec"] else "="
            print(f" {k:2d}. {c['heading'][:24]:24s} {cur} {mark} {new} "
                  f"(slide {slide}: {str(r.get('title',''))[:24]})", flush=True)
        else:
            print(f" {k:2d}. {c['heading'][:24]:24s} (매칭 없음)", flush=True)

    # 검증용 미리보기: 개념순 매칭 슬라이드 모음
    prev = cfg.base_dir / "match_preview_14"
    if prev.exists():
        shutil.rmtree(prev)
    prev.mkdir(parents=True, exist_ok=True)
    path_of = {s["n"]: s["path"] for s in deck}
    sec_to_n = {s["sec"]: s["n"] for s in deck}
    for k, c in enumerate(concepts, 1):
        if (k - 1) in plan:
            n = sec_to_n[plan[k - 1]]
            head = re.sub(r"[^\w가-힣]+", "_", c["heading"])[:20]
            shutil.copy2(path_of[n], prev / f"{k:02d}_{head}__s{n:03d}.jpg")
    print(f"\n검증 미리보기: {prev}  (개념순 매칭 슬라이드)", flush=True)
    print(f"매칭 {len(plan)}/{len(concepts)}개", flush=True)

    if not args.apply:
        print("\n[미리보기 모드] 노트 미수정. 반영하려면 --apply", flush=True)
        return

    # 반영
    out_dir = note_path.parent / "_captures"
    out_dir.mkdir(parents=True, exist_ok=True)
    for ci, sec in plan.items():
        n = sec_to_n[sec]
        fn = capture_filename(COURSE, SEQ, sec, DEFAULT_EXT)
        shutil.copy2(path_of[n], out_dir / fn)
    new_md = apply_to_note(md, concepts, plan)
    if new_md != md:
        note_path.write_text(new_md, encoding="utf-8")
        print(f"노트 반영: {note_path.name}", flush=True)
    # 더 이상 참조 안 되는 옛 캡처(틀린 이미지) 정리
    referenced = set(re.findall(r"!\[\[(.+?)\]\]", new_md))
    existing = [p.name for p in out_dir.glob(f"{sanitize(COURSE)}_{SEQ}강_*")]
    pruned = 0
    for fn in orphan_captures(existing, referenced, COURSE, SEQ):
        try:
            (out_dir / fn).unlink()
            pruned += 1
        except OSError:
            pass
    print(f"옛 캡처 정리: {pruned}개", flush=True)
    # timestamps.json 갱신
    ts_path = note_path.with_suffix(".timestamps.json")
    data = (json.loads(ts_path.read_text(encoding="utf-8"))
            if ts_path.exists() else
            {"subject": COURSE, "seq": SEQ, "name": NAME})
    data["timestamps"] = extract_timestamps(new_md)
    ts_path.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
    print(f"timestamps.json 갱신: {len(data['timestamps'])}개", flush=True)


if __name__ == "__main__":
    main()
