"""[quiz_html] 강의 퀴즈 복습용 단일 HTML 페이지 생성 (순수).

render_quiz_html(lectures, title) → 자체완결 HTML 문자열(외부 의존 없음, 더블클릭
으로 열림). 강의 고르기 · 문제 카드 · 보기 선택 · '정답 보기'(정답+해설) ·
진행률 · 강의 이동 · 초기화(localStorage). 정답/해설은 기본 숨김(hidden)으로,
'정답 보기'를 눌러야 공개된다 → 다시 풀어보기 가치 보존.

디자인은 학습현황 페이지와 같은 언어(ui_theme) — 크림 페이퍼 · 잉크 활자 ·
민트(정답)/로즈(오답) 액센트, 인라인 SVG 아이콘, 화면밝기 전환.

입력 lectures: [{"course","seq","name","questions":[표준 문항...]}, ...]
표준 문항: quizbank/quiz_capture 형식({qid,source,qtype,question,options,answer_no,
answer_text,explanation}).
⚠️ 모든 동적 텍스트는 HTML 이스케이프. 비밀값은 담기지 않는다.
⚠️ JS 가 막혀도 첫 강 문제는 보인다(서버에서 active 로 내보냄).
"""
from __future__ import annotations

from quiz_lecture import lecture_label, lecture_no
from ui_theme import (
    esc as _esc,
    escattr as _escattr,
    icon as _icon,
    page_head,
    page_tail,
    theme_button,
)


def _render_option(o: dict) -> str:
    no = o.get("no")
    return (f'<button class="opt" data-no="{_escattr(no)}">'
            f'<span class="opt-no">{_esc(no)}</span>'
            f'<span class="opt-text">{_esc(o.get("text"))}</span></button>')


