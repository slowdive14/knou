"""Phase 6.5 수동 검증: 비전 검증판 캡처(이산수학 1강).

각 개념 타임스탬프마다 주변 후보 4프레임(−20·0·+15·+30)을 ffmpeg로 뽑아
Gemini 비전에 보내 '개념과 맞는 슬라이드'를 고르게 하고, 그 1장만 남겨
요약 노트의 해당 줄 아래 `![[..]]`로 교체 임베드한다.

서버엔 영상 스트림 GET만. Gemini엔 후보 이미지+개념 라벨만 전송(키 미출력).
실행:
   .venv/Scripts/python.exe -u capture_verify_one.py
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from google import genai
from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from capture import capture_lecture_verified, needs_capture
from config import load_config
from discover import fetch_lectures, list_courses
from download import build_filename
from recon import launch_context
from summarize import note_filename

TARGET_COURSE = "이산수학"
TARGET_SEQ = 1
TARGET_NAME = "이산수학의 개요"


def main() -> None:
    ap = argparse.ArgumentParser(
        description="비전 검증판 캡처 단일 차시 재검증(기본: 이산수학 1강)")
    ap.add_argument("--course", default=TARGET_COURSE)
    ap.add_argument("--seq", type=int, default=TARGET_SEQ)
    ap.add_argument("--name", default=TARGET_NAME)
    args = ap.parse_args()
    course_name, seq, name = args.course, args.seq, args.name

    cfg = load_config()
    mp3 = cfg.downloads_dir / build_filename(course_name, seq, "mp3")
    note = cfg.summary_dir / note_filename(course_name, seq, name)
    ts_json = note.with_suffix(".timestamps.json")

    print(f"대상: {course_name} {seq}강 '{name}'", flush=True)
    print(f"  MP3 : {mp3} ({'있음' if mp3.exists() else '없음'})", flush=True)
    print(f"  노트: {note} ({'있음' if note.exists() else '없음'})", flush=True)
    print(f"  TS  : {ts_json} ({'있음' if ts_json.exists() else '없음'})", flush=True)

    if not (mp3.exists() and note.exists() and ts_json.exists()):
        print("❌ MP3/노트/타임스탬프JSON 중 누락. Phase 4·5 먼저 실행하세요.", flush=True)
        return

    # 비전용 Gemini 클라이언트 (API 키는 절대 출력 금지)
    client = genai.Client(api_key=cfg.gemini_api_key)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == course_name)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == seq)

        print("\n▶ 비전 검증 캡처 시작…", flush=True)
        res = capture_lecture_verified(
            page, lec, course_name, seq, name,
            mp3_path=mp3, note_path=note, client=client,
            overwrite=True,  # 기존 단순캡처 임베드를 비전 선택본으로 교체
            on_event=lambda m: print("  ·", m, flush=True),
        )

        print("\n=== 결과 ===", flush=True)
        print(f"  선택 클립 : {res['clip']}", flush=True)
        print(f"  타임스탬프: {res['ts_count']}개", flush=True)
        print(f"  비전 pick : {res['picked']}개", flush=True)
        print(f"  fallback  : {res['fallback']}개 (t정각)", flush=True)
        print(f"  skip/실패 : {res['skipped']} / {res['failed']}", flush=True)
        print(f"  이미지폴더: {res['out_dir']}", flush=True)

        # 검증: 노트 임베드 수 = 타임스탬프 수, 이미지 비어있지 않음
        out_dir = Path(res["out_dir"])
        md = note.read_text(encoding="utf-8")
        n_embed = md.count("![[")
        print(f"\n=== 검증 ===", flush=True)
        print(f"  노트 임베드: ![[..]] {n_embed}개 (개념 {res['ts_count']}개)", flush=True)

        # 임베드된 파일들이 실제로 존재하고 비어있지 않은지
        import re
        embedded = re.findall(r"!\[\[(.+?)\]\]", md)
        missing = [fn for fn in embedded if needs_capture(out_dir / fn)]
        print(f"  임베드 파일 존재: {len(embedded) - len(missing)}/{len(embedded)}",
              flush=True)
        if missing:
            print(f"  ⚠️ 누락/빈 파일: {missing}", flush=True)

        ctx.close()


if __name__ == "__main__":
    main()
