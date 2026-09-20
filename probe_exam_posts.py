"""C프로그래밍 강의자료실에 어떤 글·첨부가 있는지 본다(읽기 전용).

기출문제와 정답표를 찾는 게 목적이다. 기존 download.fetch_data_posts 를
그대로 쓴다 — 이미 자료실을 다루는 코드가 있다.
"""
from __future__ import annotations
import json, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from playwright.sync_api import sync_playwright
from auth import ensure_logged_in
from config import load_config
from discover import list_courses
from download import _cnts_id_of, _split_files, fetch_data_posts
from recon import SHOTS_DIR, launch_context

WANT = sys.argv[1] if len(sys.argv) > 1 else "C프로그래밍"

with sync_playwright() as p:
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ensure_logged_in(page, load_config())
    course = next((c for c in list_courses(page) if WANT in c.name), None)
    if course is None:
        print(f"'{WANT}' 과목을 못 찾았습니다."); raise SystemExit(1)
    print(f"과목: {course.name} (sbjt={course.sbjt_id}, atlc={course.atlc_no})", flush=True)
    posts = fetch_data_posts(page, course.atlc_no, course.sbjt_id,
                             _cnts_id_of(course.sbjt_id))
    print(f"자료실 글 {len(posts)}건\n", flush=True)
    cats = {}
    for po in posts:
        cats[po.get("sbjtBdotClcd") or "(분류없음)"] = cats.get(po.get("sbjtBdotClcd") or "(분류없음)", 0) + 1
    print("분류별:", cats, "\n", flush=True)
    for po in posts:
        files = _split_files(po)
        title = (po.get("bdotTtl") or po.get("title") or "").strip()
        cat = po.get("sbjtBdotClcd") or ""
        print(f"[{cat}] {title[:60]}", flush=True)
        for dn, sn in files:
            print(f"     · {dn[:70]}", flush=True)
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    (SHOTS_DIR / "exam_posts.json").write_text(
        json.dumps(posts, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"\n저장: {SHOTS_DIR / 'exam_posts.json'}", flush=True)
    ctx.close()
