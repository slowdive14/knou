"""[quiz_html] 강의 퀴즈 복습용 단일 HTML 페이지 생성 (순수).

render_quiz_html(lectures, title) → 자체완결 HTML 문자열(외부 의존 없음, 더블클릭
으로 열림). 좌측 강의 목록 · 문제 카드 · 보기 선택 · '정답 보기'(정답+해설) ·
진행률 · 강의 이동 · 초기화(localStorage). 정답/해설은 기본 숨김(hidden)으로,
'정답 보기'를 눌러야 공개된다 → 다시 풀어보기 가치 보존.

입력 lectures: [{"course","seq","name","questions":[표준 문항...]}, ...]
표준 문항: quizbank/quiz_capture 형식({qid,source,qtype,question,options,answer_no,
answer_text,explanation}).
⚠️ 모든 동적 텍스트는 HTML 이스케이프. 비밀값은 담기지 않는다.
"""
from __future__ import annotations

import html as _html


def _esc(s) -> str:
    return _html.escape("" if s is None else str(s))


def _escattr(s) -> str:
    return _html.escape("" if s is None else str(s), quote=True)


def _render_option(o: dict) -> str:
    no = o.get("no")
    return (f'<button class="opt" data-no="{_escattr(no)}">'
            f'<span class="opt-no">{_esc(no)}</span>'
            f'<span class="opt-text">{_esc(o.get("text"))}</span></button>')


def _render_card(num: int, q: dict) -> str:
    opts = "".join(_render_option(o) for o in (q.get("options") or []))
    ans_no = q.get("answer_no")
    ans_attr = _escattr(ans_no) if ans_no is not None else ""
    if ans_no is not None:
        correct = f"정답: {_esc(ans_no)}. {_esc(q.get('answer_text'))}"
    elif q.get("answer_text"):
        correct = f"정답: {_esc(q.get('answer_text'))}"
    else:
        correct = "정답 정보 없음"
    badge = _esc(q.get("source") or "")
    badge_html = f'<span class="badge">{badge}</span>' if badge else ""
    return (
        f'<div class="q-card" data-qid="{_escattr(q.get("qid"))}" '
        f'data-answer-no="{ans_attr}">'
        f'<div class="q-head"><span class="qnum">Q{num}</span>{badge_html}</div>'
        f'<div class="q-text">{_esc(q.get("question"))}</div>'
        f'<div class="opts">{opts}</div>'
        f'<div class="q-actions"><button class="btn-reveal">정답 보기</button></div>'
        f'<div class="answer-box" hidden>'
        f'<div class="ans-correct">{correct}</div>'
        f'<div class="expl">{_esc(q.get("explanation") or "")}</div>'
        f'</div>'
        f'</div>'
    )


def _lec_title(lec: dict) -> str:
    parts = [str(lec.get("seq", "")) + "강", lec.get("name") or ""]
    course = lec.get("course") or ""
    head = " · ".join(p for p in parts if p)
    return f"{course} · {head}" if course else head


def _render_sidebar_item(idx: int, lec: dict) -> str:
    return (f'<button class="lec-item" data-idx="{idx}">'
            f'<span class="li-seq">{_esc(lec.get("seq"))}강</span>'
            f'<span class="li-name">{_esc(lec.get("name"))}</span></button>')


def _render_lecture(idx: int, lec: dict) -> str:
    qs = lec.get("questions") or []
    cards = "".join(_render_card(i + 1, q) for i, q in enumerate(qs))
    if not cards:
        cards = '<div class="empty">이 강의에 저장된 문제가 없습니다.</div>'
    return (f'<div class="lecture" data-idx="{idx}" '
            f'data-title="{_escattr(_lec_title(lec))}">'
            f'<h2 class="lec-h">{_esc(_lec_title(lec))}</h2>{cards}</div>')


