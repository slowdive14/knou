"""Phase 6 수동 검증: 이산수학 1강 타임스탬프별 화면 캡처 + 노트 임베드.

요약 노트(Phase 5)의 `*.timestamps.json`을 읽어, 플레이어에서 MP3 길이와
가장 가까운 영상 클립을 골라 각 타임스탬프 지점을 ffmpeg로 캡처하고,
요약 노트의 해당 개념 줄 아래에 `![[이미지]]`로 인라인 임베드한다.

서버엔 영상 스트림 GET만(되돌릴 수 없는 행위 아님). 실행:
   .venv/Scripts/python.exe -u capture_one.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from capture import capture_lecture, needs_capture
from config import load_config
from discover import fetch_lectures, list_courses
from recon import launch_context
from summarize import note_filename

TARGET_COURSE = "이산수학"
TARGET_SEQ = 1
TARGET_NAME = "이산수학의 개요"


def main() -> None:
    cfg = load_config()
    mp3 = cfg.downloads_dir / "이산수학_1강.mp3"
    note = cfg.summary_dir / note_filename(TARGET_COURSE, TARGET_SEQ, TARGET_NAME)
    ts_json = note.with_suffix(".timestamps.json")

    print(f"대상: {TARGET_COURSE} {TARGET_SEQ}강 '{TARGET_NAME}'", flush=True)
    print(f"  MP3 : {mp3} ({'있음' if mp3.exists() else '없음'})", flush=True)
    print(f"  노트: {note} ({'있음' if note.exists() else '없음'})", flush=True)
    print(f"  TS  : {ts_json} ({'있음' if ts_json.exists() else '없음'})", flush=True)

    if not (mp3.exists() and note.exists() and ts_json.exists()):
        print("❌ MP3/노트/타임스탬프JSON 중 누락. Phase 4·5 먼저 실행하세요.", flush=True)
        return

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ)

        print("\n▶ 캡처 시작…", flush=True)
        res = capture_lecture(
            page, lec, TARGET_COURSE, TARGET_SEQ, TARGET_NAME,
            mp3_path=mp3, note_path=note,
            on_event=lambda m: print("  ·", m, flush=True),
        )

        print("\n=== 결과 ===", flush=True)
        print(f"  선택 클립 : {res['clip']}", flush=True)
        print(f"  타임스탬프: {res['ts_count']}개", flush=True)
        print(f"  캡처      : {res['captured']}개 / skip {res['skipped']} / 실패 {res['failed']}", flush=True)
        print(f"  이미지폴더: {res['out_dir']}", flush=True)

        # 검증: 캡처 폴더 내 이미지 + 노트에 임베드 포함 여부
        out_dir = Path(res["out_dir"])
        imgs = sorted(out_dir.glob(f"{TARGET_COURSE}_{TARGET_SEQ}강_*")) if out_dir.exists() else []
        good = [p for p in imgs if not needs_capture(p)]
        print(f"\n=== 검증 ===", flush=True)
        print(f"  이미지 파일: {len(good)}개 (비어있지 않음)", flush=True)
        if good:
            sizes = [p.stat().st_size for p in good]
            print(f"    크기: 최소 {min(sizes)/1024:.0f}KB / 최대 {max(sizes)/1024:.0f}KB", flush=True)
        md = note.read_text(encoding="utf-8")
        n_embed = md.count("![[")
        print(f"  노트 임베드: ![[..]] {n_embed}개 포함", flush=True)

        ctx.close()


if __name__ == "__main__":
    main()
