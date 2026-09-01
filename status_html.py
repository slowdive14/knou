"""[status_html] 학습 현황 → 단일 자체완결 HTML (순수).

render_status_html(courses, …) → 과목 카드 + 차시 표 한 장으로 "무엇이 만들어졌는지"
를 한눈에. 각 차시 줄에 영상이수 · 형성평가 · 예습노트 · MP3 · 강의록을 나란히 놓고,
파일이 있으면 그 자리에서 바로 열 수 있는 file:// 링크를 건다.

디자인은 강의퀴즈 페이지와 같은 언어(ui_theme) — 크림 페이퍼 · 잉크 활자 ·
민트(완료)/애프리콧(진행중) 액센트, 인라인 SVG 아이콘, 화면밝기 전환.

입력 courses: status_page.collect_status() 결과
    [{"course", "rows":[scan_lecture dict…], "stats":{…}}, …]

⚠️ 모든 동적 텍스트는 HTML 이스케이프. 비밀값은 담기지 않는다(과목·차시·경로만).
⚠️ JS 없이도 표 전체가 보인다 — JS 는 '남은 것만 보기' 필터에만 쓴다.
"""
from __future__ import annotations

from ui_theme import (
    esc as _esc,
    escattr as _escattr,
    icon as _icon,
    link as _link,
    page_head,
    page_tail,
    theme_button,
)

DASH = '<span class="none">·</span>'

# 진행 링 반지름/둘레(원주 = 2πr) — 파이썬에서 계산해 CSS 변수로 넘긴다.
RING_R = 19.0
RING_C = round(2 * 3.14159265 * RING_R, 2)


def fmt_when(iso: str) -> str:
    """'2026-08-17T12:09:22' → '2026-08-17 12:09'(형식이 다르면 원문 그대로)."""
    s = str(iso or "").strip()
    if len(s) >= 16 and s[10] == "T":
        return s[:10] + " " + s[11:16]
    return s


def pct(done, total) -> float:
    """0~100 백분율(총량 0 이면 0)."""
    total = float(total or 0)
    return round(float(done or 0) / total * 100, 1) if total else 0.0


def _mark(done: bool, ran: bool = False, done_text: str = "완료",
          fresh: bool = False, none: bool = False) -> str:
    """완료 / 없음 / 실행함*(목록 갱신 전) / 실행함(서버는 미완료) / — 상태 알약.

    fresh=True 는 '목록 스냅샷을 받은 뒤에 실행했다'는 뜻 — LMS 기준 미완료로
    보이는 게 당연한 상태라 다르게 표시한다.
    none=True 는 '그 차시에 애초에 없다'(형성평가 없는 차시) — 확인할 게 없는
    정상 상태라, '돌렸는데 서버는 미완료'(주황 경고)와 반드시 구분한다.
    """
    if done:
        return (f'<span class="pill ok">{_icon("i-check", "ico sm")}'
                f'{_esc(done_text)}</span>')
    if ran and none:
        return ('<span class="pill none" title="이 차시에는 형성평가가 없습니다">'
                '<i class="dot"></i>없음</span>')
    if ran and fresh:
        return ('<span class="pill fresh" '
                'title="목록 새로고침 전이라 LMS 기준 확인 안 됨">'
                f'{_icon("i-check", "ico sm")}실행함<sup>*</sup></span>')
    if ran:
        return ('<span class="pill wait" title="실행 기록은 있으나 LMS 기준 미완료">'
                '<i class="dot"></i>실행함</span>')
    return DASH


def _progress_cell(row: dict) -> str:
    """차시 진도 — 얇은 막대(본 시간이 있을 때만) + 분 수치."""
    total = int(row.get("total_min") or 0)
    if not total:
        return ""
    watched = int(row.get("watched_min") or 0)
    bar = ""
    if watched > 0:
        bar = (f'<span class="mbar"><i style="width:{pct(watched, total)}%">'
               '</i></span>')
    return (f'<span class="mins" title="{_escattr(f"{watched}분 / {total}분")}">'
            f'{bar}<span class="mnum">{watched}<em>/{total}분</em></span></span>')


def _notes_cell(row: dict) -> str:
    notes = row.get("notes") or []
    out = []
    for n in notes:
        part = int(n.get("part") or 1)
        label = "노트" if part == 1 else str(part)
        out.append(_link(n.get("url"), label, cls="chip note",
                         title=n.get("name") or "", icon_name="i-note"))
    extra = row.get("extra_videos") or []
    if extra and len(notes) < len(extra) + 1 and not row.get("extra_done"):
        out.append('<span class="chip ghost" '
                   'title="두 번째 영상 예습노트 미생성">＋2번째 영상</span>')
    return "".join(out) if out else DASH