def render_quiz_html(lectures, title: str = "강의 퀴즈") -> str:
    """강의 묶음(lectures) → 단일 자체완결 HTML 문자열."""
    lectures = list(lectures or [])
    side_items = "".join(_render_sidebar_item(i, l) for i, l in enumerate(lectures))
    total_q = sum(len(l.get("questions") or []) for l in lectures)
    side_sub = f"{len(lectures)}강 · 총 {total_q}문제"
    if lectures:
        secs = "".join(_render_lecture(i, l) for i, l in enumerate(lectures))
    else:
        secs = ('<div class="empty">저장된 문제가 없습니다. '
                '이수를 실행하면 강의 문제가 모입니다.</div>')

    head = (
        '<!DOCTYPE html>\n<html lang="ko">\n<head>\n'
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        f'<title>{_esc(title)}</title>\n'
        '<style>\n' + _CSS + '\n</style>\n</head>\n<body>\n'
    )
    body = (
        '<aside class="sidebar">'
        f'<div class="side-title">{_esc(title)}</div>'
        f'<div class="side-sub">{_esc(side_sub)}</div>'
        f'<nav class="lec-nav">{side_items}</nav>'
        '</aside>'
        '<main class="main">'
        '<header class="topbar">'
        '<div class="lec-title" id="lecTitle"></div>'
        '<div class="progress">'
        '<span class="progress-text" id="progressText">0 / 0</span>'
        '<div class="progress-bar"><i id="progressFill"></i></div>'
        '</div>'
        '</header>'
        '<div class="navrow">'
        '<button id="prevLec" class="navbtn">이전 강의</button>'
        '<button id="nextLec" class="navbtn primary">다음 강의</button>'
        '<button id="resetLec" class="navbtn">현재 강 초기화</button>'
        '<button id="resetAll" class="navbtn">전체 초기화</button>'
        '</div>'
        f'<section class="lectures">{secs}</section>'
        '</main>'
    )
    return head + body + '<script>\n' + _JS + '\n</script>\n</body>\n</html>\n'


# ---------------------------------------------------------------------------
# 정적 CSS / JS (브레이스 충돌 피하려 f-string 아님)
# ---------------------------------------------------------------------------
_CSS = r"""
* { box-sizing: border-box; }
body { margin: 0; display: flex; min-height: 100vh; font-family: "Malgun Gothic","맑은 고딕",system-ui,sans-serif; color: #1f2a26; background: #f4f7f5; }
.sidebar { width: 250px; flex: 0 0 250px; background: #15463a; color: #cfe3da; padding: 20px 14px; overflow-y: auto; }
.side-title { font-size: 19px; font-weight: 700; color: #fff; }
.side-sub { font-size: 12px; color: #9cc3b5; margin: 6px 0 16px; }
.lec-nav { display: flex; flex-direction: column; gap: 8px; }
.lec-item { text-align: left; background: #1c5747; border: none; border-radius: 10px; padding: 12px 14px; color: #dfeee8; cursor: pointer; display: flex; flex-direction: column; gap: 2px; }
.lec-item:hover { background: #226a55; }
.lec-item.active { background: #fff; color: #15463a; box-shadow: 0 2px 8px rgba(0,0,0,.15); }
.li-seq { font-weight: 700; font-size: 15px; }
.li-name { font-size: 12px; opacity: .85; }
.main { flex: 1; padding: 26px 34px; overflow-y: auto; }
.topbar { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; }
.lec-title { font-size: 30px; font-weight: 800; }
.progress { background: #fff; border: 1px solid #e3eae7; border-radius: 12px; padding: 12px 16px; min-width: 190px; box-shadow: 0 1px 4px rgba(0,0,0,.05); }
.progress-text { font-weight: 700; font-size: 14px; }
.progress-bar { height: 8px; background: #e6ece9; border-radius: 6px; margin-top: 8px; overflow: hidden; }
.progress-bar i { display: block; height: 100%; width: 0; background: linear-gradient(90deg,#1f8a5f,#e0a83a); transition: width .25s; }
.navrow { display: flex; gap: 10px; margin: 18px 0 22px; flex-wrap: wrap; }
.navbtn { background: #fff; border: 1px solid #d6ddd9; border-radius: 8px; padding: 9px 16px; cursor: pointer; font-size: 14px; }
.navbtn:hover { background: #f0f4f2; }
.navbtn.primary { background: #1f8a5f; border-color: #1f8a5f; color: #fff; }
.lecture { display: none; }
.lecture.active { display: block; }
.lec-h { font-size: 15px; color: #5b6b64; font-weight: 600; margin: 0 0 14px; }
.q-card { background: #fff; border: 1px solid #e7ece9; border-radius: 14px; padding: 22px 24px; margin-bottom: 18px; box-shadow: 0 1px 4px rgba(0,0,0,.04); }
.q-head { display: flex; justify-content: space-between; align-items: center; }
.qnum { font-weight: 800; font-size: 17px; }
.badge { background: #d7efe4; color: #1f6b50; font-size: 12px; font-weight: 700; padding: 4px 10px; border-radius: 999px; }
.q-text { font-size: 17px; font-weight: 700; margin: 14px 0 16px; line-height: 1.5; }
.opts { display: flex; flex-direction: column; gap: 10px; }
.opt { display: flex; align-items: center; gap: 12px; text-align: left; background: #f6f8f7; border: 1.5px solid #e7ece9; border-radius: 10px; padding: 14px 16px; cursor: pointer; font-size: 15px; width: 100%; }
.opt:hover { background: #eef3f1; }
.opt-no { display: inline-flex; align-items: center; justify-content: center; width: 26px; height: 26px; border-radius: 50%; background: #e6ece9; font-size: 13px; font-weight: 700; flex: 0 0 26px; }
.opt.selected { border-color: #1f8a5f; background: #eafaf2; }
.opt.correct { border-color: #1f8a5f; background: #e3f7ec; }
.opt.correct .opt-no { background: #1f8a5f; color: #fff; }
.opt.wrong { border-color: #d9534f; background: #fce8e7; }
.opt.wrong .opt-no { background: #d9534f; color: #fff; }
.q-actions { margin-top: 14px; }
.btn-reveal { background: #f3e7bf; border: 1px solid #e6d28f; border-radius: 8px; padding: 9px 16px; cursor: pointer; font-size: 14px; font-weight: 600; }
.btn-reveal:hover { background: #eedca8; }
.answer-box { margin-top: 14px; border: 1px solid #bfe6cf; border-left: 4px solid #1f8a5f; background: #f3fbf6; border-radius: 8px; padding: 14px 16px; }
.ans-correct { font-weight: 700; color: #1f6b50; }
.expl { margin-top: 8px; font-size: 14px; color: #3a463f; line-height: 1.6; white-space: pre-wrap; }
.empty { color: #7a8a83; padding: 30px 0; }
@media (max-width: 760px) { body { flex-direction: column; } .sidebar { width: 100%; flex-basis: auto; } .lec-nav { flex-direction: row; flex-wrap: wrap; } .main { padding: 18px; } .lec-title { font-size: 22px; } }
"""

