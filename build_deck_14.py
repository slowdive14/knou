"""[deck] 프로덕션 슬라이드 덱 빌더 — DB14 검증용.

흐름:
  1) 로그인→플레이어→가장 긴 클립(학습하기) HLS URL 확보
  2) ffmpeg: 키프레임만 디코드 + 슬라이드 본문 crop + fps=1
     → frames_14/f_%06d.jpg (f_000001 = 0초, f_i = (i-1)초)  ← 타임스탬프 1:1
  3) dHash dedup(thresh) → '구분되는 슬라이드' 경계 검출
  4) 각 슬라이드 대표(첫) 프레임을 deck_14/ 에 slide_NNN__HH-MM-SS.jpg 로 저장
  5) 덱 목록(시각) + 간격 출력

frames_14/ 는 보존(오프라인 re-dedup 가능). ⚠️ HLS URL(JWT) 미출력.
실행: .venv/Scripts/python.exe -u build_deck_14.py [--thresh 28]
"""
from __future__ import annotations

import argparse
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

from PIL import Image
from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from capture import FFMPEG, collect_clips, probe_duration, seconds_to_timestamp
from config import load_config
from discover import fetch_lectures, list_courses
from recon import launch_context
from watch import open_player

COURSE = "데이터베이스시스템"
SEQ = 14
DEFAULT_CROP = "880:470:40:80"
DEFAULT_THRESH = 28


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
                   timeout: float = 1800.0) -> int:
    """키프레임 디코드 + crop + fps=1 → 초단위 인덱스 프레임. 반환=프레임 수."""
    frames_dir.mkdir(parents=True, exist_ok=True)
    for old in frames_dir.glob("f_*.jpg"):
        old.unlink()
    vf = f"crop={crop},fps=1"
    cmd = [
        FFMPEG, "-hide_banner", "-loglevel", "error",
        "-skip_frame", "nokey",
        "-i", str(url),
        "-vf", vf,
        "-q:v", "3",
        str(frames_dir / "f_%06d.jpg"),
    ]
    t0 = time.time()
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    dt = time.time() - t0
    n = len(list(frames_dir.glob("f_*.jpg")))
    print(f"  추출 완료: {dt:.0f}s, 프레임 {n}장 (rc={r.returncode})", flush=True)
    if r.returncode != 0 and n == 0:
        print("  stderr(tail):", (r.stderr or "")[-500:], flush=True)
    return n


def dedup(frames_dir: Path, thresh: int) -> list[tuple[int, Path]]:
    """frames_dir(초단위 인덱스) → [(초, 대표프레임경로)]. 첫 프레임 인덱스=초."""
    frames = sorted(frames_dir.glob("f_*.jpg"))
    if not frames:
        return []
    print(f"  dHash {len(frames)}장 계산…", flush=True)
    hashes = [dhash(f) for f in frames]
    deck: list[tuple[int, Path]] = [(0, frames[0])]
    ref = hashes[0]
    for i in range(1, len(hashes)):
        if hamming(hashes[i], ref) > thresh:
            deck.append((i, frames[i]))   # 인덱스 i == i초
            ref = hashes[i]
    return deck


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thresh", type=int, default=DEFAULT_THRESH)
    ap.add_argument("--crop", default=DEFAULT_CROP)
    args = ap.parse_args()

    cfg = load_config()
    frames_dir = cfg.base_dir / "frames_14"
    deck_dir = cfg.base_dir / "deck_14"

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
            print(f"▶ 추출: [{main_clip['idx']}] {main_clip.get('title')} "
                  f"({main_clip['duration']:.0f}s), crop={args.crop}", flush=True)
            extract_frames(main_clip["hlsUrl"], frames_dir, args.crop)
        finally:
            try:
                popup.close()
            except Exception:
                pass
        ctx.close()

    deck = dedup(frames_dir, args.thresh)

    # 대표 프레임 저장
    if deck_dir.exists():
        shutil.rmtree(deck_dir)
    deck_dir.mkdir(parents=True, exist_ok=True)
    for n, (sec, src) in enumerate(deck, 1):
        ts = seconds_to_timestamp(sec).replace(":", "-")
        shutil.copy2(src, deck_dir / f"slide_{n:03d}__{ts}.jpg")

    print(f"\n=== thresh={args.thresh} → 슬라이드 {len(deck)}장 ===", flush=True)
    for n, (sec, _) in enumerate(deck, 1):
        print(f"  slide_{n:03d}  @ {seconds_to_timestamp(sec)} ({sec}s)", flush=True)
    print(f"\n덱 저장: {deck_dir}\n프레임 보존: {frames_dir}", flush=True)
    if len(deck) > 1:
        gaps = [deck[i + 1][0] - deck[i][0] for i in range(len(deck) - 1)]
        print(f"슬라이드 간격: 평균 {sum(gaps)/len(gaps):.0f}s, "
              f"최소 {min(gaps)}s, 최대 {max(gaps)}s", flush=True)


if __name__ == "__main__":
    main()
