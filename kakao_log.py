"""[kakao_log] 카카오톡 대화 내보내기 → 내가 인증한 강의 목록.

단톡방에 '자료구조 1강 들었습니다' 하고 올린 기록이 곧 **실제로 본 강의**다
(LMS 의 이수는 이 프로그램이 영상을 돌려 채운 것이라 다르다). 지난 인증을
진도 계획(study_plan)에 한 번 심어 두면, 그 뒤로는 앱에서 눌러 가며 쓴다.

대화 파일은 이렇게 생겼다:

    --------------- 2026년 9월 7일 월요일 ---------------
    [잔향/복수전공/3학년] [오후 6:44] 자료구조 1강 들었습니다

⚠️ 새벽에 올린 인증은 **전날 공부한 것**이다. 단톡방도 '새벽 세 시 이전에
   올린 건 전날로 친다' 는 규칙으로 세고 있어 그대로 따른다.

순수 로직(단위테스트 대상):
  - parse_time(text)            : '오후 6:44' → (18, 44)
  - parse_day(line)             : 날짜 구분선 → date
  - study_date(day, hh, cut)    : 새벽이면 전날로
  - course_alias(courses)       : 과목마다 줄여 부르는 이름들
  - find_course(text, aliases)  : 이 말이 어느 과목인가
  - find_lectures(text)         : '5강 6강' → [5, 6], '4강까지' → [1,2,3,4]
  - parse_log(text, 닉, 과목)   : {과목: {번호: 날짜}}
"""
from __future__ import annotations

import re
from datetime import date, timedelta

# 이 시각 이전에 올린 글은 전날 공부한 것으로 친다(단톡방과 같은 규칙).
NIGHT_CUTOFF = 3

DAY_RE = re.compile(r"-{3,}\s*(\d{4})년\s*(\d{1,2})월\s*(\d{1,2})일")
MSG_RE = re.compile(r"^\[([^\]]+)\]\s*\[(오전|오후)\s*(\d{1,2}):(\d{2})\]\s*(.*)$")
# '1강' · '5강 6강' · '8,9강' · '9, 10 강' · '4강까지' 를 모두 읽는다.
LEC_RE = re.compile(r"(\d{1,2}(?:\s*[,·~]\s*\d{1,2})*)\s*강(까지)?")
NUM_RE = re.compile(r"\d{1,2}")

# 과목을 줄여 부르는 말 — 대화에서는 정식 이름을 다 적지 않는다.
EXTRA_ALIAS = {
    "컴퓨터구조": ("컴구",),
    "오픈소스기반데이터분석": ("오픈소스", "오소분"),
    "바이오통계학": ("바이오통계", "바통"),
    "C프로그래밍": ("c프로그래밍", "씨프로그래밍"),
    "자료구조": ("자구",),
}


def parse_time(ampm: str, hour, minute) -> tuple:
    """'오후' 6:44 → (18, 44). 오전 12시는 0시, 오후 12시는 12시다."""
    h = int(hour) % 12
    if str(ampm).strip() == "오후":
        h += 12
    return h, int(minute)


def parse_day(line: str):
    """날짜 구분선 → date(구분선이 아니면 None)."""
    m = DAY_RE.search(str(line or ""))
    if not m:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def study_date(day, hour, cutoff: int = NIGHT_CUTOFF):
    """올린 날 + 시각 → **공부한 날**. 새벽이면 전날로 돌린다."""
    if day is None:
        return None
    return day - timedelta(days=1) if int(hour) < int(cutoff) else day


def course_alias(courses) -> dict:
    """{줄여 부르는 말: 정식 과목명} — 긴 이름이 먼저 걸리도록 쓴다."""
    out = {}
    for c in courses or []:
        name = str(c.get("course") if isinstance(c, dict) else c or "").strip()
        if not name:
            continue
        out[name.lower()] = name
        out[name.replace(" ", "").lower()] = name
        for a in EXTRA_ALIAS.get(name, ()):
            out[a.lower()] = name
    return out


def find_course(text, aliases):
    """이 말이 어느 과목인가(못 찾으면 None).

    긴 이름부터 맞춰 본다 — '오픈소스' 와 '오픈소스기반데이터분석' 이 함께
    있으면 긴 쪽이 맞다.
    """
    s = str(text or "").replace(" ", "").lower()
    if not s:
        return None
    for key in sorted(aliases or {}, key=len, reverse=True):
        if key and key.replace(" ", "") in s:
            return aliases[key]
    return None


def find_lectures(text, total: int = 99) -> list:
    """'5강 6강' → [5, 6] · '8,9강' → [8, 9] · '4강까지' → [1..4].

    'N강까지' 는 거기까지 다 들었다는 뜻이다. 겹쳐 담겨도 기록은 한 번만
    남으므로 넉넉히 세는 편이 낫다.
    """
    out = []
    for m in LEC_RE.finditer(str(text or "")):
        nums = [int(x) for x in NUM_RE.findall(m.group(1))]
        nums = [n for n in nums if 1 <= n <= int(total)]
        if not nums:
            continue
        # '4강까지' 는 맨 뒤 번호까지 다 들었다는 말이다.
        out += list(range(1, max(nums) + 1)) if m.group(2) else nums
    return sorted(set(out))


def is_mine(speaker, nick) -> bool:
    """이 글이 내 것인가 — 닉네임 앞부분만 맞으면 된다.

    카톡 이름은 '잔향/복수전공/3학년' 처럼 뒤에 학과·학년이 붙는다.
    """
    return str(nick or "").strip() in str(speaker or "")


def parse_log(text, nick, courses, cutoff: int = NIGHT_CUTOFF) -> dict:
    """대화 내보내기 → {과목: {강 번호: 'YYYY-MM-DD'}}.

    같은 강을 여러 번 올렸으면 **처음 올린 날**을 남긴다(그때 본 것이다).
    """
    aliases = course_alias(courses)
    totals = {}
    for c in courses or []:
        if isinstance(c, dict):
            totals[str(c.get("course"))] = int(c.get("total") or 99)
    out: dict[str, dict] = {}
    day = None
    for line in str(text or "").splitlines():
        got = parse_day(line)
        if got is not None:
            day = got
            continue
        m = MSG_RE.match(line)
        if not m or not is_mine(m.group(1), nick):
            continue
        hh, _mm = parse_time(m.group(2), m.group(3), m.group(4))
        when = study_date(day, hh, cutoff)
        if when is None:
            continue
        body = m.group(5)
        course = find_course(body, aliases)
        if not course:
            continue
        for n in find_lectures(body, totals.get(course, 99)):
            got_map = out.setdefault(course, {})
            # 먼저 올린 날이 이긴다 — 나중에 '다시 들었다' 고 올려도 처음 본
            # 날짜를 잃지 않는다.
            if str(n) not in got_map:
                got_map[str(n)] = when.isoformat()
    return out


def count(found) -> int:
    """찾은 강의 수 — 심기 전에 몇 개인지 알려준다."""
    return sum(len(v or {}) for v in (found or {}).values())


def first_day(found):
    """가장 먼저 인증한 날(없으면 None) — 계획의 시작일로 쓴다."""
    days = [w for nos in (found or {}).values() for w in (nos or {}).values()]
    return min(days) if days else None