def _exam_cell(row: dict, quiz_url) -> str:
    parts = [_mark(bool(row.get("exam_done")), bool(row.get("exam_run")),
                   fresh=bool(row.get("exam_new")),
                   none=bool(row.get("exam_none")))]
    n = int(row.get("quiz_count") or 0)
    if n:
        label = f"{n}문항"
        parts.append(_link(quiz_url, label, cls="chip quiz",
                           title="퀴즈 복습 페이지 열기", icon_name="i-quiz")
                     if quiz_url else
                     f'<span class="chip quiz">{_icon("i-quiz")}'
                     f"<span>{_esc(label)}</span></span>")
    return "".join(parts)


def _file_cell(info: dict | None, icon_name: str, kind: str = "") -> str:
    if not info:
        return DASH
    label = kind or (info.get("ext") or "").upper()
    size = info.get("size_mb")
    title = info.get("name") or ""
    if size:
        title = f"{title} · {size}MB"
    return _link(info.get("url"), label, cls="chip file", title=title,
                 icon_name=icon_name)


def row_is_done(row: dict) -> bool:
    """이 차시가 '다 끝난' 줄인지 — 남은 것만 보기 필터 기준.

    LMS 완료(video_done/exam_done)뿐 아니라 '목록 갱신 전에 실행함'도 완료로 본다
    (방금 이수했는데 목록이 아직 옛날이라 남은 것처럼 보이는 걸 막는다).
    """
    watched = bool(row.get("video_done") or row.get("watch_new"))
    examined = bool(row.get("exam_done") or row.get("exam_new"))
    return bool(watched and examined and (row.get("notes") or []))


def _row_html(row: dict, quiz_url) -> str:
    done_all = row_is_done(row)
    # 손댄 흔적이 있는 줄은 또렷하게, 아직인 줄은 조용하게 — 눈이 갈 곳을 만든다.
    touched = bool(row.get("notes") or row.get("mp3") or row.get("doc")
                   or row.get("watch_run") or row.get("video_done"))
    doc = row.get("doc") or None
    watch = _mark(bool(row.get("video_done")), bool(row.get("watch_run")),
                  "이수완료", bool(row.get("watch_new")))
    cls = "done" if done_all else ("live" if touched else "idle")
    return (
        f'<tr class="{cls}">'
        f'<td class="lec"><span class="seq">{int(row.get("seq") or 0):02d}</span>'
        f'<span class="tt"><span class="nm" '
        f'title="{_escattr(row.get("name"))}">{_esc(row.get("name"))}</span>'
        f'{_progress_cell(row)}</span></td>'
        f'<td>{watch}</td>'
        f'<td>{_exam_cell(row, quiz_url)}</td>'
        f'<td>{_notes_cell(row)}</td>'
        f'<td>{_file_cell(row.get("mp3"), "i-audio", "MP3")}</td>'
        f'<td>{_file_cell(doc, "i-doc", (doc or {}).get("kind", ""))}</td>'
        f'</tr>'
    )


def _ring(done, total) -> str:
    """과목 진행 링(인라인 SVG) — 이수 비율을 원호로 + 가운데 백분율."""
    p = pct(done, total)
    off = round(RING_C * (1 - p / 100), 2)
    return (f'<svg class="ring" viewBox="0 0 44 44" '
            f'style="--c:{RING_C};--o:{off}">'
            f'<circle class="trk" cx="22" cy="22" r="{RING_R}"/>'
            f'<circle class="val" cx="22" cy="22" r="{RING_R}"/></svg>'
            f'<span class="ring-n">{int(round(p))}<em>%</em></span>')


def _stat_chips(st: dict) -> str:
    total = int(st.get("total") or 0)
    items = [("이수", st.get("watched", 0)), ("형성평가", st.get("exam", 0)),
             ("예습노트", st.get("noted", 0)), ("MP3", st.get("mp3", 0)),
             ("강의록", st.get("doc", 0))]
    chips = "".join(
        f'<span class="stat"><i>{_esc(label)}</i>'
        f'<b>{int(v)}</b><em>/{total}</em></span>' for label, v in items)
    quiz = int(st.get("quiz") or 0)
    if quiz:
        chips += f'<span class="stat"><i>퀴즈</i><b>{quiz}</b><em>문항</em></span>'
    return chips


