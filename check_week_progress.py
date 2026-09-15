"""바이오통계학 주차별 진도율만 읽어 본다(읽기 전용, 재생하지 않음)."""
from __future__ import annotations
import sys
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass
from playwright.sync_api import sync_playwright
from auth import ensure_logged_in
from config import load_config
from recon import launch_context

with sync_playwright() as p:
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ensure_logged_in(page, load_config())
    page.goto("https://knouon.knou.ac.kr/dashboard/stuDashboard.do",
              wait_until="domcontentloaded", timeout=60000)
    page.wait_for_timeout(2000)
    page.evaluate("() => moveClassRoom('SBJCT_KNOU2092001')")
    page.wait_for_load_state("networkidle", timeout=60000)
    page.wait_for_timeout(2500)
    rows = page.evaluate("""
      () => [...document.querySelectorAll('li[data-week]')].map(li => {
        const d = li.querySelector('.desc_info');
        const t = li.querySelector('.title strong');
        return {w: li.getAttribute('data-week'),
                nm: t ? t.textContent.trim() : '',
                pr: d ? d.textContent.replace(/\s+/g,' ').trim() : ''};
      })
    """)
    for r in rows[:5]:
        print(f"{r['w']:>2}주차 {r['nm'][:30]:32s} {r['pr'][:30]}")
    ctx.close()
