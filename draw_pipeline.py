"""KNOU LMS 자동화 전체 파이프라인 플로우차트를 PNG로 그린다 (PIL)."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

W, H = 1640, 1180
BG = (255, 255, 255)
INK = (30, 35, 45)
GRAY = (90, 96, 110)

FONT = "C:/Windows/Fonts/malgun.ttf"
FONTB = "C:/Windows/Fonts/malgunbd.ttf"


def f(size, bold=False):
    return ImageFont.truetype(FONTB if bold else FONT, size)


img = Image.new("RGB", (W, H), BG)
d = ImageDraw.Draw(img)


def box(cx, y, w, h, title, sub, fill, border, tcol=INK, bw=3):
    d.rounded_rectangle([cx - w // 2, y, cx + w // 2, y + h],
                        radius=16, fill=fill, outline=border, width=bw)
    if sub:
        d.text((cx, y + h * 0.34), title, font=f(23, True), fill=tcol,
               anchor="mm")
        yy = y + h * 0.64
        for ln in sub.split("\n"):
            d.text((cx, yy), ln, font=f(16), fill=GRAY, anchor="mm")
            yy += 22
    else:
        d.text((cx, y + h / 2), title, font=f(23, True), fill=tcol,
               anchor="mm")
    return y + h


def varrow(cx, y1, y2, col=(120, 128, 140), dashed=False):
    if dashed:
        yy = y1
        while yy < y2 - 10:
            d.line([cx, yy, cx, min(yy + 9, y2 - 10)], fill=col, width=3)
            yy += 16
    else:
        d.line([cx, y1, cx, y2 - 9], fill=col, width=3)
    d.polygon([(cx - 8, y2 - 10), (cx + 8, y2 - 10), (cx, y2)], fill=col)


def dash_conn(x1, y1, x2, y2, col=(224, 123, 26)):
    n = 26
    for i in range(0, n, 2):
        ax = x1 + (x2 - x1) * i / n
        ay = y1 + (y2 - y1) * i / n
        bx = x1 + (x2 - x1) * (i + 1) / n
        by = y1 + (y2 - y1) * (i + 1) / n
        d.line([ax, ay, bx, by], fill=col, width=3)
    d.polygon([(x2 - 10, y2 - 6), (x2 - 10, y2 + 6), (x2 + 2, y2)], fill=col)


# 색상
BLUE = (220, 233, 247)
BLUE_B = (59, 107, 165)
GREEN = (223, 240, 218)
GREEN_B = (79, 157, 69)
ORANGE = (255, 226, 194)
ORANGE_B = (224, 123, 26)
PURPLE = (234, 220, 247)
PURPLE_B = (126, 79, 176)
YELLOW = (255, 244, 200)
YELLOW_B = (200, 160, 30)
GO = (215, 240, 210)
GO_B = (60, 150, 70)

# 제목
d.text((W / 2, 40), "방송대(KNOU) LMS 자동화 — 전체 파이프라인",
       font=f(34, True), fill=INK, anchor="mm")
d.line([40, 72, W - 40, 72], fill=(210, 214, 222), width=2)

# ── 왼쪽: main.py 전체 흐름 ──
LX = 330
LW = 500
gap = 26
y = 100
y = box(LX, y, LW, 56, "main.py 오케스트레이터  ·  모드: 이수 / 요약 / 전체",
        "", (238, 240, 245), (150, 156, 168)) + gap

steps = [
    ("① 로그인  (auth)", "브라우저 1회 기동 · 자동 로그인", BLUE, BLUE_B),
    ("② 강의 순회  (discover)",
     "전과목 강의 목록 · course/seq/미시청 필터", BLUE, BLUE_B),
    ("강의별 반복  (state.json)",
     "완료 단계는 skip · 중단 후 이어하기", (236, 238, 243), (150, 156, 168)),
    ("③ watch — 영상 자동 이수", "(모드: 이수 / 전체)", GREEN, GREEN_B),
    ("④ download", "MP3 + PDF 다운로드", GREEN, GREEN_B),
    ("⑤ summarize",
     "Gemini 요약 → 노트 작성 (▶ 마커 생성)", GREEN, GREEN_B),
    ("⑥ capture  ★  = deck_match",
     "슬라이드 덱 매칭 + 마커/이미지 보정", ORANGE, ORANGE_B),
    ("▶ Obsidian 노트 완성",
     "개념별 정확한 슬라이드 + 보정된 시각", GO, GO_B),
]
cap_y = None
for i, (t, s, fl, br) in enumerate(steps):
    bw = 4 if "capture" in t else 3
    bottom = box(LX, y, LW, 80, t, s, fl, br, bw=bw)
    if "capture" in t:
        cap_y = (y, bottom)
    if i < len(steps) - 1:
        varrow(LX, bottom, bottom + gap)
    y = bottom + gap

# ── 오른쪽: deck_match 상세 ──
RX = 1130
RW = 760
ry = 100
ry = box(RX, ry, RW, 56, "★ ⑥ capture 단계 상세 — deck_match.py", "",
         (255, 238, 220), ORANGE_B) + 24

rsteps = [
    ("영상 (HLS 스트림)",
     "ffmpeg: 키프레임만 디코드 + crop 880:470:40:80 + fps=1",
     (235, 238, 244), (150, 156, 168), INK),
    ("초단위 프레임  frames_NN/",
     "f_000001 = 0초 …  (파일순번 = 초)", BLUE, BLUE_B, INK),
    ("★1  dHash(64bit) + 해밍거리 > 20",
     "→ 슬라이드 덱 (대표프레임·실제시각)   ◀ 이미지끼리 '숫자'로 구분",
     YELLOW, YELLOW_B, INK),
    ("노트 개념 파싱",
     "▶ 마커별 개념 블록 (제목 + 본문) 추출", BLUE, BLUE_B, INK),
    ("★2  Gemini 멀티모달 1회 호출",
     "개념 ↔ 슬라이드 의미 매칭 → JSON   ◀ 텍스트↔이미지 '의미'로 판단",
     PURPLE, PURPLE_B, INK),
    ("전방채움 (forward-fill)",
     "미매칭 개념 → 가장 가까운 매칭 형제 슬라이드", BLUE, BLUE_B, INK),
    ("노트 반영  (--apply 일 때만)",
     "▶ 시각 교정 · 본문크롭 임베드 · 옛캡처 정리 · timestamps",
     ORANGE, ORANGE_B, INK),
]
for i, (t, s, fl, br, tc) in enumerate(rsteps):
    bottom = box(RX, ry, RW, 84, t, s, fl, br, tcol=tc)
    if i < len(rsteps) - 1:
        varrow(RX, bottom, bottom + 22)
    ry = bottom + 22

# capture(왼쪽) → deck_match(오른쪽) 점선 연결
if cap_y:
    dash_conn(LX + LW // 2, (cap_y[0] + cap_y[1]) // 2, RX - RW // 2, 128)

# 하단 범례
ly = H - 54
d.rounded_rectangle([40, ly, W - 40, H - 16], radius=12,
                    fill=(248, 249, 251), outline=(214, 218, 226), width=2)
d.text((60, (ly + H - 16) / 2),
       "검증 완료:  DB14  20/20      이산수학 13강  18/18      "
       "(둘 다 슬라이드 콘텐츠 일치 확인 · 옛 오디오 마커 → 실제 등장 시각으로 교정)",
       font=f(18, True), fill=(60, 90, 60), anchor="lm")

out = Path("pipeline_overview.png")
img.save(out)
print(f"saved: {out.resolve()}  ({W}x{H})", flush=True)
