"""[probe] 오프라인 슬라이드 dedup 검증 — 이미 저장된 probe_deck2_14/ 프레임 대상.

목적: 라이브 재실행/Gemini 비용 없이, 4443장의 dense 크롭 프레임을
perceptual hash(dHash)로 '구분되는 슬라이드'로 묶을 수 있는지 검증.
프레임은 시간순(slide_0001..slide_4443)이므로 순서만으로 경계 검출 가능.

알고리즘:
  - 각 프레임 dHash(64bit) 계산
  - 직전 '대표 프레임' 해시와 hamming 거리 > THRESH 이면 새 슬라이드 경계
  - 각 슬라이드의 첫 프레임을 deck 폴더로 복사(눈으로 커버리지/정확도 확인)

실행: .venv/Scripts/python.exe -u probe_dedup_14.py [--thresh 10] [--src probe_deck2_14]
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from PIL import Image


def dhash(path: Path, size: int = 8) -> int:
    """수평 인접 픽셀 밝기 비교 dHash (size*size bit)."""
    img = Image.open(path).convert("L").resize((size + 1, size), Image.BILINEAR)
    px = list(img.getdata())
    bits = 0
    w = size + 1
    for row in range(size):
        base = row * w
        for col in range(size):
            bit = 1 if px[base + col] > px[base + col + 1] else 0
            bits = (bits << 1) | bit
    return bits


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--thresh", type=int, default=10,
                    help="hamming 거리 임계값(클수록 덜 쪼갬)")
    ap.add_argument("--src", default="probe_deck2_14")
    args = ap.parse_args()

    src = Path(args.src)
    frames = sorted(src.glob("slide_*.jpg"))
    if not frames:
        print(f"❌ 프레임 없음: {src}", flush=True)
        return
    print(f"프레임 {len(frames)}장 로드 → dHash 계산…", flush=True)

    hashes = [dhash(f) for f in frames]

    # 경계 검출: 직전 대표 해시와 거리 > thresh 이면 새 슬라이드
    boundaries = [0]          # 슬라이드 시작 프레임 인덱스
    ref = hashes[0]
    for i in range(1, len(hashes)):
        if hamming(hashes[i], ref) > args.thresh:
            boundaries.append(i)
            ref = hashes[i]

    # 각 슬라이드 run-length
    runs = []
    for k, start in enumerate(boundaries):
        end = boundaries[k + 1] if k + 1 < len(boundaries) else len(frames)
        runs.append((start, end - start))

    print(f"\n=== thresh={args.thresh} → 슬라이드 {len(boundaries)}장 ===",
          flush=True)

    # 대표(첫) 프레임을 deck 폴더로 복사
    deck = Path(f"deck_dedup_{args.thresh}")
    if deck.exists():
        shutil.rmtree(deck)
    deck.mkdir(parents=True, exist_ok=True)
    for k, (start, length) in enumerate(runs, 1):
        srcf = frames[start]
        dstf = deck / f"deck_{k:03d}__src{start + 1:04d}__len{length}.jpg"
        shutil.copy2(srcf, dstf)

    # run-length 분포(짧은 run=전환 잔상/노이즈 의심)
    lengths = [r[1] for r in runs]
    short = sum(1 for x in lengths if x <= 2)
    print(f"대표 프레임 복사: {deck}", flush=True)
    print(f"run-length: 평균 {sum(lengths)/len(lengths):.1f}, "
          f"최소 {min(lengths)}, 최대 {max(lengths)}, "
          f"짧은(≤2프레임) {short}장", flush=True)
    print(f"(짧은 run 많으면 전환 애니메이션/노이즈로 과분할 → thresh ↑ 필요)",
          flush=True)


if __name__ == "__main__":
    main()
