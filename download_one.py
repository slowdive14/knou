"""Phase 4 수동 검증: 이산수학 1강 MP3(음성) + PDF(강의록) 다운로드.

로그인 → 과목/차시 조회 → 강의자료실 글목록 조회 → download_lecture(1강) →
저장 결과(바이트/경로)와 파일 존재·비어있지 않음 검증 출력.
서버엔 GET만 보냄(되돌릴 수 없는 행위 아님). 실행: .venv/Scripts/python.exe -u download_one.py
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
from config import load_config
from discover import fetch_lectures, list_courses
from download import download_lecture, fetch_data_posts, needs_download
from recon import launch_context

TARGET_COURSE = "이산수학"
TARGET_SEQ = 1


def main() -> None:
    cfg = load_config()
    dest = cfg.downloads_dir
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lecs = fetch_lectures(page, course)
        lec = next(l for l in lecs if l.seq == TARGET_SEQ)
        print(f"대상: {course.name} {lec.seq}강 '{lec.name}'", flush=True)
        print(f"  audio_url={lec.audio_url}", flush=True)
        print(f"  sbjt_id={lec.sbjt_id} atlc_no={lec.atlc_no}", flush=True)
        print(f"  저장 폴더: {dest}", flush=True)

        # 강의자료실 글목록(1회 조회 후 재사용)
        posts = fetch_data_posts(page, lec.atlc_no, lec.sbjt_id, course.sbjt_id[:-3])
        print(f"\n강의자료실 글 {len(posts)}건 조회", flush=True)

        print(f"\n▶ 다운로드 시작…", flush=True)
        res = download_lecture(ctx, page, lec, course.name, posts=posts,
                               dest_dir=dest, on_event=lambda m: print("  ·", m, flush=True))

        print("\n=== 결과 ===", flush=True)
        for kind in ("mp3", "pdf"):
            r = res.get(kind)
            if not r:
                print(f"  {kind.upper()}: (없음)", flush=True)
                continue
            if r.get("skipped"):
                print(f"  {kind.upper()}: skip(이미 있음) {r['path']}", flush=True)
            else:
                kb = r.get("bytes", 0) / 1024
                print(f"  {kind.upper()}: ok={r.get('ok')} status={r.get('status')} "
                      f"{kb:.1f} KB → {r.get('path')}", flush=True)
                if r.get("error"):
                    print(f"       error={r['error']}", flush=True)

        # 검증
        print("\n=== 검증(파일 존재 + 비어있지 않음) ===", flush=True)
        for kind in ("mp3", "pdf"):
            r = res.get(kind)
            if not r:
                continue
            path = Path(r["path"])
            ok = path.exists() and not needs_download(path)
            size = path.stat().st_size if path.exists() else 0
            print(f"  {kind.upper()}: {'✅' if ok else '❌'} {path.name} ({size} bytes)",
                  flush=True)

        ctx.close()


if __name__ == "__main__":
    main()
