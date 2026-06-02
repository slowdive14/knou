"""읽기 전용 진단: 이산수학 13강의 영상 클립 구성 vs MP3 길이 vs 타임스탬프.

캡처/Gemini 호출 없음. 플레이어를 열어 클립 목록·각 길이를 ffprobe로 측정하고,
MP3 길이·요약 타임스탬프와 대조해 'MP3=단일클립'인지 'MP3=다중클립 연결'인지 판단.

   .venv/Scripts/python.exe -u probe_clips_13.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from capture import probe_duration, resolve_clips
from config import load_config
from discover import fetch_lectures, list_courses
from recon import launch_context
from summarize import note_filename, seconds_to_timestamp

TARGET_COURSE = "이산수학"
TARGET_SEQ = 13
TARGET_NAME = "정수론"


def main() -> None:
    cfg = load_config()
    mp3 = cfg.downloads_dir / "이산수학_13강.mp3"
    note = cfg.summary_dir / note_filename(TARGET_COURSE, TARGET_SEQ, TARGET_NAME)
    ts_json = note.with_suffix(".timestamps.json")

    mp3_dur = probe_duration(str(mp3)) if mp3.exists() else None
    print(f"MP3 길이: {mp3_dur}s  ({mp3})", flush=True)

    ts = []
    if ts_json.exists():
        ts = json.loads(ts_json.read_text(encoding="utf-8")).get("timestamps", [])
    print(f"타임스탬프: {len(ts)}개 (저장된 seconds 기준)", flush=True)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ)

        clips = resolve_clips(page, lec, with_duration=True,
                              on_event=lambda m: None)
        print(f"\n=== 클립 {len(clips)}개 ===", flush=True)
        cum = 0.0
        bounds = []  # (start, end, idx, title)
        for c in clips:
            d = c.get("duration")
            start = cum
            if isinstance(d, (int, float)):
                cum += d
            end = cum
            bounds.append((start, end, c.get("idx"), c.get("title"), d))
            print(f"  [{c.get('idx')}] {c.get('title')!r:24} "
                  f"dur={d}  누적 {start:.0f}~{end:.0f}s", flush=True)

        total = cum
        print(f"\n클립 길이 합계 = {total:.1f}s / MP3 = {mp3_dur}s "
              f"(차이 {abs(total - (mp3_dur or 0)):.1f}s)", flush=True)

        # 가장 가까운 단일 클립
        valid = [b for b in bounds if isinstance(b[4], (int, float))]
        if valid and mp3_dur:
            closest = min(valid, key=lambda b: abs(b[4] - mp3_dur))
            print(f"단일 최근접 클립: [{closest[2]}] {closest[3]!r} "
                  f"({closest[4]:.0f}s, 차이 {abs(closest[4]-mp3_dur):.0f}s)",
                  flush=True)

        def map_clip(sec):
            for (s, e, idx, title, d) in bounds:
                if s <= sec < e:
                    return f"클립[{idx}] {title!r} +{sec - s:.0f}s"
            return "⚠️ 범위초과"

        def corrected(sec):
            """raw seconds 가 전체길이 초과면 'h:m 를 mm:ss 로' 재해석(필드 시프트)."""
            if mp3_dur and sec > mp3_dur:
                h = sec // 3600
                m = (sec % 3600) // 60
                return h * 60 + m   # 09:21:00(33660) → 9*60+21 = 561
            return sec

        # 타임스탬프(저장된 seconds)가 '연결 타임라인'에서 어느 클립에 떨어지는지
        print(f"\n=== 타임스탬프 → 클립 매핑 (raw / 교정후) ===", flush=True)
        for t in ts:
            sec = int(t["seconds"])
            cor = corrected(sec)
            note_c = "" if cor == sec else f"  ⇒ 교정 {seconds_to_timestamp(cor)}({cor}s) → {map_clip(cor)}"
            print(f"  raw {seconds_to_timestamp(sec):>10} ({sec}s) → {map_clip(sec)}{note_c}",
                  flush=True)

        ctx.close()


if __name__ == "__main__":
    main()
