"""읽기 전용: 이산수학 13강의 현재 진도 상태만 확인(재생 안 함)."""
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
from discover import fetch_lectures, list_courses
from recon import launch_context
from watch import is_complete

TARGET_COURSE = "이산수학"


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        for lec in fetch_lectures(page, course):
            vmark = "✅" if lec.video_done else "  "
            emark = "✅" if lec.exam_done else "  "
            print(f"{lec.seq:>2}강 영상{vmark} watched={lec.watched_min:>3}/{lec.total_min:>3}분 "
                  f"prog={lec.prog_rt:>3}%  연습문제{emark} exam_done={lec.exam_done}")
        ctx.close()


if __name__ == "__main__":
    main()
