"""Phase 2 수동 검증: 실제 LMS에서 과목/차시/진도 수집이 되는지 1회 확인.

로그인 보장 후 discover()로 전 과목·차시를 수집하고, 과목별 미이수 차시를 출력한다.
(영상 재생은 하지 않음 — 데이터 수집/필터만 검증)

실행:
    .venv/Scripts/python.exe discover_check.py
"""
from __future__ import annotations

import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from config import load_config
from discover import discover, filter_incomplete
from recon import launch_context


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # ensure_logged_in 이 MY_STUDY 에 남겨둔 페이지를 그대로 사용(재이동 금지)
        ensure_logged_in(page, cfg)

        data = discover(page)
        print("=" * 70)
        total_todo = 0
        for course, lects in data:
            todo = filter_incomplete(lects)
            total_todo += len(todo)
            badge = "✅완료" if course.fmtv_done else "⏳진행"
            print(f"\n[{badge}] {course.name}  진도 {course.progress}%  "
                  f"(차시 {len(lects)}개, 미이수 {len(todo)}개)")
            for l in todo:
                print(f"    - {l.seq:>2}강 {l.name}  "
                      f"{l.watched_min}/{l.total_min}분  진도 {l.prog_rt}%")
        print("\n" + "=" * 70)
        print(f"총 미이수 차시: {total_todo}개")
        ctx.close()


if __name__ == "__main__":
    main()
