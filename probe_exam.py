"""읽기 전용: 연습문제(형성평가) 박스 구조를 캡처한다. **아무것도 제출하지 않음.**

대상: 이산수학 15강(영상 이미 완청, 연습문제만 미완) — 연습문제 자동화 설계용 정찰.
플레이어 팝업을 열고 부모 프레임의 `.exam-content-box`를 스캔해
  - 문항 수 / 각 문항 tespNo·exqsId·exqsDc·exqsTc·라디오수
  - 현재 완료표시(mark_*) 클래스
를 출력한다(제출/클릭 없음). 실행: .venv/Scripts/python.exe -u probe_exam.py
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
TARGET_SEQ = 15

# 연습문제 박스를 스캔(읽기 전용). 프로토타입 오염 회피용 JSON 문자열 반환.
_SCAN_JS = r"""
() => {
  const out = {boxes: 0, title: '', confirmBtns: 0, questions: [], marks: []};
  out.boxes = document.querySelectorAll('.exam-content-box').length;
  const box = document.querySelector('.exam-content-box');
  if (!box) return JSON.stringify(out);
  const titleEl = box.querySelector('.content-box-title');
  out.title = titleEl ? titleEl.textContent.trim().replace(/\s+/g, ' ') : '';
  out.confirmBtns = box.querySelectorAll('.confirmAnswer').length;

  const g = (f, n) => { const e = f.querySelector('input[name="' + n + '"]'); return e ? e.value : null; };
  const forms = box.querySelectorAll("form[name^='frm_']");
  for (const f of forms) {
    out.questions.push({
      name: f.getAttribute('name'),
      tespNo: g(f, 'tespNo'),
      exqsId: g(f, 'exqsId'),
      examApexNo: g(f, 'examApexNo'),
      exqsDc: g(f, 'exqsDc'),
      exqsTc: g(f, 'exqsTc'),
      lectPldcTocNo: g(f, 'lectPldcTocNo'),
      radios: f.querySelectorAll('.answerCh').length,
      texts: f.querySelectorAll('.answerTxt').length,
      confirm: !!f.querySelector('.confirmAnswer'),
    });
  }
  // 완료표시: mark_* (답변 완료 시 클래스 변화 추정)
  box.querySelectorAll("[id^='mark_']").forEach(li => {
    out.marks.push({id: li.id, cls: li.className.trim()});
  });
  // 번호 버튼(Q1..QN) 현재 active/완료 상태
  out.numbers = [];
  box.querySelectorAll("[id^='numbering_']").forEach(li => {
    out.numbers.push({id: li.id, cls: li.className.trim(),
                      txt: (li.textContent || '').trim()});
  });
  return JSON.stringify(out);
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
        print(f"대상: {course.name} {lec.seq}강 영상done={lec.video_done} "
              f"연습문제done={lec.exam_done}", flush=True)

        popup = open_player(page, lec)
        time.sleep(2)
        print(f"팝업 프레임 {len(popup.frames)}개", flush=True)

        found = False
        for i, fr in enumerate(popup.frames):
            url = fr.url or ""
            if "ViewPlayer" in url:
                continue  # 영상 클립 프레임은 제외
            try:
                res = json.loads(fr.evaluate(_SCAN_JS))
            except Exception as e:
                continue
            if not res.get("boxes"):
                continue
            found = True
            print(f"\n[frame {i}] url={url[:60]}", flush=True)
            print(f"  연습문제 박스: {res['boxes']}개  제목={res['title']!r}  "
                  f"confirm버튼={res['confirmBtns']}개", flush=True)
            print(f"  문항 {len(res['questions'])}개:", flush=True)
            for q in res["questions"]:
                print(f"    {q['name']} tespNo={q['tespNo']} exqsId={q['exqsId']} "
                      f"exqsDc={q['exqsDc']} exqsTc={q['exqsTc']} "
                      f"라디오={q['radios']} 텍스트={q['texts']} confirm={q['confirm']}",
                      flush=True)
            print(f"  완료표시 mark_*: ", flush=True)
            for m in res.get("marks", []):
                print(f"    {m['id']} cls={m['cls']!r}", flush=True)
            print(f"  번호버튼:", flush=True)
            for n in res.get("numbers", []):
                print(f"    {n['id']} cls={n['cls']!r} txt={n['txt']!r}", flush=True)

        if not found:
            print("\n⚠️ 연습문제 박스를 못 찾음 — 프레임 URL 목록:", flush=True)
            for i, fr in enumerate(popup.frames):
                print(f"   frame{i}: {(fr.url or '')[:80]}", flush=True)
            popup.screenshot(path="recon_shots/exam_probe.png")
            print("screenshot → recon_shots/exam_probe.png", flush=True)

        popup.close()
        ctx.close()


if __name__ == "__main__":
    main()
