"""폴더의 이미지들을 한 장의 contact-sheet(격자)로 합쳐 눈으로 확인.

실행: .venv/Scripts/python.exe montage.py <folder> [--cols 6] [--cell 240] [--out montage.png]
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder")
    ap.add_argument("--cols", type=int, default=6)
    ap.add_argument("--cell", type=int, default=240)
    ap.add_argument("--out", default=None)
    args = ap.parse_args()

    folder = Path(args.folder)
    files = sorted(folder.glob("*.jpg")) + sorted(folder.glob("*.png"))
    if not files:
        print(f"❌ 이미지 없음: {folder}")
        return

    cols = args.cols
    rows = (len(files) + cols - 1) // cols
    cw = args.cell
    ch = int(cw * 0.55)            # 슬라이드 본문 가로:세로 ≈ 880:470
    pad = 4
    label_h = 16
    cell_h = ch + label_h
    W = cols * cw + (cols + 1) * pad
    H = rows * cell_h + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), (30, 30, 30))
    draw = ImageDraw.Draw(sheet)

    for i, f in enumerate(files):
        r, c = divmod(i, cols)
        x = pad + c * (cw + pad)
        y = pad + r * (cell_h + pad)
        try:
            im = Image.open(f).convert("RGB").resize((cw, ch), Image.BILINEAR)
            sheet.paste(im, (x, y))
        except Exception:
            pass
        # 파일명 일부(슬라이드 번호 등) 라벨
        draw.text((x + 2, y + ch + 1), f.name[:34], fill=(230, 230, 120))

    out = Path(args.out) if args.out else folder.with_suffix(".png")
    sheet.save(out)
    print(f"✅ {len(files)}장 → {out}  ({W}x{H})")


if __name__ == "__main__":
    main()
