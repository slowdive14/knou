"""정찰 2단계: knouon(바이오통계학) **진도 적립 방식** 확인.

영상 이수를 자동화하려면 서버가 무엇을 근거로 진도를 쌓는지 알아야 한다.
전자캠퍼스는 `registerUSTStudyRslt.ajax` 하트비트(300 실초마다 + 정지 시)였고,
적립 기준이 벽시계가 아니라 **영상 위치(vidoLocSec) 커버리지**라 2배속이 통했다.
knouon 은 Kollus 를 쓰므로 방식이 다를 수 있다.

여기서 볼 것:
  1. 재생을 시작하면 어떤 요청이 오가는가(진도 보고 POST 가 있는가)
  2. Kollus iframe 이 부모에게 postMessage 로 무엇을 알리는가
  3. <video> 요소에 직접 닿을 수 있는가(배속 조절 가능 여부)
  4. 짧게 재생한 뒤 주차 진도율이 실제로 오르는가

⚠️ **이 스크립트는 실제로 영상을 재생한다** — 서버에 재생 기록이 남는다.
   어차피 수강해야 하는 강의이고, 관찰은 WATCH_SECONDS(기본 90초)로 짧게 끝낸다.

⚠️ 비밀값(MP4 의 token=JWT, Kollus 의 uservalue1=학번)은 _safe() 로 가려서
   화면·파일 어디에도 남기지 않는다.

실행:
    .venv/Scripts/python.exe probe_knouon_watch.py
"""
from __future__ import annotations

import base64
import json
import re
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
from recon import SHOTS_DIR, launch_context

SBJCT_ID = "SBJCT_KNOU2092001"
WEEK_ID = "WS_KNOU209200101"     # 1주차(이미 0.52% 진도가 있는 주차)
WATCH_SECONDS = 180              # 관찰 시간 — 주기 보고가 있는지 보려면 이 정도는 필요
SPEED = 2.0                      # 배속이 먹히는지도 함께 본다


# 학번이 실려 오는 이름들 — knouon 과 Kollus 가 제각기 다른 키를 쓴다
_ID_KEYS = ("uservalue1", "userId", "client_user_id", "clientUserId", "uid")


def _safe(text: str) -> str:
    """정찰 기록에서 비밀값을 가린다(시한부 JWT · 학번).

    URL 질의문자열·POST 본문·JSON 어디에 있든 가린다. JSON 은 퍼센트 인코딩된
    채로 오기도 해서(`%22client_user_id%22%3A%22…%22`) 그 형태도 함께 훑는다.
    실측 교훈: uservalue1 만 막았더니 POST 본문의 userId 가 그대로 찍혔다.
    """
    s = str(text or "")
    s = re.sub(r"(token=)[^&\s\"']+", r"\1<가림:JWT>", s)
    for k in _ID_KEYS:
        s = re.sub(rf"({k}=)[^&\s\"']+", r"\1<가림:학번>", s)
        s = re.sub(rf"(\"{k}\"\s*:\s*)\"[^\"]*\"", r'\1"<가림:학번>"', s)
        s = re.sub(rf"(%22{k}%22%3A%22)[^%]*%22", r"\1<가림:학번>%22", s)
    return s


def lecture_url(week_id: str = WEEK_ID, sbjct_id: str = SBJCT_ID) -> str:
    """주차 강의 화면 주소. makeEncParams = base64(UTF-8 JSON) (ui-common.js)."""
    enc = base64.b64encode(json.dumps(
        {"lctrWknoSchdlId": week_id, "sbjctId": sbjct_id},
        separators=(",", ":"), ensure_ascii=False).encode("utf-8")).decode()
    return f"https://knouon.knou.ac.kr/lctr/wknoLectureView.do?encParams={enc}"


