import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from playwright.sync_api import sync_playwright
from auth import ensure_logged_in
from config import load_config
from discover import fetch_lectures, list_courses
from recon import launch_context
from watch import open_player

cfg = load_config()
with sync_playwright() as p:
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ensure_logged_in(page, cfg)
    course = next(c for c in list_courses(page) if c.name == "이산수학")
    lec = next(l for l in fetch_lectures(page, course) if l.seq == 13)
    popup = open_player(page, lec)
    print("frames:", len(popup.frames))
    for i, fr in enumerate(popup.frames):
        if "ViewPlayer" not in (fr.url or ""):
            print(f"  f{i} (parent) {fr.url[:50]}")
            continue
        try:
            a = fr.evaluate("() => 40+2")
        except Exception as e:
            a = "EXC:" + str(e)[:40]
        try:
            b = fr.evaluate("() => JSON.stringify({x: !!document.querySelector('video'), pid: (document.querySelector('[id^=player]')||{}).id})")
        except Exception as e:
            b = "EXC:" + str(e)[:40]
        try:
            c = fr.evaluate("() => typeof window.$player + '/' + typeof window.fnPlaySpeed + '/' + typeof window.jwplayer")
        except Exception as e:
            c = "EXC:" + str(e)[:40]
        print(f"  f{i}: num={a!r} obj={b!r} globals={c!r}")
    ctx.close()
