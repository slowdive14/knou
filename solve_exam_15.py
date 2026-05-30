"""15강 연습문제 자동 풀이 테스트(정오답 무관) → exam_done 전환 검증.

영상은 이미 완청(done=True), 연습문제만 미완인 15강으로 1차 테스트한다.
BEFORE 기록 → 플레이어 열기 → solve_exercises → AFTER 재조회 → exam_done 변화 확인.
제출 XHR(registerUSTStudyExamRslt)과 alert 메시지를 함께 캡처한다.
실행: .venv/Scripts/python.exe -u solve_exam_15.py
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
from exercise import scan_questions, solve_exercises, _exam_frame
from recon import launch_context
from watch import open_player

TARGET_COURSE = "이산수학"
TARGET_SEQ = 15


def _get_lec(page, course):
    return next((l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ), None)


def main() -> None:
    cfg = load_config()
    submits = []
    dialog_msgs = []

    def on_req(req):
        if "registerUSTStudyExamRslt" in req.url:
            pd = req.post_data or ""
            bits = {k: v for k, v in (kv.split("=", 1) for kv in pd.split("&") if "=" in kv)
                    if k in ("tespNo", "exqsId", "ansCn", "examApexNo", "lectPldcTocNo")}
            submits.append((time.strftime("%H:%M:%S"), bits))
            print(f"  📝 SUBMIT {time.strftime('%H:%M:%S')} {bits}", flush=True)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ctx.on("request", on_req)
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        before = _get_lec(page, course)
        print(f"BEFORE: {before.seq}강 영상done={before.video_done} "
              f"연습문제done={before.exam_done}", flush=True)

        popup = open_player(page, before)

        def on_dialog(d):
            dialog_msgs.append(d.message)
            print(f"  💬 ALERT: {d.message!r}", flush=True)
            try:
                d.accept()
            except Exception:
                pass

        popup.on("dialog", on_dialog)
        time.sleep(2)

        fr = _exam_frame(popup)
        if fr is None:
            print("⚠️ 연습문제 박스 프레임을 못 찾음", flush=True)
            popup.close(); ctx.close(); return
        qs = scan_questions(fr)
        print(f"\n연습문제 문항 {len(qs)}개 발견:", flush=True)
        for q in qs:
            print(f"   {q['id']} exqsDc={q['exqsDc']} exqsTc={q['exqsTc']} "
                  f"라디오={q['radios']} done={q['done']}", flush=True)

        print(f"\n▶ 자동 풀이 시작(정오답 무관)…", flush=True)
        result = solve_exercises(popup, dialog_msgs=dialog_msgs,
                                 on_event=lambda m: print("  ·", m, flush=True))
        print(f"\n결과: status={result['status']} "
              f"answered={result['answered']}/{result['total']}", flush=True)

        print(f"\n제출 XHR {len(submits)}건, alert {len(dialog_msgs)}건", flush=True)

        # 재스캔(완료표시 변화 확인)
        time.sleep(2)
        qs2 = scan_questions(fr)
        done2 = sum(1 for q in qs2 if q.get("done"))
        print(f"재스캔: {done2}/{len(qs2)} 문항 resultCnt=1(시도됨)", flush=True)

        popup.close()
        time.sleep(2)

        after = _get_lec(page, course)
        print(f"\nAFTER : {after.seq}강 영상done={after.video_done} "
              f"연습문제done={after.exam_done}", flush=True)
        print(f"\nΔ 연습문제done {before.exam_done}→{after.exam_done}", flush=True)
        ctx.close()


if __name__ == "__main__":
    main()
