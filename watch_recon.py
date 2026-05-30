"""Phase 3 정찰: 플레이어 제어 + 진도보고 메커니즘 관찰 (전체 시청 전 검증).

이산수학 13강(미이수) 플레이어를 열어:
  - 팝업/플레이어 iframe 탐지, JWPlayer 상태(state/position/duration/playlist)
  - 2배속 설정 시도(setPlaybackRate)
  - 약 60초 재생하며 진도보고 XHR(네트워크) 관찰
를 수행하고 보고한다. (이수 완료까지 시청하지 않음 — 메커니즘만 학습)

실행:
    .venv/Scripts/python.exe watch_recon.py
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

# 진도/위치 보고로 의심되는 네트워크 URL 힌트
_HINTS = ("prog", "study", "stdy", "position", "point", "time", "save",
          "cmplt", "complete", "mark", "heart", "beat", "view", "play",
          "lect", "ajax", "sdo", ".do", "log")

_PROBE_JS = """
() => {
  const out = {hasVideo:false};
  try {
    const v = document.querySelector('video');
    if (v) { out.hasVideo=true; out.vCurrent=v.currentTime; out.vDur=v.duration;
             out.vRate=v.playbackRate; out.vPaused=v.paused; out.vReady=v.readyState; }
  } catch(e) { out.vErr=String(e); }
  try {
    if (typeof jwplayer === 'function') {
      const jw = jwplayer();
      out.jw = true;
      try { out.jwState = jw.getState(); } catch(e){}
      try { out.jwPos = jw.getPosition(); } catch(e){}
      try { out.jwDur = jw.getDuration(); } catch(e){}
      try { out.jwRate = jw.getPlaybackRate ? jw.getPlaybackRate() : null; } catch(e){}
      try { const pl = jw.getPlaylist ? jw.getPlaylist() : null;
            out.jwPlaylistLen = pl ? pl.length : null; } catch(e){}
      try { out.jwIdx = jw.getPlaylistIndex ? jw.getPlaylistIndex() : null; } catch(e){}
    } else { out.jw = false; }
  } catch(e) { out.jwErr = String(e); }
  return out;
}
"""


def _find_player_frame(pg):
    """video 또는 jwplayer 가 있는 프레임 반환."""
    for fr in pg.frames:
        try:
            ok = fr.evaluate(
                "() => !!document.querySelector('video') || typeof jwplayer==='function'")
            if ok:
                return fr
        except Exception:
            continue
    return None


def main() -> None:
    cfg = load_config()
    reqs = []

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_req(req):
            u = req.url
            low = u.lower()
            if any(h in low for h in _HINTS) and "retrieveUMYStudy" not in u:
                reqs.append((req.method, u[:160]))

        ctx.on("request", on_req)

        ensure_logged_in(page, cfg)

        # 대상 차시의 암호화 ID 확보
        courses = list_courses(page)
        course = next((c for c in courses if c.name == TARGET_COURSE), None)
        if not course:
            print(f"⚠️ 과목 '{TARGET_COURSE}' 없음"); ctx.close(); return
        lects = fetch_lectures(page, course)
        lec = next((l for l in lects if l.seq == TARGET_SEQ), None)
        if not lec:
            print(f"⚠️ {TARGET_SEQ}강 없음"); ctx.close(); return
        print(f"대상: {course.name} {lec.seq}강 '{lec.name}' "
              f"({lec.watched_min}/{lec.total_min}분, 진도 {lec.prog_rt}%)")
        print(f"  cntsTc={lec.cnts_tc} encSbjt={lec.enc_sbjt_id[:12]}...")

        # 플레이어 팝업 열기: fnCntsPopup(strSbjtId, strLectPldcTocNo, strAtlcNo, useYn, scafValuDc, sbjtId)
        reqs.clear()
        with page.expect_popup(timeout=30000) as pi:
            page.evaluate(
                """(a) => fnCntsPopup(a.s, a.t, a.atlc, 'Y', 'Y', a.sbjt)""",
                {"s": lec.enc_sbjt_id, "t": lec.enc_toc_no,
                 "atlc": lec.enc_atlc_no, "sbjt": lec.sbjt_id},
            )
        popup = pi.value
        print(f"\n팝업 열림: {popup.url[:80]}")
        try:
            popup.wait_for_load_state("networkidle", timeout=30000)
        except Exception:
            pass
        time.sleep(5)
        print(f"팝업 URL: {popup.url[:90]}  제목: {popup.title()[:40]}")
        print(f"팝업 프레임 수: {len(popup.frames)}")
        popup.screenshot(path="recon_shots/watch_popup0.png")

        def probe_frame(fr):
            try:
                r = fr.evaluate(_PROBE_JS)
                return r if isinstance(r, dict) else {"raw": r}
            except Exception as e:
                return {"err": str(e)[:60]}

        print("\n프레임별 초기 상태:")
        for i, fr in enumerate(popup.frames):
            st = probe_frame(fr)
            mark = "▶" if (st.get("jw") or st.get("hasVideo")) else " "
            print(f" {mark}frame{i}: {fr.url[:70]}")
            if st.get("jw") or st.get("hasVideo"):
                print(f"      {st}")

        # 플레이어 프레임들(jw/video 있는 것) 모두 대상으로 2배속+재생
        player_frames = [fr for fr in popup.frames
                         if (probe_frame(fr).get("jw") or probe_frame(fr).get("hasVideo"))]
        print(f"\n플레이어 프레임 {len(player_frames)}개에 배속/재생 시도")
        for fr in player_frames:
            try:
                res = fr.evaluate("""() => {
                  let done=[];
                  try { if(typeof jwplayer==='function'){ jwplayer().setPlaybackRate(2);
                        jwplayer().play(true); done.push('jw'); } } catch(e){ done.push('jwErr:'+String(e).slice(0,40)); }
                  try { const v=document.querySelector('video'); if(v){ v.playbackRate=2; v.play();
                        done.push('video'); } } catch(e){ done.push('vErr:'+String(e).slice(0,40)); }
                  return done;
                }""")
                print(f"   {fr.url[-40:]}: {res}")
            except Exception as e:
                print(f"   {fr.url[-40:]}: ERR {str(e)[:50]}")

        # 60초 관찰 (10초 간격, 모든 플레이어 프레임 위치)
        print("\n60초 재생 관찰 (각 플레이어 프레임 pos/dur/state):")
        reqs.clear()
        for t in range(0, 61, 10):
            line = [f"+{t:>2}s"]
            for j, fr in enumerate(player_frames):
                st = probe_frame(fr)
                pos = st.get("jwPos")
                if pos is None:
                    pos = st.get("vCurrent")
                line.append(f"f{j}:pos={pos} st={st.get('jwState')}")
            print("  " + " | ".join(line))
            if t < 60:
                time.sleep(10)

        print(f"\n관찰 중 네트워크 요청({len(reqs)}건, 힌트 매칭):")
        seen = set()
        for m, u in reqs:
            key = u.split("?")[0]
            if key in seen:
                continue
            seen.add(key)
            print(f"  {m} {u}")

        popup.screenshot(path="recon_shots/watch_popup.png")
        print("\n스크린샷: recon_shots/watch_popup.png")
        ctx.close()


if __name__ == "__main__":
    main()
