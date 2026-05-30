"""읽기 전용 3: 강의자료실 전체 목록 + 첨부파일 필드 확정. **다운로드 안 함.**

recordCountPerPage를 크게 잡아 전 글을 한 번에 받아 각 글의
bdotNo/제목/분류/fileCnt/apndFileNm/apndFileSaveNm/allApndFileNm 를 출력.
→ 다운로드 URL(/user_uploading?...getfile=&realFileName=) 직접 구성 가능한지 검증.
실행: .venv/Scripts/python.exe -u probe_data3.py
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

_LIST_AJAX_JS = r"""
async () => {
  $('#recordCountPerPage').val('100');
  $('#pageIndex').val('1');
  const body = $('#frm').serialize();
  const res = await fetch('/ekp/user/lectureData/initUCRLectureData.ajax', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
    body, credentials: 'include',
  });
  return await res.text();
}
"""


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        try:
            with page.expect_navigation(wait_until="domcontentloaded", timeout=20000):
                page.evaluate("(a)=>fnCourseDataPage(a.atlc,a.sbjt,a.cnts)",
                              {"atlc": ATLC_NO, "sbjt": SBJT_ID, "cnts": CNTS_ID})
        except Exception:
            page.wait_for_timeout(2000)
        time.sleep(1.5)

        raw = page.evaluate(_LIST_AJAX_JS)
        data = json.loads(raw)
        lst = data.get("list") or []
        print(f"전체 글 {len(lst)}건\n", flush=True)
        for it in lst:
            title = (it.get("sbjtNotcTitNm") or "").replace("&lt;", "<").replace("&gt;", ">")
            print(f"bdotNo={it.get('bdotNo')} 분류={it.get('sbjtBdotClcd')!r} "
                  f"fileCnt={it.get('fileCnt')} 제목={title!r}", flush=True)
            print(f"   apndFileNm={it.get('apndFileNm')!r}", flush=True)
            print(f"   apndFileSaveNm={it.get('apndFileSaveNm')!r}", flush=True)
            allf = it.get("allApndFileNm")
            if allf:
                print(f"   allApndFileNm={allf!r}", flush=True)
        # 저장(설계 참고용)
        with open("recon_shots/lecturedata_list.json", "w", encoding="utf-8") as fp:
            json.dump(lst, fp, ensure_ascii=False, indent=1)
        print("\n저장 → recon_shots/lecturedata_list.json", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
