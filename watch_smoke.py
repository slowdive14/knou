"""Phase 3 스모크: 클립 1개를 2배속 재생해 진도저장 XHR이 실제 발생하는지 ~90초 확인.

전체 시청이 아니라 메커니즘 실증용:
  - 첫 클립 iframe 재생버튼 클릭 → 2배속 설정
  - $player 상태/위치/배속 추적
  - registerUSTStudyRslt.ajax (진도저장) 요청 캡처
실행: .venv/Scripts/python.exe watch_smoke.py
"""
from __future__ import annotations

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

TARGET_COURSE = "이산수학"
TARGET_SEQ = 13

_STATE_JS = """
() => {
  try {
    if (typeof $player !== 'undefined' && $player) {
      return {state: $player.getState(), pos: $player.getPosition(),
              dur: $player.getDuration(),
              rate: $player.getPlaybackRate ? $player.getPlaybackRate() : null};
    }
  } catch(e) { return {err: String(e).slice(0,60)}; }
  return {noPlayer: true};
}
"""


def main() -> None:
    cfg = load_config()
    saves = []      # registerUSTStudyRslt 요청
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_req(req):
            if "registerUSTStudyRslt" in req.url:
                saves.append((time.strftime("%H:%M:%S"), req.url[:110], req.post_data or "")[:3])

        ctx.on("request", on_req)
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ)
        print(f"대상: {course.name} {lec.seq}강 {lec.name} ({lec.watched_min}/{lec.total_min}분)")

        with page.expect_popup(timeout=30000) as pi:
            page.evaluate(
                "(a) => fnCntsPopup(a.s, a.t, a.atlc, 'Y', 'Y', a.sbjt)",
                {"s": lec.enc_sbjt_id, "t": lec.enc_toc_no,
                 "atlc": lec.enc_atlc_no, "sbjt": lec.sbjt_id})
        popup = pi.value
        try:
            popup.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        time.sleep(4)

        clip_frames = [fr for fr in popup.frames if "ViewPlayer" in fr.url]
        print(f"클립 프레임 {len(clip_frames)}개")
        if not clip_frames:
            print("⚠️ 클립 프레임 없음"); ctx.close(); return

        fr = clip_frames[0]
        # 재생버튼(JWPlayer display icon) 클릭 → 트러스티드 제스처
        clicked = False
        for sel in (".jw-display-icon-container", ".jw-icon-display", "video"):
            try:
                loc = fr.locator(sel).first
                loc.click(timeout=3000)
                print(f"재생버튼 클릭: {sel}")
                clicked = True
                break
            except Exception as e:
                print(f"  클릭 실패 {sel}: {str(e)[:50]}")
        if not clicked:
            print("⚠️ 재생버튼 클릭 실패")

        time.sleep(2)
        # 2배속 설정
        try:
            res = fr.evaluate("""() => {
              let out=[];
              try { if(typeof fnPlaySpeed==='function'){ fnPlaySpeed('2.0'); out.push('fnPlaySpeed(2.0)'); } } catch(e){ out.push('e1:'+e); }
              try { if($player && $player.setPlaybackRate){ $player.setPlaybackRate(2); out.push('setPlaybackRate(2)'); } } catch(e){ out.push('e2:'+e); }
              return out;
            }""")
            print("배속 설정:", res)
        except Exception as e:
            print("배속 설정 실패:", str(e)[:60])

        print("\n90초 관찰 (state/pos/rate):")
        for t in range(0, 91, 10):
            try:
                st = fr.evaluate(_STATE_JS)
            except Exception as e:
                st = {"evalErr": str(e)[:40]}
            print(f"  +{t:>2}s {st}")
            if t < 90:
                time.sleep(10)

        print(f"\n진도저장 XHR(registerUSTStudyRslt) {len(saves)}건:")
        for s in saves:
            print("  ", s)

        popup.screenshot(path="recon_shots/watch_smoke.png")
        ctx.close()


if __name__ == "__main__":
    main()
