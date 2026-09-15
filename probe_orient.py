"""오리엔테이션 영상이 왜 멈추는지 화면을 띄워 놓고 진단한다.

1주차 강의 화면을 열어 **창을 그대로 둔 채**, 오리엔테이션 프레임의 속사정을
반복해서 찍는다. 사람은 화면을 보고, 이 스크립트는 화면에 안 보이는 값을 읽는다.

보는 값:
  - readyState / networkState / error : 영상이 데이터를 받고 있는지, 거부됐는지
  - paused / currentTime / buffered   : 재생이 걸렸는지, 어디까지 받았는지
  - Kollus 오버레이(재생 버튼·안내 문구)가 떠 있는지
  - 콘솔 오류와 실패한 요청

⚠️ 재생을 시도하므로 기록이 남는다. 이미 여러 번 돌린 1주차를 그대로 쓴다.

실행:
    .venv/Scripts/python.exe probe_orient.py
"""
from __future__ import annotations

import re
import sys
import time

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
WEEK = 1
WATCH_LOOPS = 12          # 10초 간격으로 이만큼 관찰
_ID_KEYS = ("uservalue1", "userId", "client_user_id", "uid")


def _safe(text: str) -> str:
    """학번·시한부 토큰을 가린다."""
    s = str(text or "")
    s = re.sub(r"(token=)[^&\s\"']+", r"\1<가림:JWT>", s)
    for k in _ID_KEYS:
        s = re.sub(rf"({k}=)[^&\s\"']+", r"\1<가림:학번>", s)
    return s


# 영상의 속사정. 숫자 코드는 의미까지 풀어서 돌려준다.
_DIAG_JS = """
() => {
  const READY = ['데이터없음', '길이만앎', '현재프레임만', '조금앞까지', '충분히받음'];
  const NET = ['비어있음', '대기', '받는중', '소스없음'];
  const ERR = {1: '중단됨(ABORTED)', 2: '네트워크(NETWORK)',
               3: '디코드(DECODE)', 4: '지원안함(SRC_NOT_SUPPORTED)'};
  const v = document.querySelector('video');
  if (!v) return JSON.stringify({noVideo: true});
  let buf = [];
  try {
    for (let i = 0; i < v.buffered.length; i++)
      buf.push(`${v.buffered.start(i).toFixed(0)}~${v.buffered.end(i).toFixed(0)}`);
  } catch (e) {}
  // 화면을 덮고 있는 오버레이(재생 버튼·안내)가 있는지
  const vis = (el) => {
    if (!el) return false;
    const r = el.getBoundingClientRect();
    const s = getComputedStyle(el);
    return r.width > 20 && r.height > 20 && s.display !== 'none' &&
           s.visibility !== 'hidden' && parseFloat(s.opacity || '1') > 0.1;
  };
  const overlays = [...document.querySelectorAll(
      '[class*=play],[class*=btn],[class*=overlay],[class*=cover],[class*=poster],[class*=msg],[class*=alert]')]
    .filter(vis)
    .slice(0, 8)
    .map(el => ({cls: String(el.className).slice(0, 50),
                 txt: (el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 60)}));
  return JSON.stringify({
    pos: v.currentTime, dur: v.duration, rate: v.playbackRate,
    paused: v.paused, ended: v.ended, muted: v.muted,
    ready: READY[v.readyState] || v.readyState,
    net: NET[v.networkState] || v.networkState,
    err: v.error ? (ERR[v.error.code] || v.error.code) : null,
    errMsg: v.error && v.error.message ? String(v.error.message).slice(0, 80) : null,
    buffered: buf.join(','),
    src: (v.currentSrc || v.src || '').slice(0, 110),
    overlays,
  });
}
"""

_PLAY_JS = """
(rate) => {
  const v = document.querySelector('video');
  if (!v) return 'noVideo';
  try {
    v.playbackRate = rate;
    const p = v.play();
    if (p && p.catch) { p.catch(e => { window.__playErr = String(e).slice(0,120); }); }
    return 'called';
  } catch (e) { return 'throw:' + String(e).slice(0, 80); }
}
"""