def _render_card(num: int, q: dict, course: str = "") -> str:
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
    # 몇 강의 내용인지 — 'N강 모아보기' 로 거를 때도 이 값을 본다.
    lec = lecture_no(q)
    lec_html = (f'<span class="badge lec">{_esc(lecture_label(lec))}</span>'
                if lec else "")
    # 모아보면 회차가 섞이므로 어디서 온 문항인지 함께 보여준다(거를 때만 보인다).
    src = str(q.get("bank_name") or "").strip()
    src_html = f'<span class="badge src">{_esc(src)}</span>' if src else ""
    # ⚠️ 지문과 코드를 반드시 실어야 한다 — 없으면 '이 프로그램의 실행결과는?'
    # 같은 문항을 풀 수가 없다(기출을 담으면서 드러난 빠짐).
    intro = str(q.get("intro") or "").strip()
    intro_html = f'<div class="q-intro">{_esc(intro)}</div>' if intro else ""
    code = str(q.get("code") or "").strip()
    code_html = f'<pre class="q-code">{_esc(code)}</pre>' if code else ""
    return (
        f'<div class="q-card card" data-qid="{_escattr(q.get("qid"))}" '
        f'data-answer-no="{ans_attr}" data-lecture="{_escattr(lec or "")}" '
        f'data-course="{_escattr(course or q.get("bank_course") or "")}">'
        f'<div class="q-head"><span class="qnum">Q{num:02d}</span>'
        f'<span class="q-tags">{lec_html}{src_html}{badge_html}</span></div>'
        f'{intro_html}'
        f'<div class="q-text">{_esc(q.get("question"))}</div>'
        f'{code_html}'
        f'<div class="opts">{opts}</div>'
        f'<div class="q-actions"><button class="chip btn-reveal">'
        f'{_icon("i-eye")}<span>정답 보기</span></button></div>'
        f'<div class="answer-box" hidden>'
        f'<div class="ans-head">{_icon("i-check", "ico sm")}정답</div>'
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


def _render_nav_item(idx: int, lec: dict) -> str:
    # 첫 강은 서버에서 미리 활성 표시 — JS 없이도 선택 상태가 보인다.
    cls = "lec-item active" if idx == 0 else "lec-item"
    n = len(lec.get("questions") or [])
    return (f'<button type="button" class="{cls}" data-idx="{idx}">'
            f'<span class="li-seq">{_esc(lec.get("seq"))}강</span>'
            f'<span class="li-name">{_esc(lec.get("name"))}</span>'
            f'<span class="li-n">{n}</span></button>')


def _render_lecture(idx: int, lec: dict) -> str:
    qs = lec.get("questions") or []
    course = str(lec.get("course") or "")
    cards = "".join(_render_card(i + 1, q, course) for i, q in enumerate(qs))
    if not cards:
        cards = ('<div class="empty"><b>이 강의에 저장된 문제가 없습니다.</b>'
                 '<span>이수를 실행하면 돌발퀴즈·형성평가 문항이 모입니다.</span></div>')
    # 첫 강은 active 로 내보낸다 → JS 가 막히거나 실패해도 문제가 보인다.
    cls = "lecture active" if idx == 0 else "lecture"
    return (f'<div class="{cls}" data-idx="{idx}" '
            f'data-course="{_escattr(course)}" '
            f'data-title="{_escattr(_lec_title(lec))}">{cards}</div>')


def filter_pairs(lectures) -> list:
    """[(과목, 강), …] — 문항이 실제로 있는 것만, 과목 안에서 차시 순으로.

    ⚠️ 차시 번호는 **과목마다 따로 도는 번호**다. 과목을 빼고 번호만 보면
       자료구조 3강(스택)이 C프로그래밍 3강에 섞여 든다.
    """
    seen = set()
    for lec in (lectures or []):
        course = str(lec.get("course") or "")
        for q in (lec.get("questions") or []):
            n = lecture_no(q)
            if n:
                seen.add((course, n))
    return sorted(seen)


def lecture_filter(lectures) -> str:
    """'강 모아보기' 칩 줄 — 회차를 가로질러 그 강의 문항만 남긴다.

    모든 과목의 칩을 한 줄에 담아 두고, 화면에서는 지금 보고 있는 과목의 칩만
    보여준다(과목을 옮길 때마다 페이지를 다시 만들 수는 없다).
    """
    pairs = filter_pairs(lectures)
    if len(pairs) < 2:
        return ""
    chips = "".join(
        f'<button type="button" class="lf" data-course="{_escattr(c)}" '
        f'data-lec="{n}">{_esc(lecture_label(n))}</button>' for c, n in pairs)
    return ('<nav class="lec-filter"><span class="lf-lab">강 모아보기</span>'
            '<button type="button" class="lf active" data-lec="0">전체</button>'
            f'{chips}</nav>')


def render_quiz_html(lectures, title: str = "강의 퀴즈") -> str:
    """강의 묶음(lectures) → 단일 자체완결 HTML 문자열."""
    lectures = list(lectures or [])
    nav = "".join(_render_nav_item(i, l) for i, l in enumerate(lectures))
    total_q = sum(len(l.get("questions") or []) for l in lectures)
    sub = f"{len(lectures)}강 · 총 {total_q}문제"
    # 첫 강 제목·문제수는 서버에서 채운다(JS 실패 시에도 빈 헤더가 되지 않게).
    first = lectures[0] if lectures else None
    first_title = _lec_title(first) if first else ""
    first_n = len(first.get("questions") or []) if first else 0

    if lectures:
        secs = "".join(_render_lecture(i, l) for i, l in enumerate(lectures))
    else:
        secs = ('<div class="empty"><b>저장된 문제가 없습니다.</b>'
                '<span>이수를 실행하면 강의 문제가 모입니다.</span></div>')

    body = (
        '<header class="hero"><div class="wrap">'
        f'<p class="eyebrow">{_esc(title)} · {_esc(sub)}</p>'
        f'<div class="lec-title" id="lecTitle">{_esc(first_title)}</div>'
        '<div class="metrics">'
        '<div class="metric"><span class="m-lab">푼 문제</span>'
        f'<span class="m-num" id="progressText">0 / {first_n}</span>'
        '<span class="m-rail"><i id="progressFill" style="--w:0%"></i></span>'
        f'<span class="m-lab" id="progressLabel">{first_n}문제 풀이</span></div>'
        '</div>'
        '<div class="tools">'
        f'{theme_button()}'
        f'<button type="button" class="chip" id="prevLec">{_icon("i-back")}'
        '<span>이전 강의</span></button>'
        f'<button type="button" class="chip" id="nextLec">'
        f'<span>다음 강의</span>{_icon("i-next")}</button>'
        f'<button type="button" class="chip" id="resetLec">{_icon("i-reset")}'
        '<span>현재 강 초기화</span></button>'
        f'<button type="button" class="chip" id="resetAll">{_icon("i-reset")}'
        '<span>전체 초기화</span></button>'
        '</div>'
        f'<nav class="lec-nav">{nav}</nav>'
        f'{lecture_filter(lectures)}'
        '</div></header>'
        f'<main class="wrap lectures">{secs}</main>'
        '<footer class="wrap legend">'
        '<span class="pill ok sm"><i class="dot"></i>정답</span>'
        '<span class="pill bad sm"><i class="dot"></i>오답</span>'
        '<span class="lg-tip">정답·해설은 [정답 보기]를 눌러야 열립니다 '
        '· 푼 기록은 이 브라우저에 저장됩니다</span>'
        '</footer>'
    )
    return page_head(title, _CSS) + body + page_tail(_JS)


# ---------------------------------------------------------------------------
# 페이지별 CSS / JS (공통 부분은 ui_theme)
# ---------------------------------------------------------------------------
_CSS = r"""
.lec-title { font-size:clamp(26px,3.8vw,40px); font-weight:800;
  letter-spacing:-.035em; line-height:1.05; margin-top:8px; }
.lec-nav { display:flex; gap:8px; flex-wrap:wrap; margin-top:22px; }
.lec-item { display:inline-flex; align-items:center; gap:8px; font:inherit;
  font-size:13px; font-weight:600; cursor:pointer; padding:8px 12px;
  border-radius:10px; border:1px solid var(--line); background:var(--card);
  color:var(--ink2); transition:border-color .12s ease, color .12s ease,
    background .12s ease; }
.lec-item:hover { border-color:rgba(0,163,122,.45); color:var(--mint); }
.lec-item.active { background:var(--ink); border-color:var(--ink); color:var(--paper); }
.li-seq { font-family:var(--mono); font-weight:700; letter-spacing:-.04em; }
.li-name { opacity:.85; }
.li-n { font-family:var(--mono); font-size:11px; padding:1px 6px; border-radius:99px;
  background:var(--track); }
.lec-item.active .li-n { background:rgba(255,255,255,.18); }

/* 강 모아보기 — 회차가 달라도 그 강의 문항만 남긴다 */
.lec-filter { display:flex; gap:6px; flex-wrap:wrap; align-items:center;
  margin-top:12px; }
.lf-lab { font-size:12px; font-weight:700; color:var(--mute); margin-right:4px; }
.lf { font:inherit; font-size:12.5px; font-weight:700; cursor:pointer;
  padding:5px 11px; border-radius:99px; border:1px solid var(--line);
  background:var(--card); color:var(--ink2); }
.lf:hover { border-color:rgba(0,163,122,.45); color:var(--mint); }
.lf.active { background:var(--mint); border-color:var(--mint); color:#fff; }

.lectures { padding-top:8px; }
.lecture { display:none; }
.lecture.active { display:block; }
.q-card { padding:22px 24px; margin-bottom:16px; }
.q-head { display:flex; justify-content:space-between; align-items:center; }
.qnum { font-family:var(--mono); font-size:15px; font-weight:700; color:var(--mint);
  letter-spacing:-.04em; }
.q-tags { display:inline-flex; gap:6px; align-items:center; }
.badge { background:var(--paper2); color:var(--ink2); font-size:11.5px;
  font-weight:700; padding:4px 10px; border-radius:99px; }
.badge.lec { background:var(--mint-s); color:var(--mint); }
/* 출처 회차는 모아 볼 때만 — 회차별로 볼 때는 제목에 이미 적혀 있다 */
.badge.src { display:none; }
body.gathering .badge.src { display:inline-block; }
.q-text { font-size:17px; font-weight:700; margin:12px 0 16px; line-height:1.55;
  letter-spacing:-.018em; }
/* 여러 문항이 함께 쓰는 지문과, 실행결과를 묻는 문항의 코드 */
.q-intro { font-size:14px; color:var(--mute); background:rgba(0,0,0,.035);
  border-radius:8px; padding:11px 13px; margin:10px 0 0; white-space:pre-wrap; }
.q-code { font-family:Consolas,"D2Coding",monospace; font-size:13.5px;
  line-height:1.5; background:rgba(0,0,0,.055); border:1px solid rgba(0,0,0,.09);
  border-radius:8px; padding:12px 14px; margin:0 0 16px; overflow-x:auto;
  white-space:pre; }
.opts { display:flex; flex-direction:column; gap:9px; }
.opt { display:flex; align-items:center; gap:12px; text-align:left; font:inherit;
  font-size:15px; width:100%; cursor:pointer; padding:13px 15px; border-radius:11px;
  border:1.5px solid var(--line); background:var(--paper2); color:var(--ink);
  transition:border-color .12s ease, background .12s ease, transform .12s ease; }
.opt:hover { border-color:rgba(0,163,122,.4); transform:translateY(-1px); }
.opt-no { display:inline-flex; align-items:center; justify-content:center;
  width:25px; height:25px; border-radius:50%; background:var(--track);
  font-family:var(--mono); font-size:12px; font-weight:700; flex:0 0 auto; }
.opt.selected { border-color:var(--mint); background:var(--mint-s); }
.opt.correct { border-color:var(--mint); background:var(--mint-s); }
.opt.correct .opt-no { background:var(--mint); color:#fff; }
.opt.wrong { border-color:var(--rose); background:var(--rose-s); }
.opt.wrong .opt-no { background:var(--rose); color:#fff; }
.q-actions { margin-top:14px; }
.btn-reveal { padding:8px 14px; font-size:13px; }
.answer-box { margin-top:14px; border:1px solid rgba(0,163,122,.25);
  border-left:3px solid var(--mint); background:var(--mint-s); border-radius:10px;
  padding:14px 16px; }
.ans-head { display:flex; align-items:center; gap:6px; font-weight:800;
  color:var(--mint); font-size:13px; margin-bottom:6px; }
.ans-correct { font-weight:700; }
/* 해설이 길면 문제·코드가 화면 밖으로 밀려 스크롤을 오르내리게 된다.
   그래서 해설은 **자기 상자 안에서만** 굴린다(짧으면 상자가 늘지 않는다). */
.expl { margin-top:8px; font-size:14px; color:var(--ink2); line-height:1.65;
  white-space:pre-wrap; max-height:320px; overflow-y:auto;
  overscroll-behavior:contain; }
.pill.bad { background:var(--rose-s); color:var(--rose); border-color:rgba(200,69,47,.25); }
[hidden] { display:none !important; }   /* hidden 미지원 엔진에서도 정답 숨김 */

@media (max-width:820px) {
  .q-card { padding:18px; }
  .li-name { display:none; }
}
"""

_JS = r"""
(function () {
  // 구형 엔진(NodeList.forEach 없음)에서도 죽지 않게 최소 문법만 쓴다.
  function each(list, fn) {
    if (!list) return;
    for (var i = 0; i < list.length; i++) { fn(list[i], i); }
  }
  function setCls(el, name, on) {
    if (!el) return;
    var cur = ' ' + (el.className || '') + ' ';
    var has = cur.indexOf(' ' + name + ' ') >= 0;
    if (on && !has) { el.className = ((el.className || '') + ' ' + name).replace(/^\s+/, ''); }
    else if (!on && has) { el.className = cur.split(' ' + name + ' ').join(' ').replace(/^\s+|\s+$/g, ''); }
  }
  function qsa(root, sel) { return root.querySelectorAll(sel); }
  function setText(el, s) {
    if (!el) return;
    if ('textContent' in el) { el.textContent = s; } else { el.innerText = s; }
  }
  function on(el, fn) {
    if (!el) return;
    if (el.addEventListener) { el.addEventListener('click', fn, false); }
    else if (el.attachEvent) { el.attachEvent('onclick', fn); }
  }

  var lectures = [];
  each(qsa(document, '.lecture'), function (l) { lectures.push(l); });
  var items = [];
  each(qsa(document, '.lec-item'), function (b) { items.push(b); });
  var KEY = 'knou_quiz_state_v1';
  var state = {};
  try { state = JSON.parse(localStorage.getItem(KEY) || '{}') || {}; } catch (e) { state = {}; }
  var cur = 0;
  var filter = 0;          // 0 이면 회차별로, N 이면 N강만 모아 본다
  var chips = [];
  each(qsa(document, '.lf'), function (b) { chips.push(b); });

  var gatherCourse = '';

  function curCourse() {
    var l = lectures[cur];
    return l ? (l.getAttribute('data-course') || '') : '';
  }

  function inFilter(card) {
    return card.getAttribute('data-lecture') === String(filter) &&
           card.getAttribute('data-course') === gatherCourse;
  }

  // 지금 보고 있는 과목의 칩만 남긴다 — 차시 번호는 과목마다 따로 돈다.
  function syncChips() {
    var cc = curCourse(), mine = 0;
    each(chips, function (b) {
      var all = b.getAttribute('data-lec') === '0';
      var ok = all || b.getAttribute('data-course') === cc;
      b.style.display = ok ? '' : 'none';
      if (ok && !all) mine++;
    });
    var row = document.querySelector('.lec-filter');
    if (row) row.style.display = mine >= 2 ? '' : 'none';
  }

  function visibleCards() {
    var out = [];
    if (filter) {
      each(qsa(document, '.q-card'), function (c) { if (inFilter(c)) out.push(c); });
    } else {
      var lec = lectures[cur];
      each(lec ? qsa(lec, '.q-card') : [], function (c) { out.push(c); });
    }
    return out;
  }

  function save() { try { localStorage.setItem(KEY, JSON.stringify(state)); } catch (e) {} }

  function markCard(card) {
    var qid = card.getAttribute('data-qid');
    var ans = card.getAttribute('data-answer-no');
    var sel = state[qid];
    each(qsa(card, '.opt'), function (btn) {
      setCls(btn, 'selected', false);
      setCls(btn, 'correct', false);
      setCls(btn, 'wrong', false);
      var no = btn.getAttribute('data-no');
      if (sel != null && String(sel) === no) {
        setCls(btn, 'selected', true);
        if (ans) { setCls(btn, String(sel) === ans ? 'correct' : 'wrong', true); }
      }
    });
  }

  function updateProgress() {
    var cards = visibleCards();
    var done = 0;
    each(cards, function (c) { if (state[c.getAttribute('data-qid')] != null) done++; });
    setText(document.getElementById('progressText'), done + ' / ' + cards.length);
    setText(document.getElementById('progressLabel'), cards.length + '문제 풀이');
    var f = document.getElementById('progressFill');
    if (f) f.style.width = (cards.length ? (done / cards.length * 100) : 0) + '%';
  }

  function gather(n) {
    filter = n;
    gatherCourse = curCourse();
    setCls(document.body, 'gathering', !!n);
    each(chips, function (b) {
      setCls(b, 'active', b.getAttribute('data-lec') === String(n));
    });
    if (!n) { show(cur); return; }
    // 모아 볼 때는 모든 회차를 펼쳐 놓고 그 강의 문항만 남긴다.
    each(lectures, function (l) {
      var any = 0;
      each(qsa(l, '.q-card'), function (c) {
        var ok = inFilter(c);
        c.style.display = ok ? '' : 'none';
        if (ok) any++;
      });
      setCls(l, 'active', any > 0);
    });
    each(items, function (b) { setCls(b, 'active', false); });
    setText(document.getElementById('lecTitle'),
            (gatherCourse ? gatherCourse + ' · ' : '') + n + '강 모아보기');
    updateProgress();
  }

  function show(idx) {
    if (idx < 0 || idx >= lectures.length) return;
    if (filter) {              // 회차를 고르면 모아보기는 풀린다
      filter = 0;
      setCls(document.body, 'gathering', false);
      each(chips, function (b) { setCls(b, 'active', b.getAttribute('data-lec') === '0'); });
      each(qsa(document, '.q-card'), function (c) { c.style.display = ''; });
    }
    cur = idx;
    each(lectures, function (l, i) { setCls(l, 'active', i === idx); });
    each(items, function (b, i) { setCls(b, 'active', i === idx); });
    if (lectures[idx]) {
      setText(document.getElementById('lecTitle'),
              lectures[idx].getAttribute('data-title') || '');
    }
    syncChips();
    updateProgress();
  }

  each(qsa(document, '.q-card'), function (card) {
    markCard(card);
    each(qsa(card, '.opt'), function (btn) {
      on(btn, function () {
        state[card.getAttribute('data-qid')] = btn.getAttribute('data-no');
        save(); markCard(card); updateProgress();
      });
    });
    var rev = card.querySelector('.btn-reveal');
    var box = card.querySelector('.answer-box');
    if (rev && box) {
      on(rev, function () {
        if (box.getAttribute('hidden') != null) { box.removeAttribute('hidden'); }
        else { box.setAttribute('hidden', 'hidden'); }
      });
    }
  });

  each(items, function (b) {
    on(b, function () { show(parseInt(b.getAttribute('data-idx'), 10)); });
  });
  on(document.getElementById('prevLec'), function () { show(cur - 1); });
  on(document.getElementById('nextLec'), function () { show(cur + 1); });
  each(chips, function (b) {
    on(b, function () { gather(parseInt(b.getAttribute('data-lec'), 10) || 0); });
  });
  on(document.getElementById('resetLec'), function () {
    each(visibleCards(), function (c) {
      delete state[c.getAttribute('data-qid')]; markCard(c);
    });
    save(); updateProgress();
  });
  on(document.getElementById('resetAll'), function () {
    state = {}; save();
    each(qsa(document, '.q-card'), markCard); updateProgress();
  });

  if (lectures.length) show(0);
})();
"""
