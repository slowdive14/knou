"""Phase 3 결정적 파일럿: 클립 1개를 2배속으로 ~2.5분 재생 → 진도 적립 측정.

BEFORE(watched/prog) 기록 → 재생 → 일시정지(저장) → 팝업 닫기 → 재조회 AFTER.
이로써 (1)적립 여부 (2)2배속 위치 진행 (3)배속 적립을 한 번에 확인한다.
전체 시청이 아니라 측정용(짧게).
실행: .venv/Scripts/python.exe watch_pilot.py
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
from watch import (
    _clip_state,
    _reapply_speed,
    _start_clip,
    clip_inventory,
    open_player,
)

TARGET_COURSE = "이산수학"
TARGET_SEQ = 15
PLAY_SECONDS = 360   # 300초 저장주기를 확실히 통과시키기 위함
SPEED = 2.0


def _get_lec(page, course):
    return next((l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ), None)


def main() -> None:
    cfg = load_config()
    saves = []
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        def on_req(req):
            if "registerUSTStudyRslt" in req.url:
                pd = req.post_data or ""
                # timeSec/vidoLocSec/vidoSpd/state 만 추려서
                bits = {k: v for k, v in (kv.split("=", 1) for kv in pd.split("&") if "=" in kv)
                        if k in ("timeSec", "vidoLocSec", "vidoSpd", "state", "timeLectPldcTocNo")}
                saves.append((time.strftime("%H:%M:%S"), bits))

        ctx.on("request", on_req)
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        before = _get_lec(page, course)
        print(f"BEFORE: {before.seq}강 watched={before.watched_min}분 "
              f"total={before.total_min}분 prog={before.prog_rt}% done={before.video_done}")

        popup = open_player(page, before)

        # 실제 영상이 든 클립 인벤토리 (차시마다 1~3개로 다름)
        inv = clip_inventory(popup)
        actives = [c["index"] for c in inv if c["has"]]
        print(f"\n클립 인벤토리({len(inv)}슬롯, 실제영상 {len(actives)}개):")
        for c in inv:
            print(f"   슬롯{c['index']} has={c['has']} dur={c['dur']} src={c['src'][:40]}")
        if not actives:
            print("⚠️ 재생 가능한 클립 없음"); popup.close(); ctx.close(); return

        # 진짜 '미시청' 클립을 찾을 때까지 actives 순회(완청 클립은 건너뜀)
        idx = None
        for cand in actives:
            print(f"\n슬롯{cand} 재생 시도(2배속)…")
            status = _start_clip(popup, cand, SPEED)
            print(f"  _start_clip → {status}")
            if status == "playing":
                idx = cand
                break
            elif status == "already_complete":
                print("  (이미 완청 → 다음 클립)")
        if idx is None:
            print("⚠️ 미시청 클립 없음(모두 완청) → 측정 불가"); popup.close(); ctx.close(); return

        print(f"\n측정 대상 슬롯{idx} — {PLAY_SECONDS}초 연속 관찰(300초 저장주기 통과 목표):")
        ended = False
        for t in range(0, PLAY_SECONDS + 1, 15):
            st = _clip_state(popup, idx)
            print(f"  +{t:>3}s pos={st.get('pos')} dur={st.get('dur')} "
                  f"rate={st.get('rate')} paused={st.get('paused')} ended={st.get('ended')}")
            if st.get("ended"):
                ended = True
                print(f"  → 클립{idx} 종료(ended) 감지")
                break
            # 배속이 1.0 으로 떨어졌으면 위치 유지한 채 배속만 재설정(재시작 금지)
            if st.get("rate") and float(st.get("rate")) < SPEED - 0.1:
                _reapply_speed(popup, idx, SPEED)
            if t < PLAY_SECONDS:
                time.sleep(15)
        print(f"종료감지={ended}")

        # 일시정지 → 저장 트리거 (각 클립 프레임에서 fnPlayStop)
        print("\n일시정지(저장 트리거)…")
        for fr in popup.frames:
            if "ViewPlayer" in (fr.url or ""):
                try:
                    fr.evaluate("() => { if(typeof fnPlayStop==='function') fnPlayStop(); }")
                except Exception:
                    pass
        time.sleep(4)

        print(f"\n진도저장 XHR {len(saves)}건:")
        for s in saves:
            print("  ", s)

        popup.close()
        time.sleep(2)

        # 재조회 (원본 page 는 그대로 study 페이지)
        after = _get_lec(page, course)
        print(f"\nAFTER : {after.seq}강 watched={after.watched_min}분 "
              f"total={after.total_min}분 prog={after.prog_rt}% done={after.video_done}")
        print(f"\nΔ watched={after.watched_min - before.watched_min}분  "
              f"Δ prog={after.prog_rt - before.prog_rt}%")
        ctx.close()


if __name__ == "__main__":
    main()