def _course_html(course: dict, quiz_url, idx: int = 0) -> str:
    rows = course.get("rows") or []
    st = course.get("stats") or {}
    body = "".join(_row_html(r, quiz_url) for r in rows)
    if not body:
        body = '<tr><td colspan="6" class="none">차시 정보가 없습니다.</td></tr>'
    ring = _ring(st.get("watched") or 0, st.get("total") or 0)
    return (
        f'<section class="course card" style="--i:{idx}">'
        '<header class="c-head">'
        f'<span class="c-ring">{ring}</span>'
        f'<h2>{_esc(course.get("course"))}</h2>'
        f'<span class="c-stats">{_stat_chips(st)}</span>'
        '</header>'
        '<div class="t-wrap"><table><thead><tr>'
        '<th class="lec">차시</th><th>영상이수</th><th>형성평가</th>'
        '<th>예습노트</th><th>MP3</th><th>강의록</th>'
        f'</tr></thead><tbody>{body}</tbody></table></div></section>'
    )


def overall_stats(courses) -> dict:
    """전 과목 합계 — 머리말 요약용."""
    keys = ("total", "watched", "noted", "exam", "mp3", "doc", "quiz")
    out = {k: 0 for k in keys}
    for c in courses or []:
        st = c.get("stats") or {}
        for k in keys:
            out[k] += int(st.get(k) or 0)
    return out


def _metric(label: str, done, total) -> str:
    return (f'<div class="metric"><span class="m-lab">{_esc(label)}</span>'
            f'<span class="m-num">{int(done or 0)}'
            f'<em>/{int(total or 0)}</em></span>'
            f'<span class="m-rail"><i style="--w:{pct(done, total)}%"></i></span>'
            '</div>')


def render_status_html(courses, title: str = "방송대 학습 현황",
                       quiz_url: str | None = None,
                       generated_at: str = "") -> str:
    """과목별 현황 → 단일 자체완결 HTML 문자열."""
    courses = list(courses or [])
    total = overall_stats(courses)
    secs = "".join(_course_html(c, quiz_url, i) for i, c in enumerate(courses))
    if not secs:
        secs = ('<div class="empty"><b>표시할 강의가 없습니다.</b>'
                "<span>실행 탭의 '목록 새로고침'을 먼저 눌러 주세요.</span></div>")

    n = total["total"]
    metrics = (_metric("영상이수", total["watched"], n)
               + _metric("예습노트", total["noted"], n)
               + _metric("형성평가", total["exam"], n))
    when = (f'<span class="when">목록 기준 {_esc(fmt_when(generated_at))}'
            "<em>최신 상태는 '목록 새로고침' 후 다시 만들기</em></span>"
            if generated_at else "")
    quiz_btn = (_link(quiz_url, "퀴즈 복습 페이지", cls="chip cta",
                      icon_name="i-quiz") if quiz_url else "")

    body = (
        '<header class="hero"><div class="wrap">'
        f'<p class="eyebrow">{len(courses)}과목 · {n}차시</p>'
        f'<h1>{_esc(title)}</h1>'
        f'<div class="metrics">{metrics}</div>'
        f'<div class="tools">{quiz_btn}{theme_button()}'
        '<label class="toggle"><input type="checkbox" id="onlyTodo">'
        '<span class="tg"></span>남은 것만 보기</label>'
        f'{when}</div>'
        '</div></header>'
        f'<main class="wrap">{secs}</main>'
        '<footer class="wrap legend">'
        '<span class="pill ok sm"><i class="dot"></i>완료</span>'
        '<span class="pill fresh sm"><i class="dot"></i>'
        '실행함<sup>*</sup> 목록 새로고침 전</span>'
        '<span class="pill wait sm"><i class="dot"></i>'
        '실행했지만 서버 기준 미완료</span>'
        '<span class="pill none sm"><i class="dot"></i>'
        '없음 — 그 차시에 형성평가가 없음</span>'
        '<span class="lg-none">· 아직</span>'
        '<span class="lg-tip">칩을 누르면 파일이 바로 열립니다</span>'
        '</footer>'
    )
    return page_head(title, _CSS) + body + page_tail(_JS)


