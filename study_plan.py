"""[study_plan] 진도 따라잡기 — 목표일까지 모든 강의를 한 번은 보려면.

LMS 의 '이수' 는 이 프로그램이 영상을 돌려 채운 것이라, 내가 **실제로 본**
강의와는 다르다. 그래서 따로 센다.

계획은 이렇게 생겼다:

    {"goal": "2026-11-16",          # 이 날까지 모두 한 번은 본다
     "start": "2026-09-07",         # 세기 시작한 날
     "courses": [{"course": "자료구조", "total": 15}, …],
     "watched": {"자료구조": {"1": "2026-09-07", …}, …}}

차질이 생기면 **남은 강의 ÷ 남은 날**을 다시 나누기만 하면 된다. 하루치가
늘어나는 것을 눈으로 보는 것이 이 화면의 전부다.

순수 로직(단위테스트 대상):
  - course_rows(plan)          : 과목마다 몇 강 봤고 몇 강 남았는지
  - totals(plan)               : 전체 합계
  - days_left(goal, today)     : 오늘을 넣어 남은 날
  - weekly_goal(left, days)    : 일주일에 몇 강(정수) — 0.3강짜리 강의는 없다
  - day_text(left, days)       : '하루 1~2강'
  - expected_done(plan, today) : 균등하게 갔다면 오늘까지 봤어야 할 양
  - drift(plan, today)         : 그보다 앞섰는지 뒤처졌는지
  - pace_text / status_line    : 화면 머리말
  - today_line(plan, today)    : '오늘 0강 · 이번 주 1 / 10강'
  - toggle(plan, 과목, 번호)   : 한 강을 봤다/안 봤다로 뒤집는다
  - weekly(plan)               : 주마다 몇 강 봤는지(막대 그래프용)

IO:
  - plan_path(cfg) / load_plan(path) / save_plan(path, plan)
  - courses_from_lectures(path, skip) : 과목·총 강의 수를 lectures.json 에서

⚠️ 학습 기록이라 지워지면 되돌릴 수 없다 — 저장은 임시 파일에 쓴 뒤 바꿔치기.
"""
from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path

PLAN_NAME = "진도계획.json"
DEFAULT_GOAL = "2026-11-16"
DEFAULT_TOTAL = 15          # 방송대 한 과목은 보통 15강이다

# 목표에서 빼는 과목 — 이수만 하면 되는 교양·필수 교육이라 '한 번은 본다' 의
# 대상이 아니다. 필요하면 부르는 쪽에서 다시 정한다.
SKIP_COURSES = ("성폭력·가정폭력예방교육(학생용)",)


