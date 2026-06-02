"""[probe v2] 슬라이드 덱 추출 개선 — 데이터베이스시스템 14강.

v1 문제: scene@0.3 + 발표자/자막 미제거 → 본문 슬라이드 대량 누락(18~23분 공백),
전환 애니메이션/발표자단독 프레임 오검출.

v2 개선:
  - crop 으로 '슬라이드 본문 영역'만 남김(발표자=우측, 자막=하단, 헤더=상단 제거)
    → 발표자 움직임·실시간 자막 변화가 검출을 오염시키지 않음.
  - scene 임계값 대신 mpdecimate(픽셀 차분 중복제거) → 임계값 튜닝 불필요,
    슬라이드가 바뀔 때만 프레임 보존.
  - -skip_frame nokey 로 키프레임만 디코드(빠름).

크롭 썸네일을 probe_deck2_14/ 에 저장(내가 눈으로 커버리지 확인). Gemini 비용 0.
⚠️ 영상 URL(JWT) 미출력. 실행: .venv/Scripts/python.exe -u probe_deck2_14.py
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from capture import FFMPEG, collect_clips, probe_duration, seconds_to_timestamp
from config import load_config
from discover import fetch_lectures, list_courses
from recon import launch_context
from watch import open_player

COURSE = "데이터베이스시스템"
SEQ = 14

# 1280x720 기준 슬라이드 본문 영역: x[40..920], y[80..550]
#  → 발표자(우측 ~930+), 하단 자막(y~560+), 상단 헤더(y<80) 제외
DEFAULT_CROP = "880:470:40:80"
_SHOWINFO_RE = re.compile(r"pts_time:([0-9.]+)")


def deck_scan(url: str, out_dir: Path, crop: str = DEFAULT_CROP,
              timeout: float = 1200.0) -> list[float]:
    """키프레임만 디코드 → 슬라이드 본문 crop → mpdecimate 중복제거 → 저장.

    return: 저장된 각 (구분되는)슬라이드 프레임의 pts_time(초) 리스트.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    vf = f"crop={crop},mpdecimate,showinfo"
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "info",
        "-skip_frame", "nokey",
        "-i", str(url),
        "-vf", vf,
        "-vsync", "vfr",
        "-q:v", "3",
        str(out_dir / "slide_%04d.jpg"),
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    dt = time.time() - t0
    # mpdecimate 가 통과시킨 프레임만 showinfo 에 찍힘(=저장된 슬라이드)
    # showinfo 는 drop 안 된 프레임에 대해서만 출력되므로 pts_time 순서=파일 순서
    times = [float(m) for m in _SHOWINFO_RE.findall(r.stderr or "")]
    print(f"  스캔 완료: {dt:.0f}s, 슬라이드 {len(times)}장 (rc={r.returncode})",
          flush=True)
    if r.returncode != 0 and not times:
        print("  stderr(tail):", (r.stderr or "")[-500:], flush=True)
    return times


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--crop", default=DEFAULT_CROP)
    args = ap.parse_args()

    cfg = load_config()
    out_dir = cfg.base_dir / "probe_deck2_14"

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == SEQ)
        print(f"대상: {COURSE} {SEQ}강 '{lec.name}'", flush=True)

        popup = open_player(page, lec)
        try:
            clips = collect_clips(popup)
            for c in clips:
                c["duration"] = probe_duration(c.get("hlsUrl") or "")
            valid = [c for c in clips
                     if isinstance(c.get("duration"), (int, float))
                     and c["duration"] > 0]
            main_clip = max(valid, key=lambda c: c["duration"])
            print(f"▶ 스캔: [{main_clip['idx']}] {main_clip.get('title')} "
                  f"({main_clip['duration']:.0f}s), crop={args.crop}", flush=True)
            times = deck_scan(main_clip["hlsUrl"], out_dir, args.crop)
        finally:
            try:
                popup.close()
            except Exception:
                pass
        ctx.close()

    print(f"\n=== 슬라이드 {len(times)}장 ===", flush=True)
    for i, ts in enumerate(times, 1):
        print(f"  slide_{i:04d}.jpg  @ {seconds_to_timestamp(int(ts))} "
              f"({ts:.1f}s)", flush=True)
    print(f"\n덱 저장: {out_dir}", flush=True)
    if len(times) > 1:
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        print(f"슬라이드 간격: 평균 {sum(gaps) / len(gaps):.0f}s, "
              f"최소 {min(gaps):.0f}s, 최대 {max(gaps):.0f}s", flush=True)
        # 2분 넘는 공백(누락 의심) 구간 표시
        big = [(times[i], times[i + 1]) for i in range(len(gaps))
               if gaps[i] > 150]
        if big:
            print("⚠️ 150s 초과 공백(누락 의심):", flush=True)
            for a, b in big:
                print(f"   {seconds_to_timestamp(int(a))} → "
                      f"{seconds_to_timestamp(int(b))} ({b - a:.0f}s)", flush=True)


if __name__ == "__main__":
    main()
