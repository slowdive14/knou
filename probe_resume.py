"""이어보기/처음부터 모달의 버튼 id/class 와 질문 문구를 '읽기 전용'으로 캡처.

대상: 이산수학 14강 첫 영상(이미 완청 → '처음부터 다시 시청하시겠습니까?' 모달2).
재생버튼만 눌러 모달을 띄운 뒤, 버튼 정보와 질문 문구를 읽고 **아무것도 누르지 않고** 닫는다.
실행: .venv/Scripts/python.exe probe_resume.py
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
from discover import fetch_lectures, list_courses
from recon import launch_context
from watch import open_player

TARGET_COURSE = "이산수학"
TARGET_SEQ = 14

# 모달 분석: (1)질문 문구 (2)예/아니오 버튼의 id/class/위치 를 한 번에 수집.
_SCAN_JS = r"""
() => {
  const result = {question: '', buttons: []};
  // 질문 문구 후보
  const bodyText = (document.body && document.body.innerText) || '';
  for (const line of bodyText.split('\n')) {
    const s = line.trim();
    if (s.includes('시청하시겠습니까') || s.includes('이전 재생 기록')) {
      result.question += (result.question ? ' | ' : '') + s;
    }
  }
  // 버튼 후보
  const wanted = ['예', '아니오'];
  const all = document.querySelectorAll('button, a, div, span, input, td, li');
  for (const el of all) {
    const t = (el.textContent || el.value || '').trim();
    if (!wanted.includes(t)) continue;
    const r = el.getBoundingClientRect();
    if (r.width === 0 || r.height === 0) continue;   // 숨김 제외
    result.buttons.push({
      text: t, tag: el.tagName, id: el.id || '', cls: el.className || '',
      onclick: (el.getAttribute && el.getAttribute('onclick')) || '',
      x: Math.round(r.x), y: Math.round(r.y)
    });
  }
  return JSON.stringify(result);
}
"""


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ)
        print(f"대상: {course.name} {lec.seq}강 "
              f"(watched={lec.watched_min}/{lec.total_min}분 done={lec.video_done})")
        popup = open_player(page, lec)
        time.sleep(3)
        print(f"팝업 프레임 {len(popup.frames)}개")

        # 첫 클립 재생버튼만 클릭 → 모달 유도 (모달 버튼은 절대 안 누름)
        clip_frames = [fr for fr in popup.frames if "ViewPlayer" in (fr.url or "")]
        if clip_frames:
            for sel in (".jw-display-icon-container", ".jw-icon-display", "video"):
                try:
                    clip_frames[0].locator(sel).first.click(timeout=3000)
                    print(f"재생버튼 클릭: {sel}")
                    break
                except Exception as e:
                    print(f"  클릭 실패 {sel}: {str(e)[:40]}")
        time.sleep(3)

        for i, fr in enumerate(popup.frames):
            if "ViewPlayer" not in (fr.url or ""):
                continue
            try:
                res = json.loads(fr.evaluate(_SCAN_JS))
            except Exception as e:
                res = {"evalErr": str(e)[:60]}
            if res.get("question") or res.get("buttons"):
                print(f"\n[frame {i}]")
                print(f"  질문: {res.get('question')!r}")
                for b in res.get("buttons", []):
                    print(f"  버튼: text={b['text']!r} id={b['id']!r} "
                          f"cls={b['cls']!r} x={b['x']} y={b['y']}")
        popup.screenshot(path="recon_shots/resume_modal2.png")
        print("\nscreenshot → recon_shots/resume_modal2.png  (버튼 클릭 안 함)")
        ctx.close()


if __name__ == "__main__":
    main()