def _frames(page):
    from watch import _clip_frames
    return _clip_frames(page)


def main() -> int:
    cfg = load_config()
    sbjct = knouon.sbjct_id_for(COURSE)
    console: list[str] = []
    failed: list[str] = []

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        ctx.on("console", lambda m: console.append(
            f"[{m.type}] {_safe(m.text)[:160]}"))
        ctx.on("requestfailed", lambda r: failed.append(
            f"{_safe(r.url)[:110]} — {r.failure}"))

        print("1) 로그인·강의실…", flush=True)
        ensure_logged_in(page, cfg)
        weeks = knouon.fetch_weeks(page, sbjct, COURSE)
        week = next(w for w in weeks if w.seq == WEEK)
        print(f"   {week.seq}주차 '{week.name}' — 진도 {week.percent}%", flush=True)

        print("2) 강의 화면 열기…", flush=True)
        knouon.open_week(page, week)
        frames = _frames(page)
        print(f"   재생 프레임 {len(frames)}개", flush=True)
        for i, fr in enumerate(frames):
            print(f"     [{i}] {_safe(fr.url)[:100]}", flush=True)

        if not frames:
            print("   프레임이 없습니다.", flush=True)
            return 1

        print("\n3) 지금 상태(재생 전) —— 화면도 함께 봐 주세요", flush=True)
        import json as _json
        for i, fr in enumerate(frames):
            d = _json.loads(fr.evaluate(_DIAG_JS))
            tag = "오리엔테이션" if i == 0 else "본강의"
            print(f"   [{i}] {tag}: 길이={d.get('dur')} 위치={d.get('pos')} "
                  f"멈춤={d.get('paused')} 받음={d.get('ready')} "
                  f"네트워크={d.get('net')} 오류={d.get('err')}", flush=True)
            if d.get("overlays"):
                for o in d["overlays"]:
                    print(f"        덮개: {o['cls']} | {o['txt']}", flush=True)

        print("\n4) 본강의 정지 → 오리엔테이션 재생 시도", flush=True)
        for i, fr in enumerate(frames):
            if i != 0:
                try:
                    fr.evaluate("() => { const v=document.querySelector('video');"
                                " if (v) v.pause(); }")
                except Exception:
                    pass
        print(f"   play() 호출: {frames[0].evaluate(_PLAY_JS, 2.0)}", flush=True)

        for loop in range(WATCH_LOOPS):
            time.sleep(10)
            fr = _frames(page)
            if not fr:
                print(f"   {(loop+1)*10:>3}초: 재생 프레임이 사라졌다", flush=True)
                continue
            d = _json.loads(fr[0].evaluate(_DIAG_JS))
            if d.get("noVideo"):
                print(f"   {(loop+1)*10:>3}초: <video> 가 없다", flush=True)
                continue
            print(f"   {(loop+1)*10:>3}초: 위치={d.get('pos'):.1f} "
                  f"멈춤={d.get('paused')} 배속={d.get('rate')} "
                  f"받음={d.get('ready')} 네트워크={d.get('net')} "
                  f"버퍼={d.get('buffered')} 오류={d.get('err')}", flush=True)
            if d.get("errMsg"):
                print(f"        오류내용: {d['errMsg']}", flush=True)
            if d.get("overlays"):
                for o in d["overlays"][:3]:
                    print(f"        덮개: {o['cls']} | {o['txt']}", flush=True)

        perr = page.evaluate("() => window.__playErr || null")
        if perr:
            print(f"\n   play() 거부 사유: {perr}", flush=True)
        print(f"\n   콘솔 {len(console)}건(끝 12건):", flush=True)
        for c in console[-12:]:
            print(f"     {c}", flush=True)
        print(f"   실패한 요청 {len(failed)}건:", flush=True)
        for f in failed[:8]:
            print(f"     {f}", flush=True)

        print("\n창을 열어 둡니다. 화면에서 무엇이 보이는지 알려 주세요.", flush=True)
        print("(재생 버튼이 있는지 · 안내 문구가 뜨는지 · 화면이 검은지)",
              flush=True)
        try:
            input("확인하셨으면 Enter…")
        except Exception:
            time.sleep(600)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
