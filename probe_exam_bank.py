"""정찰: 기출문제 자료실(initUCRLectureData.do) 구조 파악.

기출문제와 정답표를 반복 학습에 쓰려면 먼저 이것부터 알아야 한다:
  1. 목록이 어떻게 생겼는가(과목 검색·필터가 있는가)
  2. C프로그래밍 기출이 몇 건이고 어느 연도·학기인가
  3. 첨부가 PDF 인가 한글인가, **텍스트가 뽑히는가**(스캔 이미지면 다른 길)
  4. 정답표가 문제지와 같은 글에 붙는가, 따로인가

**읽기 전용**이다. 내려받지 않고 목록과 상세만 본다.

실행:
    .venv/Scripts/python.exe probe_exam_bank.py [과목검색어]
"""
from __future__ import annotations

import json
import re
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from config import load_config
from recon import SHOTS_DIR, launch_context

URL = "https://ucampus.knou.ac.kr/ekp/user/lectureData/initUCRLectureData.do"
WANT = "C프로그래밍"

# 화면을 넓게 훑는다 — 셀렉터를 모르므로 구조부터 본다
_SCAN_JS = """
() => {
  const txt = (el) => (el ? el.textContent.replace(/\\s+/g, ' ').trim() : '');
  const rows = [...document.querySelectorAll('tr, .tabulator-row, li')]
    .filter(el => (el.textContent || '').trim().length > 10)
    .slice(0, 40)
    .map(el => ({
      text: txt(el).slice(0, 130),
      links: [...el.querySelectorAll('a, button')].slice(0, 4).map(a => ({
        text: txt(a).slice(0, 40),
        href: (a.getAttribute('href') || '').slice(0, 120),
        onclick: (a.getAttribute('onclick') || '').slice(0, 140),
      })),
    }));
  const inputs = [...document.querySelectorAll('input, select')].slice(0, 15)
    .map(el => ({tag: el.tagName.toLowerCase(), type: el.type || '',
                 name: el.name || '', id: el.id || '',
                 placeholder: el.placeholder || '',
                 options: el.tagName === 'SELECT'
                   ? [...el.options].slice(0, 8).map(o => o.textContent.trim()) : []}));
  return {url: location.href, title: document.title,
          bodyLen: document.body ? document.body.innerHTML.length : 0,
          frames: [...document.querySelectorAll('iframe')].map(f => f.src || f.name),
          rows, inputs};
}
"""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    want = argv[0] if argv else WANT
    cfg = load_config()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    calls: list[dict] = []

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_resp(resp):
            try:
                if resp.request.resource_type not in ("xhr", "fetch"):
                    return
                rec = {"url": resp.url[:160], "status": resp.status}
                if "json" in (resp.headers or {}).get("content-type", "").lower():
                    try:
                        rec["json"] = resp.json()
                    except Exception:
                        pass
                calls.append(rec)
            except Exception:
                pass

        page.on("response", on_resp)

        print("1) 로그인…", flush=True)
        ensure_logged_in(page, cfg)

        print("2) 기출문제 자료실 열기…", flush=True)
        page.goto(URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)

        info = page.evaluate(_SCAN_JS)
        print(f"   URL  : {info['url'][:110]}", flush=True)
        print(f"   제목 : {info['title']}", flush=True)
        print(f"   본문 : {info['bodyLen']}글자 · iframe {len(info['frames'])}개",
              flush=True)
        for f in info["frames"]:
            print(f"     iframe: {str(f)[:100]}", flush=True)
        print(f"   입력칸 {len(info['inputs'])}개:", flush=True)
        for q in info["inputs"]:
            extra = f" 옵션={q['options'][:5]}" if q["options"] else ""
            print(f"     <{q['tag']} {q['type']}> name={q['name']} "
                  f"id={q['id']} {q['placeholder']}{extra}", flush=True)
        print(f"   줄 {len(info['rows'])}개(앞 15):", flush=True)
        for r in info["rows"][:15]:
            print(f"     {r['text'][:100]}", flush=True)
            for a in r["links"][:2]:
                if a["onclick"] or a["href"]:
                    print(f"        ↳ {a['text'][:24]} | "
                          f"{(a['onclick'] or a['href'])[:90]}", flush=True)
        print(f"   XHR {len(calls)}건:", flush=True)
        for c in calls[:10]:
            print(f"     {c['status']} {c['url'][:110]}", flush=True)

        (SHOTS_DIR / "exam_bank_scan.json").write_text(
            json.dumps({"info": info, "xhr": calls}, ensure_ascii=False,
                       indent=1), encoding="utf-8")
        (SHOTS_DIR / "exam_bank.html").write_text(page.content(),
                                                  encoding="utf-8")
        page.screenshot(path=str(SHOTS_DIR / "exam_bank.png"), full_page=True)
        print(f"\n저장: {SHOTS_DIR}", flush=True)
        print(f"(검색어 '{want}' 로 걸러내는 방법은 위 입력칸을 보고 정합니다)",
              flush=True)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
