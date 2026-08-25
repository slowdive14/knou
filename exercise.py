"""Phase 3-2 — 형성평가 '연습문제' 자동 풀이 (정오답 무관).

플레이어 팝업 메인 프레임(`retrieveUSTStudy.do`)의 `.exam-content-box` 안
연습문제 문항을 모두 '응답 등록'시킨다(exam_done=Y 목표).

정오답 무관 메커니즘(docs/lms-map.md §7):
  - 각 문항 보기 1개 선택 → `.confirmAnswer` 클릭.
  - exqsTc=2 & exqsDc=3/4 의 첫 클릭은 정답검사(retrieveUSTStudyExamRslt)만 하고
    오답이면 alert("다시 한번 생각해 보세요") 후 등록 안 함(resultCnt=1).
  - 두 번째 클릭은 정오답 무관하게 registerUSTStudyExamRslt.ajax 로 등록.
  → 각 문항당 최대 2번 클릭하면 정오답 무관하게 등록된다.

⚠️ 실제 답안이 서버에 제출되는 되돌릴 수 없는 행위. 호출 측에서 사용자 동의 후 사용.
⚠️ 호출 측은 popup.on("dialog", ...)로 alert 을 accept 하고 메시지를 dialog_msgs 에
   모아 넘겨야 한다(오답 재시도 판정에 사용).
"""
from __future__ import annotations

import json
import time

# 연습문제 박스 문항 스캔(읽기). 프로토타입 오염 회피용 JSON 문자열 반환.
_SCAN_JS = r"""
() => {
  const box = document.querySelector('.exam-content-box');
  if (!box) return JSON.stringify({has: false, questions: []});
  const g = (f, n) => { const e = f.querySelector('input[name="'+n+'"]'); return e ? e.value : null; };
  const qs = [];
  box.querySelectorAll("form[id^='frm_']").forEach(f => {
    qs.push({
      id: f.getAttribute('id'),
      tespNo: g(f, 'tespNo'), exqsId: g(f, 'exqsId'),
      exqsDc: g(f, 'exqsDc'), exqsTc: g(f, 'exqsTc'),
      radios: f.querySelectorAll('.answerCh').length,
      texts: f.querySelectorAll('.answerTxt').length,
      done: !!(f.querySelector('input[name="resultCnt"]') &&
               f.querySelector('input[name="resultCnt"]').value === '1'),
    });
  });
  return JSON.stringify({has: true, questions: qs});
}
"""

# 한 문항 활성화 + 첫 보기 선택 + 확인 클릭. JSON 문자열 반환.
_ANSWER_JS = r"""
(exqsId) => {
  const out = {activated:false, selected:false, clicked:false};
  document.querySelectorAll('li.exam-number-btn').forEach(li => {
    if (li.className.split(/\s+/).indexOf(String(exqsId)) !== -1) {
      (li.querySelector('a') || li).click();
      out.activated = true;
    }
  });
  const f = document.querySelector("form[id$='_" + exqsId + "']");
  if (f) {
    const r = f.querySelector('.answerCh');
    if (r) { r.checked = true; out.selected = true; }
    const txts = f.querySelectorAll('.answerTxt');
    txts.forEach(t => { if (!t.value) t.value = '0'; });  // 서술형 대비(보통 없음)
    const btn = f.querySelector('.confirmAnswer');
    if (btn) { btn.click(); out.clicked = true; }
  }
  return JSON.stringify(out);
}
"""

# 확인 버튼만 다시 클릭(2번째 클릭 = 정오답 무관 등록).
_RECLICK_JS = r"""
(exqsId) => {
  const f = document.querySelector("form[id$='_" + exqsId + "']");
  if (!f) return 'noform';
  const btn = f.querySelector('.confirmAnswer');
  if (btn) { btn.click(); return 'clicked'; }
  return 'nobtn';
}
"""


def _exam_frame(popup):
    """연습문제 박스가 들어있는 프레임(영상 ViewPlayer 프레임 제외)을 찾는다."""
    for fr in popup.frames:
        if "ViewPlayer" in (fr.url or ""):
            continue
        try:
            n = fr.evaluate("() => document.querySelectorAll('.exam-content-box').length")
        except Exception:
            continue
        if n:
            return fr
    return None


