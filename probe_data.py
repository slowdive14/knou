"""읽기 전용: 강의자료(자료실) 페이지 구조를 캡처한다. **아무것도 다운로드 안 함.**

대상: 이산수학(atlcNo=14802079, sbjtId=KNOU1545001, cntsId=KNOU1545).
나의학습 페이지에서 fnCourseDataPage(...)를 호출 → initUCRLectureData.do 로 이동 후
  - 다운로드 링크/버튼(onclick, href)
  - 파일명·확장자(.pdf/.mp3/.hwp 등) 단서
  - 탭/목록 구조
를 출력하고 HTML을 recon_shots/lecturedata_*.html 로 저장한다.
실행: .venv/Scripts/python.exe -u probe_data.py
"""
from __future__ import annotations

import json
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
from recon import launch_context

ATLC_NO = "14802079"
SBJT_ID = "KNOU1545001"
CNTS_ID = "KNOU1545"

# 페이지(또는 프레임)에서 다운로드/파일 단서를 긁는다. JSON 문자열 반환.
_SCAN_JS = r"""
() => {
  const out = {url: location.href, title: document.title,
               links: [], buttons: [], fileHits: [], iframes: [], tabs: []};
  // a[href] 중 파일 또는 다운로드성
  document.querySelectorAll('a[href], a[onclick]').forEach(a => {
    const href = a.getAttribute('href') || '';
    const oc = a.getAttribute('onclick') || '';
    const t = (a.textContent || '').trim().replace(/\s+/g, ' ').slice(0, 40);
    if (href || oc) out.links.push({t, href: href.slice(0, 120), onclick: oc.slice(0, 120)});
  });
  document.querySelectorAll('button[onclick]').forEach(b => {
    out.buttons.push({t: (b.textContent||'').trim().replace(/\s+/g,' ').slice(0,40),
                      onclick: (b.getAttribute('onclick')||'').slice(0,120)});
  });
  // 파일 확장자 단서(전체 HTML 텍스트에서)
  const html = document.documentElement.outerHTML;
  const re = /[^\s"'<>()]+\.(pdf|mp3|hwp|hwpx|docx?|pptx?|zip)/gi;
  const seen = {};
  let m;
  while ((m = re.exec(html)) !== null) {
    const s = m[0].slice(-100);
    if (!seen[s]) { seen[s] = 1; out.fileHits.push(s); }
    if (out.fileHits.length > 60) break;
  }
  document.querySelectorAll('iframe').forEach(f =>
    out.iframes.push({id: f.id || '', src: (f.getAttribute('src')||'').slice(0,120)}));
  // 탭/목록 컨테이너 후보
  document.querySelectorAll('[class*="tab"], [id*="tab"], [class*="list"]').forEach(el => {
    const t = (el.textContent||'').trim().replace(/\s+/g,' ').slice(0, 50);
    if (t) out.tabs.push({tag: el.tagName, cls: (el.className||'').slice(0,40), t});
  });
  out.tabs = out.tabs.slice(0, 25);
  return JSON.stringify(out);
}
"""


def _scan(target, label):
    try:
        res = json.loads(target.evaluate(_SCAN_JS))
    except Exception as e:
        print(f"  [{label}] scan 실패: {e}", flush=True)
        return
    print(f"\n[{label}] url={res['url'][:90]}", flush=True)
    print(f"  title={res['title']!r}", flush=True)
    if res["fileHits"]:
        print(f"  📄 파일 단서 {len(res['fileHits'])}개:", flush=True)
        for f in res["fileHits"]:
            print(f"     {f}", flush=True)
    else:
        print("  📄 파일 단서 없음", flush=True)
    dl = [b for b in res["buttons"] if any(k in b["onclick"].lower()
          for k in ("down", "file", "pdf", "data"))]
    if dl:
        print(f"  🔘 다운로드성 버튼 {len(dl)}개:", flush=True)
        for b in dl:
            print(f"     {b['t']!r} onclick={b['onclick']}", flush=True)
    dlinks = [a for a in res["links"] if any(k in (a["href"]+a["onclick"]).lower()
              for k in ("down", "file", ".pdf", ".mp3", "data"))]
    if dlinks:
        print(f"  🔗 다운로드성 링크 {len(dlinks)}개:", flush=True)
        for a in dlinks:
            print(f"     {a['t']!r} href={a['href']} onclick={a['onclick']}", flush=True)
    if res["iframes"]:
        print(f"  🖼 iframe {len(res['iframes'])}개:", flush=True)
        for f in res["iframes"]:
            print(f"     id={f['id']!r} src={f['src']}", flush=True)


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        # 나의학습 페이지에서 강의자료 함수 존재 확인
        has_fn = page.evaluate(
            "() => typeof fnCourseDataPage === 'function'")
        print(f"fnCourseDataPage 존재(메인): {has_fn}", flush=True)

        # 강의자료 페이지로 이동 (form submit → _self 네비게이션)
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                page.evaluate(
                    "(a) => fnCourseDataPage(a.atlc, a.sbjt, a.cnts)",
                    {"atlc": ATLC_NO, "sbjt": SBJT_ID, "cnts": CNTS_ID})
        except Exception as e:
            print(f"네비게이션 대기 실패(계속 진행): {e}", flush=True)
            page.wait_for_timeout(3000)

        time.sleep(2)
        print(f"\n현재 URL: {page.url}", flush=True)

        # HTML 저장
        try:
            html = page.content()
            with open("recon_shots/lecturedata_main.html", "w", encoding="utf-8") as fp:
                fp.write(html)
            print("저장 → recon_shots/lecturedata_main.html "
                  f"({len(html)} chars)", flush=True)
        except Exception as e:
            print(f"HTML 저장 실패: {e}", flush=True)

        _scan(page, "main")
        for i, fr in enumerate(page.frames):
            if fr == page.main_frame:
                continue
            _scan(fr, f"frame{i} {fr.url[:50]}")

        page.screenshot(path="recon_shots/lecturedata.png")
        print("\nscreenshot → recon_shots/lecturedata.png", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
