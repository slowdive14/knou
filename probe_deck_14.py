"""[probe] 슬라이드 덱 추출 검증 — 데이터베이스시스템 14강.

목적: capture.py 재설계(슬라이드 덱 매칭)에 앞서 '영상에서 실제 슬라이드 전부를
ffmpeg 장면전환 검출로 깨끗하게 뽑을 수 있는가 / 몇 장인가'를 Gemini 비용 없이 검증.

흐름: 로그인 → DB14 플레이어 → 클립 조회 → 가장 긴 클립(학습하기) 1회 스캔
(-skip_frame nokey 로 키프레임만 디코드 → scene>thr 프레임만 저장) → 덱 프레임 +
각 슬라이드 pts_time 출력. 덱은 probe_deck_14/ 에 저장(내가 눈으로 확인).

⚠️ 영상 URL(JWT 토큰)은 절대 출력하지 않는다.
실행: .venv/Scripts/python.exe -u probe_deck_14.py [--threshold 0.3]
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

_SHOWINFO_RE = re.compile(r"pts_time:([0-9.]+)")


def scene_scan(url: str, out_dir: Path, threshold: float = 0.3,
               timeout: float = 900.0) -> list[float]:
    """키프레임만 디코드하며 scene>threshold 인 프레임을 out_dir 에 저장.

    return: 저장된 각 프레임의 pts_time(초) 리스트(시간순). 첫 키프레임(n=0)도 포함.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    # select: 장면전환(scene>thr) 또는 맨 첫 프레임(eq(n,0)) → showinfo 로 pts 로깅
    vf = f"select=gt(scene\\,{threshold})+eq(n\\,0),showinfo"
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
    # showinfo 는 stderr 로 프레임별 정보 출력 → pts_time 순서대로 추출
    times = [float(m) for m in _SHOWINFO_RE.findall(r.stderr or "")]
    print(f"  스캔 완료: {dt:.0f}s, 저장 프레임 {len(times)}장 "
          f"(rc={r.returncode})", flush=True)
    if r.returncode != 0 and not times:
        print("  stderr(tail):", (r.stderr or "")[-400:], flush=True)
    return times


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.3)
    args = ap.parse_args()

    cfg = load_config()
    out_dir = cfg.base_dir / "probe_deck_14"

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
            print(f"클립 {len(clips)}개:", flush=True)
            for c in clips:
                print(f"  [{c['idx']}] {c.get('title')} "
                      f"dur={c.get('duration')}", flush=True)
            valid = [c for c in clips
                     if isinstance(c.get("duration"), (int, float))
                     and c["duration"] > 0]
            if not valid:
                print("❌ 유효 클립 없음", flush=True)
                return
            main_clip = max(valid, key=lambda c: c["duration"])
            print(f"\n▶ 스캔 클립: [{main_clip['idx']}] {main_clip.get('title')} "
                  f"({main_clip['duration']:.0f}s), threshold={args.threshold}",
                  flush=True)

            times = scene_scan(main_clip["hlsUrl"], out_dir, args.threshold)
        finally:
            try:
                popup.close()
            except Exception:
                pass
        ctx.close()

    # 결과: 슬라이드별 추정 시각(시간순)
    print(f"\n=== 추출된 슬라이드 {len(times)}장 ===", flush=True)
    for i, ts in enumerate(times, 1):
        print(f"  slide_{i:04d}.jpg  @ {seconds_to_timestamp(int(ts))} "
              f"({ts:.1f}s)", flush=True)
    print(f"\n덱 저장 폴더: {out_dir}", flush=True)
    if times:
        gaps = [times[i + 1] - times[i] for i in range(len(times) - 1)]
        if gaps:
            print(f"슬라이드 간격: 평균 {sum(gaps) / len(gaps):.0f}s, "
                  f"최소 {min(gaps):.0f}s, 최대 {max(gaps):.0f}s", flush=True)


if __name__ == "__main__":
    main()