def _as_date(value, fallback=None):
    """'2026-11-16' → date. 못 읽으면 fallback."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    try:
        return date.fromisoformat(str(value).strip()[:10])
    except (TypeError, ValueError):
        return fallback


def _today(today=None) -> date:
    return _as_date(today, None) or date.today()


def is_date(value) -> bool:
    """'2026-11-16' 처럼 읽을 수 있는 날짜인가(목표일을 고칠 때 확인한다)."""
    return _as_date(value) is not None


# ---------------------------------------------------------------------------
# 계획 읽기
# ---------------------------------------------------------------------------
def watched_nos(plan, course) -> list:
    """이 과목에서 본 강 번호들(작은 것부터)."""
    got = ((plan or {}).get("watched") or {}).get(str(course)) or {}
    if not isinstance(got, dict):
        return []
    out = []
    for k in got:
        try:
            n = int(k)
        except (TypeError, ValueError):
            continue
        if n > 0:
            out.append(n)
    return sorted(set(out))


def watched_on(plan, course, no):
    """그 강을 본 날(모르면 빈 문자열)."""
    got = ((plan or {}).get("watched") or {}).get(str(course)) or {}
    return str(got.get(str(no)) or "") if isinstance(got, dict) else ""


def course_rows(plan) -> list:
    """과목마다 한 줄 — [{course, total, nos, done, left, pct}].

    계획에 적힌 과목 순서를 지킨다(화면이 흔들리지 않게).
    """
    out = []
    for c in (plan or {}).get("courses") or []:
        course = str((c or {}).get("course") or "").strip()
        if not course:
            continue
        try:
            total = int(c.get("total") or DEFAULT_TOTAL)
        except (TypeError, ValueError):
            total = DEFAULT_TOTAL
        nos = [n for n in watched_nos(plan, course) if n <= total]
        done = len(nos)
        out.append({"course": course, "total": total, "nos": nos,
                    "done": done, "left": max(0, total - done),
                    "pct": round(done / total * 100) if total else 0})
    return out


def totals(plan) -> dict:
    """전체 합계 — {total, done, left, pct}."""
    rows = course_rows(plan)
    total = sum(r["total"] for r in rows)
    done = sum(r["done"] for r in rows)
    return {"total": total, "done": done, "left": max(0, total - done),
            "pct": round(done / total * 100) if total else 0}


# ---------------------------------------------------------------------------
# 남은 날과 하루치
# ---------------------------------------------------------------------------
def days_left(goal, today=None) -> int:
    """목표일까지 남은 날 — **오늘을 넣어** 센다.

    오늘 아직 안 들었으면 오늘도 들을 수 있는 날이다. 오늘을 빼면 하루치가
    실제보다 부풀어 겁만 준다. 목표일이 지났으면 0.
    """
    g = _as_date(goal)
    if g is None:
        return 0
    return max(0, (g - _today(today)).days + 1)


def weekly_goal(left, days) -> int:
    """일주일에 몇 강 — **정수**로.

    강의는 쪼갤 수 없다. '하루 0.3강' 같은 단위는 현실에 없어서, 과목마다는
    주 단위로 말한다(주 2강이면 계획을 세울 수 있다). 모자라지 않게 올린다.
    """
    left, days = max(0, int(left or 0)), int(days or 0)
    if not left:
        return 0
    if days <= 0:
        return left
    return min(left, -(-left * 7 // days))      # 올림


def day_text(left, days) -> str:
    """'하루 1~2강' — 하루치가 소수로 떨어질 때 정수 범위로 말한다.

    64강을 49일에 나누면 1.3강이지만, 실제로는 하루 1강 듣는 날과 2강 듣는
    날이 섞인다. 그것을 그대로 적는다.
    """
    left, days = max(0, int(left or 0)), int(days or 0)
    if days <= 0:
        return f"하루 {left}강"
    lo = left // days
    hi = -(-left // days)                       # 올림
    return f"하루 {lo}강" if lo == hi else f"하루 {lo}~{hi}강"


def expected_done(plan, today=None) -> float:
    """균등하게 갔다면 오늘까지 봤어야 할 강의 수.

    시작일부터 목표일까지를 고르게 나눈 값이다. 목표일을 넘었으면 전부.
    """
    t = totals(plan)["total"]
    start = _as_date((plan or {}).get("start"))
    goal = _as_date((plan or {}).get("goal"))
    if not t or start is None or goal is None:
        return 0.0
    span = (goal - start).days + 1
    if span <= 0:
        return float(t)
    gone = (_today(today) - start).days + 1
    if gone <= 0:
        return 0.0
    return round(t * min(gone, span) / span, 1)


def drift(plan, today=None) -> float:
    """계획보다 앞섰으면 +, 뒤처졌으면 - (강 수)."""
    return round(totals(plan)["done"] - expected_done(plan, today), 1)


def num_text(x) -> str:
    """강의 수를 적는 법 — **정수**로. 0.3강짜리 강의는 없다."""
    return str(int(round(float(x or 0))))


def pace_text(plan, today=None) -> str:
    """'하루 1~2강 · 주 10강' — 남은 것이 없으면 다 봤다고 말한다.

    마지막 한 주가 남으면 주 단위가 뜻을 잃는다 — 그때는 남은 날로 말한다.
    """
    t = totals(plan)
    if not t["total"]:
        return "과목이 없습니다"
    if not t["left"]:
        return "모든 강의를 한 번씩 봤습니다"
    d = days_left((plan or {}).get("goal"), today)
    if d <= 0:
        return f"목표일이 지났습니다 · {t['left']}강 남음"
    if d < 7:
        return f"남은 {d}일에 {t['left']}강"
    week = f"주 {weekly_goal(t['left'], d)}강"
    # 하루 한 강도 안 되는 양을 '하루 0~1강' 이라 적으면 읽을 것이 없다.
    return week if t["left"] < d else f"{day_text(t['left'], d)} · {week}"


def drift_text(plan, today=None) -> str:
    """'계획보다 12강 뒤처졌습니다' — 앞섰으면 그렇게 말한다."""
    t = totals(plan)
    if not t["total"] or not t["left"]:
        return ""
    d = drift(plan, today)
    if d <= -0.5:
        return f"계획보다 {num_text(-d)}강 뒤처졌습니다"
    if d >= 0.5:
        return f"계획보다 {num_text(d)}강 앞섰습니다"
    return "계획대로 가고 있습니다"


def status_line(plan, today=None) -> str:
    """머리말 한 줄 — 'D-50 · 11 / 75강(15%) · 하루 1.3강'."""
    t = totals(plan)
    d = days_left((plan or {}).get("goal"), today)
    head = f"D-{d}" if d > 0 else "목표일이 지났습니다"
    return f"{head} · {t['done']} / {t['total']}강({t['pct']}%) · " \
           f"{pace_text(plan, today)}"


def done_between(plan, since, until) -> int:
    """이 사이(양 끝 포함)에 본 강의 수."""
    n = 0
    for nos in ((plan or {}).get("watched") or {}).values():
        if not isinstance(nos, dict):
            continue
        for when in nos.values():
            d = _as_date(when)
            if d is not None and since <= d <= until:
                n += 1
    return n


def today_done(plan, today=None) -> int:
    """오늘 본 강의 수."""
    t = _today(today)
    return done_between(plan, t, t)


def week_done(plan, today=None) -> int:
    """이번 주(월요일부터 오늘까지) 본 강의 수."""
    t = _today(today)
    return done_between(plan, t - timedelta(days=t.weekday()), t)


def today_line(plan, today=None) -> str:
    """'오늘 0강 · 이번 주 1 / 10강' — 오늘 뭘 해야 하는지.

    트래커를 여는 이유가 이 한 줄이다. 남은 것이 없으면 빈 문자열.

    ⚠️ 오늘 몫은 **목표를 붙이지 않는다.** 하루치가 1.3강처럼 떨어지면 오늘의
       목표가 1강인지 2강인지 말할 수 없다. 목표는 주로 잡고, 오늘은 얼마나
       했는지만 센다.
    """
    t = totals(plan)
    if not t["total"] or not t["left"]:
        return ""
    d = days_left((plan or {}).get("goal"), today)
    if d <= 0:
        return ""
    return (f"오늘 {today_done(plan, today)}강 · "
            f"이번 주 {week_done(plan, today)} / "
            f"{weekly_goal(t['left'], d)}강")


def course_week(row, days) -> int:
    """이 과목만 따로 봤을 때 일주일에 몇 강 — 뒤처진 과목을 가려낸다."""
    return weekly_goal((row or {}).get("left"), days)


def worst_course(plan, today=None):
    """가장 뒤처진 과목 이름(다 봤으면 None).

    남은 강의가 가장 많은 과목이다. 어디부터 손댈지 알려준다.
    """
    rows = [r for r in course_rows(plan) if r["left"]]
    if not rows:
        return None
    return max(rows, key=lambda r: (r["left"], -r["done"]))["course"]


# ---------------------------------------------------------------------------
# 고치기
# ---------------------------------------------------------------------------
def toggle(plan, course, no, today=None) -> dict:
    """한 강을 봤다/안 봤다로 뒤집는다 → 새 계획(원본은 건드리지 않는다)."""
    course, no = str(course), str(int(no))
    p = dict(plan or {})
    watched = {k: dict(v) for k, v in (p.get("watched") or {}).items()
               if isinstance(v, dict)}
    got = watched.get(course) or {}
    if no in got:
        got.pop(no)
    else:
        got[no] = _today(today).isoformat()
    if got:
        watched[course] = got
    else:
        watched.pop(course, None)
    p["watched"] = watched
    return p


def merge_watched(plan, found) -> dict:
    """밖에서 읽어 온 기록을 합친다 — **이미 있는 날짜는 지키고** 빈 곳만 채운다.

    카카오톡 대화에서 지난 인증을 심을 때 쓴다. 앱에서 손으로 눌러 둔 것을
    덮어쓰지 않는다.
    """
    p = dict(plan or {})
    watched = {k: dict(v) for k, v in (p.get("watched") or {}).items()
               if isinstance(v, dict)}
    for course, nos in (found or {}).items():
        got = watched.get(str(course)) or {}
        for no, when in (nos or {}).items():
            got.setdefault(str(no), str(when))
        if got:
            watched[str(course)] = got
    p["watched"] = watched
    return p


def make_plan(courses, goal: str = DEFAULT_GOAL, start=None) -> dict:
    """빈 계획 한 벌 — courses 는 [{course, total}] 또는 과목명 목록."""
    rows = []
    for c in courses or []:
        if isinstance(c, dict):
            rows.append({"course": str(c.get("course") or "").strip(),
                         "total": int(c.get("total") or DEFAULT_TOTAL)})
        else:
            rows.append({"course": str(c).strip(), "total": DEFAULT_TOTAL})
    return {"goal": str(goal or DEFAULT_GOAL),
            "start": (_as_date(start) or date.today()).isoformat(),
            "courses": [r for r in rows if r["course"]], "watched": {}}


def weekly(plan, weeks: int = 8, today=None) -> list:
    """주마다 몇 강 봤는지 — [{start, n}] (월요일 기준, 오래된 주부터).

    최근 weeks 주만 돌려주되 **세기 시작하기 전 주는 뺀다**. 학기 시작 전의
    빈 막대가 줄줄이 붙으면 정작 봐야 할 최근 몇 주가 눈에 안 들어온다.
    """
    counts: dict[date, int] = {}
    for nos in ((plan or {}).get("watched") or {}).values():
        if not isinstance(nos, dict):
            continue
        for when in nos.values():
            d = _as_date(when)
            if d is None:
                continue
            mon = d - timedelta(days=d.weekday())
            counts[mon] = counts.get(mon, 0) + 1
    end = _today(today)
    end_mon = end - timedelta(days=end.weekday())
    start = _as_date((plan or {}).get("start"))
    first_mon = (start - timedelta(days=start.weekday())) if start else None
    out = []
    for i in range(int(weeks) - 1, -1, -1):
        mon = end_mon - timedelta(weeks=i)
        if first_mon is not None and mon < first_mon:
            continue
        out.append({"start": mon.isoformat(), "n": counts.get(mon, 0)})
    return out


# ---------------------------------------------------------------------------
# 저장 (IO)
# ---------------------------------------------------------------------------
def plan_path(cfg) -> Path:
    """계획 파일 — 볼트의 요약 폴더에 둔다(퀴즈·노트와 한자리)."""
    return Path(cfg.summary_dir) / PLAN_NAME


def load_plan(path) -> dict:
    """계획을 읽는다. 없거나 깨졌으면 빈 dict."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_plan(path, plan) -> Path:
    """계획을 저장한다 — 임시 파일에 쓴 뒤 바꿔치기한다.

    ⚠️ 사람이 쌓은 학습 기록이다. 도중에 멈춰 반쪽짜리가 남으면 되돌릴 수 없다.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(plan or {}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)
    return p


def courses_from_lectures(path, skip=SKIP_COURSES) -> list:
    """lectures.json → [{course, total}] — 강의가 없는 과목은 뺀다."""
    p = Path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    out = []
    for c in (data or {}).get("courses") or []:
        name = str((c or {}).get("name") or "").strip()
        total = len((c or {}).get("lectures") or [])
        if not name or not total or name in (skip or ()):
            continue
        out.append({"course": name, "total": total})
    return out
