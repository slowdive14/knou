"""바이오통계학 강의 슬라이드(자료실 ZIP)를 받아 푼다.

knouon 은 MP3 가 없어 예습 노트를 만들 재료가 마땅치 않았는데, 강의자료실에
**강의 슬라이드가 ZIP 한 덩어리**로 올라와 있다(`Biostat_lecturenotes.zip`).
받아서 풀면 주차별 강의록이 나오고, 그러면 '강의록만으로 요약'(AI네이티브에
쓴 그 경로)으로 노트를 만들 수 있다.

⚠️ 읽기 작업이다 — 서버에 아무것도 남기지 않는다.

실행:
    .venv/Scripts/python.exe fetch_knouon_slides.py
"""
from __future__ import annotations

import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

import knouon
from auth import ensure_logged_in
from config import load_config
from recon import launch_context

COURSE = "바이오통계학"
# 자료실 글 제목에 이 말이 들어간 글에서 첨부를 받는다
WANT = "강의 슬라이드"

_ROWS_JS = """
() => [...document.querySelectorAll('.tabulator-row')].map(el => {
  const a = el.querySelector('a[href*="bbsAtclView"]');
  const oc = a ? (a.getAttribute('href') || '') : '';
  const m = oc.match(/bbsAtclView\\('([^']+)'\\s*,\\s*'([^']*)'/);
  return {title: a ? a.textContent.trim() : '',
          atclId: m ? m[1] : '', bbsId: m ? m[2] : ''};
})
"""


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    cfg = load_config()
    out_dir = Path(argv[0]) if argv else Path(cfg.downloads_dir) / "_바이오통계학_슬라이드"
    out_dir.mkdir(parents=True, exist_ok=True)
    sbjct = knouon.sbjct_id_for(COURSE)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("1) 로그인·강의실…", flush=True)
        ensure_logged_in(page, cfg)
        knouon.enter_classroom(page, sbjct)

        print("2) 강의자료실…", flush=True)
        page.evaluate("""
          () => {
            const a = [...document.querySelectorAll('a')].find(
                el => /강의자료실/.test(el.textContent || ''));
            if (a) a.click();
          }
        """)
        page.wait_for_load_state("networkidle", timeout=60000)
        page.wait_for_timeout(2500)

        rows = page.evaluate(_ROWS_JS)
        target = next((r for r in rows if WANT in (r.get("title") or "")), None)
        if target is None:
            print(f"   '{WANT}' 글을 못 찾았습니다. 목록:", flush=True)
            for r in rows:
                print(f"     {r.get('title')}", flush=True)
            return 1
        print(f"   대상: {target['title']}", flush=True)

        page.evaluate("(a) => bbsAtclView(a.id, a.bbs, 'Y')",
                      {"id": target["atclId"], "bbs": target["bbsId"]})
        page.wait_for_load_state("networkidle", timeout=60000)
        page.wait_for_timeout(2500)

        print("3) 첨부 내려받기(29MB 라 시간이 걸립니다)…", flush=True)
        zip_path = None
        try:
            with page.expect_download(timeout=300000) as di:
                page.evaluate("""
                  () => {
                    const a = [...document.querySelectorAll('a, button')].find(
                        el => /UiFileDownloader/.test(
                            el.getAttribute('onclick') || ''));
                    if (a) a.click();
                  }
                """)
            dl = di.value
            zip_path = out_dir / (dl.suggested_filename or "slides.zip")
            dl.save_as(str(zip_path))
            size = zip_path.stat().st_size
            print(f"   받음: {zip_path.name} ({size / 1024 / 1024:.1f}MB)",
                  flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"   내려받기 실패: {str(e)[:160]}", flush=True)
            return 1
        finally:
            ctx.close()

    print("4) 압축 풀기…", flush=True)
    try:
        with zipfile.ZipFile(zip_path) as z:
            names = z.namelist()
            print(f"   파일 {len(names)}개:", flush=True)
            for n in names[:25]:
                print(f"     {n}", flush=True)
            z.extractall(out_dir)
    except Exception as e:  # noqa: BLE001
        print(f"   압축 풀기 실패: {str(e)[:160]}", flush=True)
        return 1

    print(f"\n푼 곳: {out_dir}", flush=True)
    print("다음: python import_docs.py \"<위 폴더>\" \"바이오통계학\" --dry-run",
          flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
