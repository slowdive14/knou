"""읽기 전용 2: 강의자료실 게시판의 목록 AJAX + 글보기 첨부 구조를 캡처. **다운로드 안 함.**

probe_data.py 후속. 강의자료실(initUCRLectureData.do) 진입 →
  1) initUCRLectureData.ajax 로 글 목록(bdotNo/제목/분류/날짜) JSON 출력
  2) 첫 글 fnView(bdotNo) → retrieveUCRLectureData.do 글보기에서 첨부 파일/
     다운로드 링크(fnZipDown args, /user_uploading, .pdf 등) 캡처 + HTML 저장
실행: .venv/Scripts/python.exe -u probe_data2.py
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

# 목록 AJAX를 페이지 컨텍스트에서 그대로 호출(폼 직렬화 포함). JSON 텍스트 반환.
_LIST_AJAX_JS = r"""
async () => {
  const body = $('#frm').serialize();
  const res = await fetch('/ekp/user/lectureData/initUCRLectureData.ajax', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
    body, credentials: 'include',
  });
  return await res.text();
}
"""

# 글보기 페이지에서 첨부/다운로드 단서 수집. JSON 문자열 반환.
_VIEW_SCAN_JS = r"""
() => {
  const out = {url: location.href, title: document.title, files: [],
               zipBtns: [], links: [], fileHits: []};
  document.querySelectorAll('a[onclick], button[onclick]').forEach(el => {
    const oc = el.getAttribute('onclick') || '';
    const t = (el.textContent||'').trim().replace(/\s+/g,' ').slice(0,60);
    if (/zip|down|file|user_uploading/i.test(oc))
      out.zipBtns.push({t, onclick: oc.slice(0,200)});
  });
  document.querySelectorAll('a[href]').forEach(a => {
    const h = a.getAttribute('href')||'';
    if (/user_uploading|down|\.(pdf|mp3|hwp|zip|pptx?|docx?)/i.test(h))
      out.links.push({t:(a.textContent||'').trim().slice(0,60), href:h.slice(0,200)});
  });
  // 첨부 영역 후보(파일명 텍스트)
  document.querySelectorAll('[class*="file"], [class*="attach"], [id*="file"]').forEach(el=>{
    const t=(el.textContent||'').trim().replace(/\s+/g,' ').slice(0,80);
    if (t) out.files.push({cls:(el.className||'').slice(0,40), t});
  });
  out.files = out.files.slice(0, 20);
  const html = document.documentElement.outerHTML;
  const re = /[^\s"'<>()]+\.(pdf|mp3|hwp|hwpx|docx?|pptx?|zip)/gi;
  const seen={}; let m;
  while ((m=re.exec(html))!==null){const s=m[0].slice(-100); if(!seen[s]){seen[s]=1; out.fileHits.push(s);} if(out.fileHits.length>40) break;}
  return JSON.stringify(out);
}
"""


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        # 강의자료실 진입
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                page.evaluate("(a)=>fnCourseDataPage(a.atlc,a.sbjt,a.cnts)",
                              {"atlc": ATLC_NO, "sbjt": SBJT_ID, "cnts": CNTS_ID})
        except Exception as e:
            print(f"진입 네비 실패(계속): {e}", flush=True)
            page.wait_for_timeout(2000)
        time.sleep(1.5)
        print(f"강의자료실 URL: {page.url}", flush=True)

        # 1) 목록 AJAX
        try:
            raw = page.evaluate(_LIST_AJAX_JS)
            data = json.loads(raw)
        except Exception as e:
            print(f"목록 AJAX 실패: {e}", flush=True)
            data = {}
        lst = data.get("list") or []
        print(f"\n글 목록 {len(lst)}건:", flush=True)
        for it in lst:
            print(f"   bdotNo={it.get('bdotNo')} 분류={it.get('sbjtBdotClcd')!r} "
                  f"제목={it.get('sbjtNotcTitNm')!r} 날짜={it.get('wrtDttm')}", flush=True)
        # 목록 응답에 첨부파일 단서 키가 있는지(원본 키 일부 출력)
        if lst:
            print(f"\n[목록 item[0] 전체 키]: {sorted(lst[0].keys())}", flush=True)

        # 2) 첫 글 보기
        if lst:
            first = lst[0]["bdotNo"]
            print(f"\n▶ 첫 글 보기 fnView({first})…", flush=True)
            try:
                with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                    page.evaluate("(b)=>fnView(b)", first)
            except Exception as e:
                print(f"글보기 네비 실패(계속): {e}", flush=True)
                page.wait_for_timeout(2000)
            time.sleep(1.5)
            try:
                html = page.content()
                with open("recon_shots/lecturedata_view.html", "w", encoding="utf-8") as fp:
                    fp.write(html)
                print(f"저장 → recon_shots/lecturedata_view.html ({len(html)} chars)", flush=True)
            except Exception as e:
                print(f"HTML 저장 실패: {e}", flush=True)
            try:
                res = json.loads(page.evaluate(_VIEW_SCAN_JS))
            except Exception as e:
                print(f"글보기 scan 실패: {e}", flush=True)
                res = {}
            print(f"\n글보기 URL: {res.get('url','')[:90]}", flush=True)
            print(f"제목: {res.get('title')!r}", flush=True)
            print(f"📄 파일 단서: {res.get('fileHits')}", flush=True)
            print(f"🔘 zip/down 버튼:", flush=True)
            for b in res.get("zipBtns", []):
                print(f"   {b['t']!r} onclick={b['onclick']}", flush=True)
            print(f"🔗 다운로드 링크:", flush=True)
            for a in res.get("links", []):
                print(f"   {a['t']!r} href={a['href']}", flush=True)
            print(f"📎 첨부영역 텍스트:", flush=True)
            for f in res.get("files", []):
                print(f"   cls={f['cls']!r} {f['t']!r}", flush=True)
            page.screenshot(path="recon_shots/lecturedata_view.png")
            print("screenshot → recon_shots/lecturedata_view.png", flush=True)

        ctx.close()


if __name__ == "__main__":
    main()