# 연습문제 박스가 늦게 붙는 차시가 있어 한 번만 보고 '없음'으로 단정하면 안 된다.
# (실측: 2초 고정 대기 뒤 1회 확인 → '형성평가 없음(skip)' 으로 **완료 기록**되어
#  그 차시는 다시 시도조차 안 되는 상태가 됐다.)
EXAM_WAIT_MS = 15000      # 최대 대기
EXAM_POLL_MS = 1000       # 확인 간격


def wait_for_exam_frame(popup, timeout_ms: int = EXAM_WAIT_MS,
                        poll_ms: int = EXAM_POLL_MS, finder=None):
    """연습문제 프레임이 나타날 때까지 폴링하다 찾으면 반환(끝내 없으면 None).

    finder 는 테스트용 주입점(기본 `_exam_frame`). 대기는 popup.wait_for_timeout
    을 쓴다 — Playwright 가 그 동안 프레임 로딩을 계속 진행시키기 때문이다.
    """
    find = finder or _exam_frame
    waited = 0
    while True:
        fr = find(popup)
        if fr is not None:
            return fr
        if waited >= timeout_ms:
            return None
        try:
            popup.wait_for_timeout(poll_ms)
        except Exception:  # noqa: BLE001 - 창이 닫혔으면 더 기다릴 이유가 없다
            return None
        waited += poll_ms


def scan_questions(frame):
    """연습문제 문항 목록 반환(읽기). list[dict] (없으면 [])."""
    try:
        raw = frame.evaluate(_SCAN_JS)
        data = json.loads(raw)
    except Exception:
        return []
    return data.get("questions", []) if data.get("has") else []


def _is_retry_alert(msg: str) -> bool:
    msg = msg or ""
    return ("다시" in msg) or ("생각" in msg)


def solve_exercises(popup, dialog_msgs=None, settle=1.5, on_event=None):
    """연습문제 박스의 모든 문항을 정오답 무관으로 응답 등록한다.

    dialog_msgs: 호출 측 popup.on("dialog")가 채우는 메시지 리스트(공유). 오답 재시도 판정용.
    on_event(str): 진행 로그 콜백(선택).

    return: {"status", "total", "answered", "results":[{exqsId, activated, selected,
             clicked, retried, alerts}]}
    """
    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    fr = _exam_frame(popup)
    if fr is None:
        return {"status": "no_exam_box", "total": 0, "answered": 0, "results": []}

    qs = scan_questions(fr)
    if not qs:
        return {"status": "no_questions", "total": 0, "answered": 0, "results": []}

    results = []
    answered = 0
    for q in qs:
        exqsId = q["exqsId"]
        before = len(dialog_msgs) if dialog_msgs is not None else 0
        try:
            res = json.loads(fr.evaluate(_ANSWER_JS, exqsId))
        except Exception as e:
            res = {"evalErr": str(e)[:60]}
        time.sleep(settle)

        new_msgs = dialog_msgs[before:] if dialog_msgs is not None else []
        retried = False
        # 오답 alert("다시 한번 생각해 보세요") → 한 번 더 클릭하면 정오답 무관 등록
        if any(_is_retry_alert(m) for m in new_msgs):
            try:
                fr.evaluate(_RECLICK_JS, exqsId)
            except Exception:
                pass
            retried = True
            time.sleep(settle)
            new_msgs = dialog_msgs[before:] if dialog_msgs is not None else new_msgs

        ok = bool(res.get("clicked")) and bool(res.get("selected"))
        if ok:
            answered += 1
        results.append({"exqsId": exqsId, "activated": res.get("activated"),
                        "selected": res.get("selected"), "clicked": res.get("clicked"),
                        "retried": retried, "alerts": list(new_msgs)})
        log(f"Q(exqsId={exqsId}) selected={res.get('selected')} "
            f"clicked={res.get('clicked')} retried={retried} alerts={new_msgs}")

    return {"status": "ok", "total": len(qs), "answered": answered, "results": results}
