"""정찰: knouon 강의자료실에 주차별 강의록이 있는지 본다.

예습 노트를 만들려면 음성이나 강의록이 있어야 한다. knouon 은 MP3 가 따로
없으므로(docs/lms-map.md §11-3) 두 갈래다:
  1) 강의자료실에 주차별 강의록(PDF/PPT)이 있으면 → 그걸로 노트를 만든다
     (AI네이티브에 쓴 '강의록만으로 요약' 경로를 그대로 재사용)
  2) 없으면 영상에서 오디오를 뽑아야 한다(MP4 직접 링크)

여기서는 1번 가능성을 확인한다. **읽기 전용**이다.

실행:
    .venv/Scripts/python.exe probe_knouon_docs.py
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

import knouon
from auth import ensure_logged_in
from config import load_config
from recon import SHOTS_DIR, launch_context

COURSE = "바이오통계학"
_ID_KEYS = ("uservalue1", "userId", "client_user_id", "uid")


def _safe(text: str) -> str:
    s = str(text or "")
    s = re.sub(r"(token=)[^&\s\"']+", r"\1<가림:JWT>", s)
    for k in _ID_KEYS:
        s = re.sub(rf"({k}=)[^&\s\"']+", r"\1<가림:학번>", s)
    return s


# 자료실 목록: 제목·날짜·첨부 개수·열기 함수
# 자료실은 Tabulator 로 그린 표다(일반 <tr> 이 아니다 — 실측).
_LIST_JS = """
() => {
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
  return [...document.querySelectorAll('.tabulator-row')].slice(0, 40).map(el => {
    const a = el.querySelector('a[href*="bbsAtclView"]');
    const oc = a ? (a.getAttribute('href') || '') : '';
    const m = oc.match(/bbsAtclView\('([^']+)'\s*,\s*'([^']*)'/);
    return {
      title: a ? txt(a) : txt(el).slice(0, 80),
      atclId: m ? m[1] : '',
      bbsId: m ? m[2] : '',
      row: txt(el).slice(0, 110),
    };
  });
}
"""

# 글 상세의 첨부파일
_FILES_JS = """
() => {
  const txt = (el) => (el ? el.textContent.replace(/\s+/g, ' ').trim() : '');
  const links = [...document.querySelectorAll('a, button')].filter(
      el => /다운로드|download|\.pdf|\.pptx?|\.hwpx?|\.zip/i.test(
          (el.textContent || '') + ' ' + (el.getAttribute('onclick') || '')));
  return JSON.stringify({
    title: txt(document.querySelector('.view_title, .tit, h3, h4')),
    files: links.slice(0, 20).map(el => ({
      text: txt(el).slice(0, 80),
      onclick: (el.getAttribute('onclick') || '').slice(0, 200),
      href: (el.getAttribute('href') || '').slice(0, 200),
    })),
    bodyLen: document.body ? document.body.innerHTML.length : 0,
  });
}
"""


def main() -> int:
    cfg = load_config()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    sbjct = knouon.sbjct_id_for(COURSE)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("1) 로그인·강의실…", flush=True)
        ensure_logged_in(page, cfg)
        knouon.enter_classroom(page, sbjct)

        print("2) 강의자료실로 이동…", flush=True)
        # 강의실 메뉴의 moveMenu 를 그대로 쓴다(encParams 를 직접 만들지 않음)
        try:
            page.evaluate("""
              () => {
                const a = [...document.querySelectorAll('a')].find(
                    el => /강의자료실/.test(el.textContent || ''));
                if (a) a.click();
              }
            """)
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:  # noqa: BLE001
            print(f"   이동 실패: {str(e)[:120]}", flush=True)

        print(f"   URL: {_safe(page.url)[:120]}", flush=True)
        rows = page.evaluate(_LIST_JS)
        print(f"   글 {len(rows)}건:", flush=True)
        for r in rows[:20]:
            print(f"     [{r['atclId'][:22]:22s}] {r['row'][:80]}", flush=True)

        # 첫 글을 열어 첨부파일을 확인한다
        target = next((r for r in rows if r.get("atclId")), None)
        if target:
            print(f"\n3) 글 열기: {target['title'][:50]}", flush=True)
            try:
                page.evaluate("(a) => bbsAtclView(a.id, a.bbs, 'Y')",
                              {"id": target["atclId"], "bbs": target["bbsId"]})
                page.wait_for_load_state("networkidle", timeout=60000)
                page.wait_for_timeout(2500)
                det = json.loads(page.evaluate(_FILES_JS))
                print(f"   제목: {det.get('title','')[:70]}", flush=True)
                print(f"   첨부 {len(det.get('files') or [])}개:", flush=True)
                for f in det.get("files") or []:
                    print(f"     {f['text'][:60]} | {_safe(f['onclick'])[:90]}",
                          flush=True)
                (SHOTS_DIR / "knouon_doc_view.html").write_text(
                    _safe(page.content()), encoding="utf-8")
            except Exception as e:  # noqa: BLE001
                print(f"   열기 실패: {str(e)[:140]}", flush=True)

        (SHOTS_DIR / "knouon_docs.json").write_text(
            json.dumps({"url": _safe(page.url), "rows": rows},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        (SHOTS_DIR / "knouon_docs.html").write_text(
            _safe(page.content()), encoding="utf-8")
        print(f"\n저장: {SHOTS_DIR}", flush=True)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
