"""Phase 3 1차시 풀 파일럿: watch_lecture 로 한 차시를 끝까지 자동 시청.

BEFORE 기록 → watch_lecture(2배속, 끝까지) → AFTER 재조회 → Δ/done 검증.
진도저장 XHR(registerUSTStudyRslt)을 함께 캡처해 적립 흐름을 확인한다.
브라우저는 watch_lecture 의 finally + ctx.close 로 스스로 닫힌다(좀비 방지).

⚠️ 실제로 ~58분(2배속) 걸리는 긴 실행이다. 백그라운드 + -u 권장:
   .venv/Scripts/python.exe -u watch_one.py
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
from watch import is_complete, watch_lecture

TARGET_COURSE = "이산수학"
TARGET_SEQ = 15
SPEED = 2.0


def _get_lec(page, course):
    return next((l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ), None)


def main() -> None:
    cfg = load_config()
    saves = []
    t0 = time.time()

    def on_req(req):
        if "registerUSTStudyRslt" in req.url:
            pd = req.post_data or ""
            bits = {k: v for k, v in (kv.split("=", 1) for kv in pd.split("&") if "=" in kv)
                    if k in ("timeSec", "vidoLocSec", "vidoSpd", "state", "timeLectPldcTocNo")}
            saves.append((time.strftime("%H:%M:%S"), bits))
            print(f"  💾 SAVE {time.strftime('%H:%M:%S')} {bits}", flush=True)

    last = {"n": 0}

    def on_progress(st):
        last["n"] += 1
        # 60초마다(폴링 4회당 1회) 한 줄 출력
        if last["n"] % 4 == 1:
            el = int(time.time() - t0)
            print(f"  +{el:>4}s pos={st.get('pos')} dur={st.get('dur')} "
                  f"rate={st.get('rate')} paused={st.get('paused')} "
                  f"ended={st.get('ended')}", flush=True)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.on("request", on_req)
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        before = _get_lec(page, course)
        print(f"BEFORE: {before.seq}강 watched={before.watched_min}분 "
              f"total={before.total_min}분 prog={before.prog_rt}% "
              f"done={before.video_done} complete={is_complete(before)}", flush=True)

        print(f"\n▶ watch_lecture 시작 (배속 {SPEED}, 끝까지)…", flush=True)
        result = watch_lecture(page, before, cfg=cfg, speed=SPEED,
                               on_progress=on_progress)
        print(f"\n결과: {result}", flush=True)

        print(f"\n진도저장 XHR {len(saves)}건", flush=True)

        # 재조회 (원본 page 는 study 페이지 유지)
        time.sleep(2)
        after = _get_lec(page, course)
        print(f"\nAFTER : {after.seq}강 watched={after.watched_min}분 "
              f"total={after.total_min}분 prog={after.prog_rt}% "
              f"done={after.video_done} complete={is_complete(after)}", flush=True)
        print(f"\nΔ watched={after.watched_min - before.watched_min}분  "
              f"Δ prog={after.prog_rt - before.prog_rt}%  "
              f"done {before.video_done}→{after.video_done}", flush=True)
        print(f"\n총 소요: {int(time.time() - t0)}초", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
