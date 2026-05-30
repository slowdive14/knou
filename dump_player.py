"""Phase 3 정찰: 플레이어 팝업의 프레임 HTML을 떠서 JWPlayer setup/진도보고 분석."""
from __future__ import annotations

import sys
import time

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from config import load_config
from discover import fetch_lectures, list_courses
from recon import SHOTS_DIR, launch_context

TARGET_COURSE = "이산수학"
TARGET_SEQ = 13


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ)
        print(f"대상: {course.name} {lec.seq}강 {lec.name}")

        with page.expect_popup(timeout=30000) as pi:
            page.evaluate(
                "(a) => fnCntsPopup(a.s, a.t, a.atlc, 'Y', 'Y', a.sbjt)",
                {"s": lec.enc_sbjt_id, "t": lec.enc_toc_no,
                 "atlc": lec.enc_atlc_no, "sbjt": lec.sbjt_id},
            )
        popup = pi.value
        try:
            popup.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        time.sleep(5)

        for i, fr in enumerate(popup.frames):
            try:
                html = fr.content()
            except Exception as e:
                html = f"<!-- {e} -->"
            path = SHOTS_DIR / f"player_frame{i}.html"
            path.write_text(f"<!-- URL: {fr.url} -->\n{html}", encoding="utf-8")
            print(f"  저장 frame{i} ({len(html)}b): {fr.url[:70]}")

        ctx.close()


if __name__ == "__main__":
    main()