# ---------------------------------------------------------------------------
# 페이지별 CSS / JS (공통 부분은 ui_theme)
# ---------------------------------------------------------------------------
_CSS = r"""
/* 과목 카드 */
.course { margin-bottom:20px;
  animation:rise .55s cubic-bezier(.2,.75,.3,1) backwards;
  animation-delay:calc(var(--i) * 55ms); }
@keyframes rise { from { opacity:0; transform:translateY(12px); } }
.c-head { display:flex; align-items:center; gap:15px; padding:15px 20px;
  border-bottom:1px solid var(--line); position:sticky; top:0; z-index:3;
  background:var(--card); border-radius:var(--r) var(--r) 0 0; flex-wrap:wrap; }
.c-head h2 { margin:0; font-size:19px; font-weight:800; letter-spacing:-.025em; }
.c-ring { position:relative; width:44px; height:44px; flex:0 0 auto;
  display:grid; place-items:center; }
.ring { position:absolute; inset:0; width:44px; height:44px; transform:rotate(-90deg); }
.ring circle { fill:none; stroke-width:3.4; stroke-linecap:round; }
.ring .trk { stroke:var(--track); }
.ring .val { stroke:var(--mint); stroke-dasharray:var(--c); stroke-dashoffset:var(--o);
  animation:ring 1.1s cubic-bezier(.2,.8,.2,1) .15s backwards; }
@keyframes ring { from { stroke-dashoffset:var(--c); } }
.ring-n { font-family:var(--mono); font-size:12px; font-weight:700;
  font-variant-numeric:tabular-nums; letter-spacing:-.05em; }
.ring-n em { font-style:normal; font-size:9px; color:var(--mute); }
.c-stats { display:flex; gap:6px; flex-wrap:wrap; margin-left:auto; }
.stat { font-size:11.5px; padding:4px 10px; border-radius:99px; background:var(--paper2);
  color:var(--ink2); display:inline-block; }
.stat i { font-style:normal; color:var(--mute); margin-right:5px; }
.stat b { font-family:var(--mono); font-variant-numeric:tabular-nums;
  letter-spacing:-.03em; }
.stat em { font-style:normal; color:var(--mute); }

/* 표 */
.t-wrap { overflow-x:auto; }
table { width:100%; border-collapse:collapse; }
th, td { text-align:left; padding:9px 12px; white-space:nowrap; vertical-align:middle; }
th { font-size:11.5px; font-weight:700; color:var(--mute); letter-spacing:.01em;
  padding:13px 12px 8px; }
tbody tr { border-top:1px solid var(--line); }
tbody tr:hover { background:rgba(0,163,122,.05); }
td.lec, th.lec { white-space:normal; width:46%; min-width:268px; }
td.lec { display:flex; align-items:baseline; gap:12px; }
.seq { font-family:var(--mono); font-size:16px; font-weight:700; color:var(--mute);
  letter-spacing:-.05em; font-variant-numeric:tabular-nums; flex:0 0 auto; }
tr.done .seq, tr.live .seq { color:var(--mint); }
.tt { display:flex; align-items:baseline; gap:10px; flex-wrap:wrap; min-width:0; }
.nm { font-weight:600; letter-spacing:-.015em; min-width:0; max-width:100%;
  overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
tr.idle .nm { color:var(--ink2); font-weight:500; }
.mins { display:flex; align-items:center; gap:8px; }
.mbar { width:92px; height:3px; border-radius:99px; overflow:hidden;
  background:var(--track); flex:0 0 auto; }
.mbar i { display:block; height:100%; background:var(--mint); border-radius:99px; }
.mnum { font-family:var(--mono); font-size:11px; color:var(--mute);
  font-variant-numeric:tabular-nums; }
.mnum em { font-style:normal; opacity:.72; }

/* 남은 것만 보기 */
body.only-todo tr.done { display: none; }
body.only-todo .course:not(:has(tbody tr:not(.done))) { display:none; }

@media (max-width:820px) {
  .c-stats { margin-left:0; }
  td.lec, th.lec { min-width:208px; }
  .mbar { width:58px; }
}
"""

_JS = r"""
(function () {
  var box = document.getElementById('onlyTodo');
  if (!box) return;
  function apply() {
    var cn = document.body.className.replace(/\s*only-todo\s*/g, ' ');
    document.body.className = (box.checked ? cn + ' only-todo' : cn)
      .replace(/^\s+|\s+$/g, '');
  }
  if (box.addEventListener) { box.addEventListener('change', apply, false); }
  else if (box.attachEvent) { box.attachEvent('onclick', apply); }
  apply();
})();
"""