# 부모 창이 받는 postMessage 를 모아 둔다(Kollus → 페이지 보고 경로 확인용)
_HOOK_MSG_JS = """
() => {
  window.__probeMsgs = [];
  window.addEventListener('message', (e) => {
    try {
      window.__probeMsgs.push({
        origin: e.origin,
        data: (typeof e.data === 'string') ? e.data.slice(0, 400)
              : JSON.stringify(e.data).slice(0, 400),
        at: Date.now(),
      });
    } catch (err) {}
  });
  return 'hooked';
}
"""

# 프레임마다 <video> 상태를 본다(배속을 우리가 만질 수 있는지)
_VIDEO_JS = """
() => {
  const vs = [...document.querySelectorAll('video')];
  return vs.map(v => ({
    pos: v.currentTime, dur: v.duration, rate: v.playbackRate,
    paused: v.paused, ended: v.ended, readyState: v.readyState,
    src: (v.currentSrc || v.src || '').slice(0, 120),
  }));
}
"""

_PLAY_JS = """
(rate) => {
  const out = [];
  for (const v of document.querySelectorAll('video')) {
    try { v.playbackRate = rate; const p = v.play();
          if (p && p.catch) p.catch(e => {});
          out.push('rate=' + v.playbackRate); }
    catch (e) { out.push('err:' + String(e).slice(0, 60)); }
  }
  return out;
}
"""


_SET_RATE_JS = """
(rate) => {
  const out = [];
  for (const v of document.querySelectorAll('video')) {
    try { if (v.playbackRate !== rate) v.playbackRate = rate;
          out.push(v.playbackRate); } catch (e) {}
  }
  return out;
}
"""


def _video_frames(page):
    """<video> 를 가진 프레임만 (index, frame) 로."""
    out = []
    for i, fr in enumerate(page.frames):
        try:
            if fr.evaluate("() => document.querySelectorAll('video').length") > 0:
                out.append((i, fr))
        except Exception:
            pass
    return out


