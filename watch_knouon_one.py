"""바이오통계학 한 주차를 끝까지 자동 시청한다(검증용 실행기).

`knouon.watch_week` 를 실제 계정으로 돌려 보는 스크립트다. 전자캠퍼스의
`watch_one.py` 와 같은 자리에 있다.

여기서 확인하려는 것:
  1. 주차 하나를 끝까지 봤을 때 진도율이 어디까지 오르는가
  2. **'이수 완료'로 판정되는 기준**이 무엇인가(knouon.COMPLETE_PERCENT 조정용)

⚠️ **실제 서버에 재생 기록이 남는다.** 되돌릴 수 없다.

실행:
    .venv/Scripts/python.exe watch_knouon_one.py [주차번호]
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

import knouon
from auth import ensure_logged_in
from config import load_config
from recon import launch_context

COURSE = "바이오통계학"


def main(argv=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    target = int(argv[0]) if argv else 1
    cfg = load_config()
    sbjct = knouon.sbjct_id_for(COURSE)
    if not sbjct:
        print(f"{COURSE} 은 knouon 과목이 아닙니다.", flush=True)
        return 1

    t0 = time.time()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        print("1) 로그인 확보…", flush=True)
        ensure_logged_in(page, cfg)

        print("2) 주차 목록…", flush=True)
        weeks = knouon.fetch_weeks(page, sbjct, COURSE)
        print(f"   {len(weeks)}주차 · 남은 주차 "
              f"{len(knouon.unwatched(weeks))}개", flush=True)
        week = next((w for w in weeks if w.seq == target), None)
        if week is None:
            print(f"   {target}주차를 찾지 못했습니다.", flush=True)
            return 1
        print(f"   대상: {week.seq}주차 '{week.name}' — 진도 {week.percent}%",
              flush=True)

        def on_progress(st):
            pos, dur = st.get("pos"), st.get("dur")
            if isinstance(pos, (int, float)) and isinstance(dur, (int, float)):
                print(f"      {pos:.0f}/{dur:.0f}초 "
                      f"({pos / dur * 100:.1f}%) 배속={st.get('rate')} "
                      f"· 경과 {int(time.time() - t0)}초", flush=True)

        print("3) 자동 시청 시작(2배속)…", flush=True)
        res = knouon.watch_week(page, week, cfg=cfg, on_progress=on_progress,
                                on_event=lambda m: print(f"   {m}", flush=True))
        for c in res["clips"]:
            print(f"   영상 {c['clip']}: {c['status']} "
                  f"({int(c.get('dur') or 0)}초)", flush=True)

        print("4) 진도 반영 확인…", flush=True)
        page.wait_for_timeout(5000)
        after = knouon.fetch_weeks(page, sbjct, COURSE)
        now = next((w for w in after if w.seq == target), None)
        if now:
            print(f"   {now.seq}주차: {week.percent}% → **{now.percent}%** "
                  f"· 완료판정={now.video_done}", flush=True)
            print(f"   (판정 기준 {knouon.COMPLETE_PERCENT}%)", flush=True)
        print(f"\n총 경과 {int(time.time() - t0)}초", flush=True)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
