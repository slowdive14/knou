"""'기출문제'가 어느 메뉴에 있는지 찾는다(읽기 전용)."""
from __future__ import annotations
import re, sys
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from playwright.sync_api import sync_playwright
from auth import MY_STUDY_URL, ensure_logged_in
from config import load_config
from recon import launch_context

_LINKS_JS = """
() => [...document.querySelectorAll('a, button')].map(el => ({
  text: (el.textContent || '').replace(/\s+/g,' ').trim().slice(0, 40),
  href: (el.getAttribute('href') || '').slice(0, 150),
  onclick: (el.getAttribute('onclick') || '').slice(0, 150),
})).filter(x => x.text)
"""

WANT = re.compile(r"기출|시험|문제|자료|평가", re.I)

with sync_playwright() as p:
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ensure_logged_in(page, load_config())
    for name, url in (("나의 학습", MY_STUDY_URL),
                      ("캠퍼스 메인", "https://ucampus.knou.ac.kr/ekp/user/main/retrieveUMNMain.do")):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2500)
        except Exception as e:
            print(f"[{name}] 열기 실패: {str(e)[:80]}", flush=True); continue
        links = page.evaluate(_LINKS_JS)
        hits = [l for l in links if WANT.search(l["text"])]
        print(f"\n[{name}] 링크 {len(links)}개 · 관련 {len(hits)}개", flush=True)
        for l in hits[:20]:
            print(f"   {l['text'][:28]:30s} | {(l['onclick'] or l['href'])[:95]}", flush=True)
    ctx.close()
