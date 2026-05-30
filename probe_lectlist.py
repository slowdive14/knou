"""Phase 2 정찰: 차시 목록 AJAX(retrieveUMYAtlcLectList.ajax) 실제 JSON 샘플 확보.

로그인 보장 후 '나의 학습'에서 (atlcNo, sType) 쌍을 긁어, 첫 과목의 차시 목록
JSON을 떠서 recon_shots/lectlist_sample.json 에 저장한다.
필드명/완료기준(stdyCmyn, stdyHrMnt, vidoHrSec 등)을 확정하기 위함.

실행:
    .venv/Scripts/python.exe probe_lectlist.py
"""
from __future__ import annotations

import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import MY_STUDY_URL, ensure_logged_in
from config import load_config
from recon import SHOTS_DIR, launch_context

# 페이지 안에서 실행: 과목별 (sbjtId, 과목명, atlcNo, sType) 추출
_COURSES_JS = """
() => {
  const items = [...document.querySelectorAll('.lecture-progress-item')];
  return items.map(it => {
    const ul = it.querySelector('ul.lecture-list');
    const titleEl = it.querySelector('.lecture-title a, .lecture-title');
    const valEl = it.querySelector('.lecture-per .value');
    const badge = it.querySelector('.divi2');
    return {
      id: it.id || '',
      title: titleEl ? titleEl.textContent.trim() : '',
      progress: valEl ? valEl.textContent.trim() : '',
      badge: badge ? badge.textContent.trim() : '',
      atlcNo: ul ? ul.getAttribute('data-atlc') : null,
      sType: ul ? (ul.getAttribute('data-stype') || ul.getAttribute('data-sType')) : null,
    };
  });
}
"""

# 페이지 안에서 AJAX 호출(쿠키 자동 포함). jQuery와 동일하게 form-encoded body 사용.
_FETCH_JS = """
async ({atlcNo, sType}) => {
  const body = 'atlcNo=' + encodeURIComponent(atlcNo) + '&sType=' + encodeURIComponent(sType || '');
  const res = await fetch('/ekp/user/study/retrieveUMYAtlcLectList.ajax', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body,
    credentials: 'include',
  });
  const text = await res.text();
  return {status: res.status, text};
}
"""


def main() -> None:
    SHOTS_DIR.mkdir(exist_ok=True)
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        # ensure_logged_in 이 이미 MY_STUDY 에 남겨둠. 재이동하면 jvmsso 세션이
        # 끊겨 로그인 페이지로 리다이렉트되므로 추가 goto 하지 않는다.
        ensure_logged_in(page, cfg)
        print(f"URL={page.url}  TITLE={page.title()}")
        try:
            page.wait_for_selector(".lecture-progress-item", timeout=15000)
        except Exception as e:
            print(f"⚠️ .lecture-progress-item 대기 실패: {e}")
            cnt = page.evaluate("() => document.querySelectorAll('.lecture-progress-item').length")
            print(f"   item count={cnt}")

        courses = page.evaluate(_COURSES_JS)
        print(f"과목 수: {len(courses)}")
        for c in courses:
            print(f"  - {c['title']} | 진도 {c['progress']}% | {c['badge']} "
                  f"| atlcNo={c['atlcNo']} sType={c['sType']} | {c['id']}")

        # 첫 번째 유효 과목의 차시 JSON을 떠본다
        target = next((c for c in courses if c.get("atlcNo")), None)
        if not target:
            print("⚠️ atlcNo 있는 과목 없음")
            ctx.close()
            return

        print(f"\n차시 JSON 요청: {target['title']} (atlcNo={target['atlcNo']})")
        resp = page.evaluate(_FETCH_JS, {"atlcNo": target["atlcNo"], "sType": target["sType"]})
        print(f"HTTP {resp['status']}, 본문 {len(resp['text'])} bytes")

        out = SHOTS_DIR / "lectlist_sample.json"
        out.write_text(resp["text"], encoding="utf-8")
        print(f"저장: {out}")

        # 구조 요약
        try:
            data = json.loads(resp["text"])
            atlc = (data.get("atlcList") or [{}])[0]
            lects = atlc.get("lectList") or []
            print(f"\nlectList {len(lects)}개. 첫 항목 키:")
            if lects:
                for k, v in lects[0].items():
                    print(f"    {k} = {v!r}")
        except Exception as e:
            print(f"JSON 파싱 실패(원문 저장됨): {e}")
            print(resp["text"][:300])

        ctx.close()


if __name__ == "__main__":
    main()