def main() -> int:
    cfg = load_config()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    posts: list[dict] = []

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_req(req):
            """진도 보고로 보이는 요청을 전부 적는다(미디어 조각은 뺀다)."""
            try:
                u = req.url
                if any(u.lower().endswith(x) for x in
                       (".js", ".css", ".png", ".jpg", ".gif", ".woff", ".woff2",
                        ".svg", ".ico")):
                    return
                if req.resource_type == "media" or ".ts" in u:
                    return
                if req.method != "POST" and req.resource_type not in (
                        "xhr", "fetch"):
                    return
                rec = {"t": round(time.time() % 100000, 1), "method": req.method,
                       "url": _safe(u)[:200], "type": req.resource_type}
                try:
                    body = req.post_data
                    if body:
                        rec["body"] = _safe(body)[:2000]
                except Exception:
                    pass
                posts.append(rec)
            except Exception:
                pass

        ctx.on("request", on_req)

        print("1) 로그인 확보…", flush=True)
        ensure_logged_in(page, cfg)

        # 강의실을 먼저 거친다. 바로 강의 URL 로 가면 iframe(Kollus)이 채워지지
        # 않는다 — 세션에 학기·과목 컨텍스트가 잡혀야 하는 것으로 보인다(실측).
        print("2) 대시보드 → 강의실 → 1주차 강의 화면…", flush=True)
        page.goto("https://knouon.knou.ac.kr/dashboard/stuDashboard.do",
                  wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(2000)
        page.evaluate(f"() => moveClassRoom('{SBJCT_ID}')")
        page.wait_for_load_state("networkidle", timeout=60000)
        page.wait_for_timeout(2500)

        page.goto(lecture_url(), wait_until="domcontentloaded", timeout=60000)
        page.evaluate(_HOOK_MSG_JS)
        page.wait_for_timeout(10000)

        vf = _video_frames(page)
        print(f"   프레임 목록:", flush=True)
        for i, fr in enumerate(page.frames):
            print(f"     [{i}] {_safe(fr.url)[:110]}", flush=True)
        print(f"   프레임 {len(page.frames)}개 · <video> 가진 프레임 {len(vf)}개",
              flush=True)
        for i, fr in vf:
            st = fr.evaluate(_VIDEO_JS)
            for v in st:
                print(f"     [{i}] 길이={v['dur']} 위치={v['pos']} "
                      f"배속={v['rate']} 멈춤={v['paused']} "
                      f"src={_safe(v['src'])[:70]}", flush=True)

        if not vf:
            print("   <video> 를 못 찾았다 — Kollus 가 iframe 안에서 막고 있을 수 있다",
                  flush=True)
            print("   (그렇다면 이수는 DOM 조작이 아니라 Kollus 의 재생 UI 를 "
                  "눌러야 한다)", flush=True)

        print(f"\n3) 재생 시작({SPEED}배속) — {WATCH_SECONDS}초만 관찰…", flush=True)
        posts.clear()
        for i, fr in vf:
            try:
                print(f"   [{i}] {fr.evaluate(_PLAY_JS, SPEED)}", flush=True)
            except Exception as e:  # noqa: BLE001
                print(f"   [{i}] 재생 실패: {str(e)[:90]}", flush=True)

        t0 = time.time()
        while time.time() - t0 < WATCH_SECONDS:
            page.wait_for_timeout(15000)
            for i, fr in _video_frames(page):
                try:
                    # 한 번 건 배속이 1 로 되돌아갔다(실측) → 폴링마다 다시 건다.
                    # 이게 통하면 전자캠퍼스처럼 2배속 이수가 가능하다.
                    fr.evaluate(_SET_RATE_JS, SPEED)
                    for v in fr.evaluate(_VIDEO_JS):
                        print(f"   {int(time.time()-t0):>3}초 [{i}] 위치="
                              f"{v['pos']:.0f}/{v['dur']} 배속={v['rate']} "
                              f"멈춤={v['paused']}", flush=True)
                except Exception:
                    pass

        print("\n4) 일시정지(저장을 유도한다)…", flush=True)
        for i, fr in _video_frames(page):
            try:
                fr.evaluate("() => { for (const v of "
                            "document.querySelectorAll('video')) v.pause(); }")
            except Exception:
                pass
        page.wait_for_timeout(6000)

        msgs = page.evaluate("() => window.__probeMsgs || []")
        print(f"\n   postMessage {len(msgs)}건:", flush=True)
        for m in msgs[:12]:
            print(f"     {m['origin'][:40]} | {_safe(m['data'])[:140]}",
                  flush=True)

        print(f"\n   재생 중 오간 요청 {len(posts)}건:", flush=True)
        for c in posts[:25]:
            print(f"     {c['method']:4s} {c['url'][:110]}", flush=True)
            if c.get("body"):
                print(f"          본문: {c['body'][:160]}", flush=True)

        (SHOTS_DIR / "knouon_watch.json").write_text(
            json.dumps({"posts": posts, "messages": msgs},
                       ensure_ascii=False, indent=1), encoding="utf-8")

        print("\n5) 강의실로 돌아가 진도율 변화 확인…", flush=True)
        try:
            page.goto("https://knouon.knou.ac.kr/dashboard/stuDashboard.do",
                      wait_until="domcontentloaded", timeout=60000)
            page.wait_for_timeout(2000)
            page.evaluate(f"() => moveClassRoom('{SBJCT_ID}')")
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(2500)
            rates = page.evaluate("""
              () => [...document.querySelectorAll('li[data-week]')].slice(0, 4)
                .map(li => ({
                  week: li.getAttribute('data-week'),
                  txt: (li.querySelector('.desc_info') || {}).textContent
                       ? li.querySelector('.desc_info').textContent.replace(/\\s+/g,' ').trim()
                       : '',
                }))
            """)
            for r in rates:
                print(f"     {r['week']}주차: {r['txt'][:60]}", flush=True)
        except Exception as e:  # noqa: BLE001
            print(f"   확인 실패: {str(e)[:120]}", flush=True)

        print(f"\n저장: {SHOTS_DIR}", flush=True)
        try:
            input("Enter 로 닫기…")
        except Exception:
            page.wait_for_timeout(10000)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