_JS = r"""
(function () {
  var lectures = Array.prototype.slice.call(document.querySelectorAll('.lecture'));
  var items = Array.prototype.slice.call(document.querySelectorAll('.lec-item'));
  var KEY = 'knou_quiz_state_v1';
  var state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { state = {}; }
  var cur = 0;

  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  function markCard(card) {
    var qid = card.getAttribute('data-qid');
    var ans = card.getAttribute('data-answer-no');
    var sel = state[qid];
    card.querySelectorAll('.opt').forEach(function (btn) {
      btn.classList.remove('selected', 'correct', 'wrong');
      var no = btn.getAttribute('data-no');
      if (sel != null && String(sel) === no) {
        btn.classList.add('selected');
        if (ans) { btn.classList.add(String(sel) === ans ? 'correct' : 'wrong'); }
      }
    });
  }

  function updateProgress() {
    var lec = lectures[cur];
    var cards = lec ? lec.querySelectorAll('.q-card') : [];
    var done = 0;
    cards.forEach(function (c) { if (state[c.getAttribute('data-qid')] != null) done++; });
    var t = document.getElementById('progressText');
    var f = document.getElementById('progressFill');
    if (t) t.textContent = done + ' / ' + cards.length;
    if (f) f.style.width = (cards.length ? (done / cards.length * 100) : 0) + '%';
  }

  function show(idx) {
    if (idx < 0 || idx >= lectures.length) return;
    cur = idx;
    lectures.forEach(function (l, i) { l.classList.toggle('active', i === idx); });
    items.forEach(function (b, i) { b.classList.toggle('active', i === idx); });
    var t = document.getElementById('lecTitle');
    if (t && lectures[idx]) t.textContent = lectures[idx].getAttribute('data-title') || '';
    updateProgress();
  }

  document.querySelectorAll('.q-card').forEach(function (card) {
    markCard(card);
    card.querySelectorAll('.opt').forEach(function (btn) {
      btn.addEventListener('click', function () {
        state[card.getAttribute('data-qid')] = btn.getAttribute('data-no');
        save(); markCard(card); updateProgress();
      });
    });
    var rev = card.querySelector('.btn-reveal');
    var box = card.querySelector('.answer-box');
    if (rev && box) { rev.addEventListener('click', function () { box.hidden = !box.hidden; }); }
  });

  items.forEach(function (b) {
    b.addEventListener('click', function () { show(parseInt(b.getAttribute('data-idx'), 10)); });
  });
  var prev = document.getElementById('prevLec');
  var next = document.getElementById('nextLec');
  if (prev) prev.addEventListener('click', function () { show(cur - 1); });
  if (next) next.addEventListener('click', function () { show(cur + 1); });
  var rl = document.getElementById('resetLec');
  if (rl) rl.addEventListener('click', function () {
    if (!lectures[cur]) return;
    lectures[cur].querySelectorAll('.q-card').forEach(function (c) {
      delete state[c.getAttribute('data-qid')]; markCard(c);
    });
    save(); updateProgress();
  });
  var ra = document.getElementById('resetAll');
  if (ra) ra.addEventListener('click', function () {
    state = {}; save();
    document.querySelectorAll('.q-card').forEach(markCard); updateProgress();
  });

  if (lectures.length) show(0);
})();
"""
