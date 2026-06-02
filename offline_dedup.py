"""[offline] frames_14(초단위 인덱스)에서 dedup 재튜닝 — 라이브 불필요.

빌드 누락(점진적 bullet build) 보완을 위해 thresh/해시크기를 바꿔가며
덱 커버리지(특히 tail) 확인. deck_14_t{thresh}s{size}/ 에 대표프레임 저장.

실행: .venv/Scripts/python.exe -u offline_dedup.py --thresh 20 --size 8
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image

from summarize import seconds_to_timestamp


def dhash(path: Path, size: int) -> int:
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


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--frames", default="frames_14")
    ap.add_argument("--thresh", type=int, default=20)
    ap.add_argument("--size", type=int, default=8)
    ap.add_argument("--tail", type=int, default=4000, help="이 초 이상만 상세출력")
    args = ap.parse_args()

    frames = sorted(Path(args.frames).glob("f_*.jpg"))
    if not frames:
        print(f"❌ 프레임 없음: {args.frames}")
        return
    print(f"프레임 {len(frames)}장, dHash size={args.size} thresh={args.thresh}",
          flush=True)
    hashes = [dhash(f, args.size) for f in frames]

    deck = [0]
    ref = hashes[0]
    for i in range(1, len(hashes)):
        if hamming(hashes[i], ref) > args.thresh:
            deck.append(i)
            ref = hashes[i]

    out = Path(f"deck_14_t{args.thresh}s{args.size}")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True, exist_ok=True)
    for n, idx in enumerate(deck, 1):
        ts = seconds_to_timestamp(idx).replace(":", "-")
        shutil.copy2(frames[idx], out / f"slide_{n:03d}__{ts}.jpg")

    print(f"=== 슬라이드 {len(deck)}장 → {out} ===", flush=True)
    tail = [idx for idx in deck if idx >= args.tail]
    print(f"tail(≥{args.tail}s) 슬라이드 {len(tail)}장:", flush=True)
    for idx in tail:
        print(f"   {seconds_to_timestamp(idx)} ({idx}s)", flush=True)


if __name__ == "__main__":
    main()
