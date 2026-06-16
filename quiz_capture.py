"""[quiz_capture] 플레이어 DOM 에서 돌발퀴즈/형성평가 문항·정답·해설 스캔.

순수 로직(단위테스트):
  - parse_scanned(raw)  : 스캔 결과(dict) → 표준 문항 목록(quizbank 형식).
                          정답 번호/텍스트 보강, qtype 기본값, 식별불가 문항 스킵.

IO(수동 검증 게이트):
  - scan_quiz(frame, source) : `.exam-content-box`/`#quiz_*` DOM 을 읽어 raw 생성
                               → parse_scanned. **답 제출 후** 호출해야 정답·해설이
                               채워진다. 실패해도 []를 돌려 파이프라인을 막지 않는다.

⚠️ 정답(exqsCansCn)·해설(exqsExplCn)은 답을 제출한 뒤에야 DOM 에 노출된다.
⚠️ 문항 본문(stem) 셀렉터는 강의 템플릿에 따라 다를 수 있어 라이브 1회 확인 필요.
"""
from __future__ import annotations

import json

from quizbank import normalize_question


def _resolve_answer(q: dict) -> dict:
    """정답 텍스트(exqsCansCn)로 정답 보기 번호를 보강한다(가능할 때).

    - 정답이 숫자면 같은 번호 보기를 찾아 answer_no 설정 + answer_text 를 그 보기
      텍스트로 보강(더 읽기 좋음).
    - 정답이 보기 텍스트와 일치하면 그 보기의 번호를 answer_no 로 설정.
    이미 answer_no 가 있거나 정답이 비어 있으면 그대로 둔다.
    """
    at = (q.get("answer_text") or "").strip()
    if not at or q.get("answer_no") is not None:
        return q
    if at.isdigit():
        no = int(at)
        for o in q["options"]:
            if o["no"] == no:
                return {**q, "answer_no": no, "answer_text": o["text"] or at}
        return q
    for o in q["options"]:
        if o["text"] and o["text"].strip() == at:
            return {**q, "answer_no": o["no"]}
    return q


def parse_scanned(raw) -> list:
    """스캔 raw(dict) → 표준 문항 목록. 식별자(exqsId) 없는 문항은 건너뛴다.

    raw = {"source": "형성평가"|"돌발퀴즈", "questions": [
              {"exqsId","exqsDc","exqsTc","question","options":[{no,text}],
               "answer_text","explanation"}, ...]}
    """
    raw = raw or {}
    source = raw.get("source") or ""
    out = []
    for q in (raw.get("questions") or []):
        q = dict(q or {})
        if not q.get("source"):
            q["source"] = source
        if not q.get("qtype") and q.get("options"):
            q["qtype"] = "객관식"
        try:
            norm = normalize_question(q)
        except ValueError:
            continue          # exqsId 없음 → 식별 불가, 스킵
        out.append(_resolve_answer(norm))
    return out


# ---------------------------------------------------------------------------
# IO (수동 검증) — 브라우저 프레임 DOM 스캔
# ---------------------------------------------------------------------------
# `.exam-content-box`(형성평가)·`#quiz_*`(돌발퀴즈) 안 각 form 에서 문항을 읽는다.
# 보기 텍스트는 `.exam-answer-message` textContent(HWP json 은 HTML 주석이라 자동
# 제외됨). 정답/해설은 풀이 후 채워지는 `[name=exqsCansCn]`/`.exqsExplCn`.
_QUIZ_SCAN_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const boxes = document.querySelectorAll(".exam-content-box, [id^='quiz_']");
  const qs = [];
  boxes.forEach(box => {
    box.querySelectorAll("form").forEach(f => {
      const g = n => { const e = f.querySelector('input[name="'+n+'"]'); return e ? e.value : null; };
      const exqsId = g('exqsId');
      if (!exqsId) return;
      const options = [];
      f.querySelectorAll('.answerCh').forEach(r => {
        const lab = r.closest('label') || r.parentElement;
        const msg = lab ? lab.querySelector('.exam-answer-message') : null;
        const text = norm(msg ? msg.textContent : (lab ? lab.textContent : ''));
        options.push({ no: parseInt(r.value, 10), text: text });
      });
      // 문항 본문(템플릿마다 다를 수 있어 후보 셀렉터 순차 시도)
      let stem = '';
      const qel = f.querySelector('.exam-question, .question, .exam-tit, .tit, .exam-title-text');
      if (qel) stem = norm(qel.textContent);
      const cans = f.querySelector('[name=exqsCansCn]');
      const expl = f.querySelector('.exqsExplCn');
      qs.push({
        exqsId: exqsId, exqsDc: g('exqsDc'), exqsTc: g('exqsTc'),
        question: stem, options: options,
        answer_text: norm(cans ? cans.textContent : ''),
        explanation: norm(expl ? expl.textContent : ''),
      });
    });
  });
  return JSON.stringify({ questions: qs });
}
"""


def scan_quiz(frame, source: str = "") -> list:
    """frame(또는 popup) DOM 에서 문항을 읽어 표준 문항 목록 반환.

    답 제출 후 호출해야 정답·해설이 채워진다. 어떤 실패든 []를 돌려
    이수/시청 흐름을 막지 않는다(부수효과 격리).
    """
    try:
        raw = json.loads(frame.evaluate(_QUIZ_SCAN_JS))
    except Exception:
        return []
    raw["source"] = source
    return parse_scanned(raw)
