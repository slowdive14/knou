"""[knouon] 통합학습관리시스템(knouon.knou.ac.kr) — 바이오통계학 전용 경로.

2026-2학기부터 **바이오통계학만** 전자캠퍼스(ucampus)가 아니라 이 시스템에서
돌아간다. '나의 학습'에 과목은 뜨지만 차시 AJAX 가 빈 목록을 주기 때문에,
지금까지 파이프라인이 이 과목을 아예 보지 못했다.

다행히 **로그인 세션은 그대로 통한다**. 다른 것은 앞단뿐이라, 여기서 주차 목록과
재생만 맡고 요약·캡처 같은 뒷단은 기존 코드를 그대로 쓴다.

순수 로직(단위테스트 대상):
  - content_id(sbjct_id, week)   : 주차 → 콘텐츠ID(WS_KNOU20920010N)
  - enc_params(data)             : makeEncParams = base64(UTF-8 JSON)
  - lecture_url(week_id, sbjct_id): 주차 강의 화면 주소
  - parse_week(raw)              : DOM 추출 dict → Week
  - parse_percent(text)          : "진도율 5.67%" → 5.67
  - week_is_complete(week)       : 이수 완료 판정

브라우저 연동(수동 검증):
  - enter_classroom(page, sbjct_id): 대시보드 → 강의실
  - fetch_weeks(page, sbjct_id)    : 주차 목록
  - open_week(page, week)          : 주차 강의 화면 열기
  - watch_week(page, week, …)      : 주차 영상 자동 시청

정찰 결과와 주의사항은 docs/lms-map.md §11 참조.

⚠️ 비밀값: 영상 URL 의 `token=` 은 시한부 JWT, Kollus 의 `uservalue1`·POST 의
   `userId` 에는 **학번**이 실린다. 어느 것도 state.json·로그에 남기지 않는다.
"""
from __future__ import annotations

import base64
import json
import re
import time
from dataclasses import dataclass

BASE = "https://knouon.knou.ac.kr"
DASHBOARD_URL = f"{BASE}/dashboard/stuDashboard.do"
LECTURE_VIEW = f"{BASE}/lctr/wknoLectureView.do"

# 이 시스템에서 돌아가는 과목. 과목이 늘면 여기에 (과목명 → sbjctId)를 더한다.
# sbjctId 는 '나의 학습'의 sbjt_id(KNOU2092001) 앞에 SBJCT_ 를 붙인 꼴이다.
KNOUON_COURSES = {"바이오통계학": "SBJCT_KNOU2092001"}

# 이수 완료로 볼 진도율(%). 서버 판정 플래그를 아직 못 찾아 진도율로 본다 —
# 완료 기준이 확인되면 그 값으로 바꾼다(docs/lms-map.md §11-5).
COMPLETE_PERCENT = 95.0

# 영상 길이를 끝내 못 읽었을 때 줄 벽시계 예산(초). 완청 판정은 예산이 아니라
# watch._play_until_end 가 하므로, 이 값은 '무한정 붙잡지 않기' 위한 상한이다.
UNKNOWN_BUDGET_S = 5400.0

# 벽시계 예산 여유배수. 전자캠퍼스는 1.5 로 충분했지만 여기는 더 줘야 한다 —
# **배속을 2 로 걸어도 실제로는 그만큼 안 나온다**(실측: 15초에 12초 진행,
# 약 0.8배). HLS 가 아니라 progressive MP4 라 버퍼가 2배속을 못 따라간다.
# 예산은 '멈췄을 때 빠져나오기 위한 상한'일 뿐이라, 완청하면 일찍 끝난다.
WAIT_FACTOR = 3.0


@dataclass(frozen=True)
class Week:
    """주차 1개. 전자캠퍼스의 Lecture 에 대응하지만 필드가 다르다."""
    seq: int            # 주차 번호(파일명·노트에서는 'N강'과 같은 자리)
    name: str           # 주차명(번호 접두사를 뗀 것)
    percent: float      # 진도율 %
    content_id: str     # lctrWknoSchdlId (WS_KNOU20920010N)
    sbjct_id: str       # SBJCT_KNOU2092001
    course: str = ""    # 과목명
    period: str = ""    # 학습기간 표시문자열

    @property
    def video_done(self) -> bool:
        """영상 이수 완료 — 기존 파이프라인이 이 이름으로 묻는다."""
        return week_is_complete(self)


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def sbjct_id_for(course: str) -> str | None:
    """과목명 → knouon sbjctId. 이 시스템 과목이 아니면 None."""
    return KNOUON_COURSES.get((course or "").strip())


def is_knouon_course(course: str) -> bool:
    """이 과목을 knouon 에서 다뤄야 하는가."""
    return sbjct_id_for(course) is not None


def content_id(sbjct_id: str, week: int) -> str:
    """주차 → 콘텐츠ID. `SBJCT_KNOU2092001` + 1주차 → `WS_KNOU209200101`.

    규칙: 과목ID 의 `SBJCT_` 를 `WS_` 로 바꾸고 **두 자리 주차**를 덧붙인다.
    """
    core = re.sub(r"^SBJCT_", "", str(sbjct_id or ""))
    return f"WS_{core}{int(week):02d}"


def enc_params(data: dict) -> str:
    """`UiComm.makeEncParams` 와 같은 값 — base64(UTF-8 JSON).

    ⚠️ 대시보드 주소에 붙는 `encParams`(학기 컨텍스트)는 이것과 **다르다**.
    그쪽은 URL 인코딩이 한 겹 더 있는 서버 생성값이라, 직접 만들지 말고
    페이지의 함수를 불러야 한다(enter_classroom 참고).
    """
    raw = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    return base64.b64encode(raw.encode("utf-8")).decode()


def lecture_url(week_id: str, sbjct_id: str) -> str:
    """주차 강의 화면 주소(모달 iframe 이 쓰는 그 주소)."""
    enc = enc_params({"lctrWknoSchdlId": week_id, "sbjctId": sbjct_id})
    return f"{LECTURE_VIEW}?encParams={enc}"


_PCT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*%")
# 주차 제목은 'N주차 제목' 꼴이라 앞의 번호를 뗀다
_WEEK_PREFIX_RE = re.compile(r"^\s*\d+\s*주차\s*")


def parse_percent(text) -> float:
    """'진도율 5.67%' → 5.67. 못 읽으면 0.0."""
    m = _PCT_RE.search(str(text or ""))
    if not m:
        return 0.0
    try:
        return float(m.group(1))
    except ValueError:
        return 0.0


def clean_week_name(text) -> str:
    """'1주차 통계학의 기본 개념과 데이터 요약' → '통계학의 기본 개념과 데이터 요약'."""
    return _WEEK_PREFIX_RE.sub("", str(text or "")).strip()


def parse_week(raw: dict, sbjct_id: str = "", course: str = "") -> Week | None:
    """DOM 에서 긁은 dict → Week. 주차 번호가 없으면 None."""
    try:
        seq = int(str(raw.get("week") or "").strip())
    except (TypeError, ValueError):
        return None
    if seq <= 0:
        return None
    sid = (raw.get("sbjctId") or sbjct_id or "").strip()
    cid = (raw.get("contentId") or "").strip() or content_id(sid, seq)
    return Week(
        seq=seq,
        name=clean_week_name(raw.get("title")),
        percent=parse_percent(raw.get("progress")),
        content_id=cid,
        sbjct_id=sid,
        course=course,
        period=(raw.get("period") or "").strip(),
    )


def parse_weeks(rows, sbjct_id: str = "", course: str = "") -> list[Week]:
    """DOM dict 목록 → Week 목록(주차 순, 못 읽은 줄은 버린다)."""
    out = [parse_week(r, sbjct_id, course) for r in (rows or [])]
    return sorted([w for w in out if w is not None], key=lambda w: w.seq)


def week_is_complete(week) -> bool:
    """이 주차 영상 이수가 끝났는가.

    전자캠퍼스는 서버 플래그(stdyCmyn)가 있었지만 여기서는 아직 못 찾아
    **진도율**로 본다. 100%가 아니라 COMPLETE_PERCENT 로 두는 이유: 블록
    커버리지 방식이라 마지막 자투리가 안 채워져 99%대에서 멈추는 일이 있다.
    """
    try:
        return float(getattr(week, "percent", 0)) >= COMPLETE_PERCENT
    except (TypeError, ValueError):
        return False


def unwatched(weeks) -> list:
    """아직 이수하지 않은 주차만."""
    return [w for w in (weeks or []) if not week_is_complete(w)]


# ---------------------------------------------------------------------------
# 브라우저 연동 (수동 검증)
# ---------------------------------------------------------------------------

# 강의실의 주차 목록. DOM 구조는 docs/lms-map.md §11-1 참조.
_WEEKS_JS = """
() => {
  const txt = (el) => (el ? el.textContent.replace(/\\s+/g, ' ').trim() : '');
  return [...document.querySelectorAll('li[data-week]')].map(li => {
    const btn = li.querySelector('button[onclick*="openWknoLectureViewPopup"]');
    const oc = btn ? (btn.getAttribute('onclick') || '') : '';
    const m = oc.match(/openWknoLectureViewPopup\\('([^']+)'\\s*,\\s*'([^']+)'/);
    return {
      week: li.getAttribute('data-week'),
      title: txt(li.querySelector('.title strong')),
      progress: txt(li.querySelector('.desc_info')),
      period: txt(li.querySelector('.desc .date')),
      contentId: m ? m[1] : '',
      sbjctId: m ? m[2] : '',
    };
  });
}
"""


def enter_classroom(page, sbjct_id: str, timeout_ms: int = 60000) -> None:
    """대시보드를 거쳐 강의실로 들어간다.

    ⚠️ **이 순서를 건너뛰면 안 된다.** 강의 주소로 바로 가면 Kollus iframe 이
    채워지지 않는다(실측: 프레임 1개, `<video>` 0개). 세션에 학기·과목
    컨텍스트가 잡혀야 하는 것으로 보인다.

    ⚠️ 학기 컨텍스트(encParams)는 대시보드 페이지의 전역변수에 들어 있으므로,
    주소를 직접 조립하지 않고 페이지의 `moveClassRoom` 을 부른다 — 그래야
    학기가 바뀌어도 따라간다.
    """
    page.goto(DASHBOARD_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    page.wait_for_timeout(2000)
    page.evaluate("(id) => moveClassRoom(id)", sbjct_id)
    try:
        page.wait_for_load_state("networkidle", timeout=timeout_ms)
    except Exception:
        pass
    page.wait_for_timeout(2500)


def fetch_weeks(page, sbjct_id: str, course: str = "",
                enter: bool = True) -> list[Week]:
    """강의실의 주차 목록을 읽는다(읽기 전용)."""
    if enter:
        enter_classroom(page, sbjct_id)
    rows = page.evaluate(_WEEKS_JS)
    return parse_weeks(rows, sbjct_id, course)


def wait_for_players(page, timeout_ms: int = 30000, poll_ms: int = 1000) -> bool:
    """재생 프레임에 `<video>` 가 채워질 때까지 기다린다.

    Kollus 는 iframe 을 늦게 채우므로 '페이지 로드 완료'만으로는 부족하다.
    """
    from watch import clip_inventory
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        try:
            if any(c.get("has") for c in clip_inventory(page)):
                return True
        except Exception:
            pass
        page.wait_for_timeout(poll_ms)
    return False


def open_week(page, week: Week, timeout_ms: int = 60000, settle_ms: int = 30000,
              tries: int = 2):
    """주차 강의 화면을 연다. 반환: page.

    enter_classroom 을 먼저 거친 상태여야 한다.

    ⚠️ `wait_until="domcontentloaded"` 로 기다리면 타임아웃 난다(실측). Kollus
    iframe 이 계속 물고 있어 그 시점이 늦게 온다. 주소가 확정되는 것(commit)만
    확인하고, 그 뒤 **재생 프레임이 차오르는 것**을 직접 기다린다.
    """
    url = lecture_url(week.content_id, week.sbjct_id)
    last_err = None
    for attempt in range(1, max(1, tries) + 1):
        try:
            page.goto(url, wait_until="commit", timeout=timeout_ms)
        except Exception as e:  # noqa: BLE001 - 느린 응답은 재시도로 넘긴다
            last_err = e
            page.wait_for_timeout(3000)
            continue
        if wait_for_players(page, settle_ms):
            return page
        last_err = TimeoutError(f"{week.seq}주차: 재생 프레임이 뜨지 않았다")
    if last_err is not None:
        raise last_err
    return page


_PLAY_JS = """
(rate) => {
  const out = [];
  for (const v of document.querySelectorAll('video')) {
    try {
      v.playbackRate = rate;
      const p = v.play();
      if (p && p.catch) p.catch(() => {});
      out.push(v.playbackRate);
    } catch (e) { out.push(-1); }
  }
  return JSON.stringify(out);
}
"""


_PAUSE_JS = """
() => {
  let n = 0;
  for (const v of document.querySelectorAll('video')) {
    try { if (!v.paused) { v.pause(); n++; } } catch (e) {}
  }
  return n;
}
"""


def trigger_save(page, settle: float = 6.0) -> int:
    """진도 저장을 유도한다 — 영상을 멈추면 서버로 보고가 나간다.

    전자캠퍼스의 `_trigger_save` 는 `fnPlayStop()` 을 부르지만 그건 그쪽 전용
    함수다. 여기서는 `POST /lctr/kollusCallback.do` 가 **재생 정지 시점**에도
    나가는 것을 확인했으므로(docs/lms-map.md §11-4) 일시정지로 갈음한다.
    보고가 날아갈 시간만큼 기다린다.
    """
    paused = 0
    from watch import _clip_frames
    for fr in _clip_frames(page):
        try:
            paused += int(fr.evaluate(_PAUSE_JS) or 0)
        except Exception:
            pass
    if paused:
        time.sleep(settle)
    return paused


def pause_others(page, keep_index: int) -> int:
    """대상 말고 다른 영상을 멈춘다. 반환: 멈춘 개수."""
    from watch import _clip_frames
    n = 0
    for i, fr in enumerate(_clip_frames(page)):
        if i == keep_index:
            continue
        try:
            n += int(fr.evaluate(_PAUSE_JS) or 0)
        except Exception:
            pass
    return n


def solo_guard(page, keep_index: int, speed: float, inner=None):
    """폴링마다 **대상 영상만 살려 두는** 감시 콜백을 만든다.

    실측 문제: 오리엔테이션을 재생하면 잠깐 나아가다(0→45초) 멈춰 버리고,
    그 뒤로는 상태조차 못 읽는다. 본강의가 되살아나 밀어내는 것으로 보인다
    (Kollus 는 한 페이지에서 한 영상만 돌린다). 재생 시작 때 한 번 멈추는
    것으로는 모자라, 매 폴링에서 다시 멈추고 대상을 다시 밀어 준다.

    inner 가 있으면 그대로 이어서 부른다(진행 출력 등).
    """
    from watch import _clip_frames

    def guard(st):
        try:
            pause_others(page, keep_index)
            frames = _clip_frames(page)
            if keep_index < len(frames):
                frames[keep_index].evaluate(_PLAY_JS, speed)
        except Exception:
            pass
        if inner is not None:
            try:
                inner(st)
            except Exception:
                pass

    return guard


def clip_duration(page, frame_index: int, fallback: float = 0,
                  timeout_ms: int = 20000, poll_ms: int = 1000) -> float:
    """재생 중인 영상의 길이(초). 못 읽으면 fallback.

    Kollus 는 메타데이터를 늦게 채워 재생 직후에도 잠시 길이가 없다 — 잠깐
    기다리며 다시 묻는다.
    """
    from watch import _clip_state
    deadline = time.time() + timeout_ms / 1000.0
    while time.time() < deadline:
        st = _clip_state(page, frame_index) or {}
        d = st.get("dur")
        if isinstance(d, (int, float)) and d > 0:
            return float(d)
        page.wait_for_timeout(poll_ms)
    try:
        return float(fallback or 0)
    except (TypeError, ValueError):
        return 0.0


def start_clip(page, frame_index: int, speed: float) -> bool:
    """한 영상의 재생을 시작한다. 전자캠퍼스와 달리 재생기록 모달이 없다.

    return: 재생이 걸렸으면 True.
    """
    from watch import _clip_frames
    frames = _clip_frames(page)
    if frame_index >= len(frames):
        return False
    # ⚠️ 다른 영상을 **먼저 멈춘다**. 페이지를 열면 본강의가 저절로 재생되기
    # 시작하는데, 그 상태에서 오리엔테이션을 play() 하면 `paused=True` 인 채로
    # 위치가 한 발짝도 안 나간다(실측: 13초에서 정체 → 예산만 소진).
    # Kollus 는 한 페이지에서 한 영상만 돌리는 것으로 보인다.
    for i, fr in enumerate(frames):
        if i == frame_index:
            continue
        try:
            fr.evaluate(_PAUSE_JS)
        except Exception:
            pass
    try:
        frames[frame_index].evaluate(_PLAY_JS, speed)
    except Exception:
        return False
    time.sleep(2)
    return True


def watch_week(page, week: Week, cfg=None, speed=None, poll=15,
               max_wait_factor=WAIT_FACTOR, on_progress=None,
               on_event=lambda m: None, only=None):
    """한 주차의 모든 영상을 끝까지 자동 시청한다.

    감시·완청 판정은 watch.py 의 검증된 로직을 그대로 쓴다(`_clip_frames` 가
    Kollus 프레임도 알아보도록 넓혀 두었다).

    ⚠️ 배속은 **폴링마다 다시 걸어야** 유지된다. 한 번만 설정하면 Kollus 가
    1 로 되돌린다(실측). `_play_until_end` 가 배속 하락을 보고 복구해 준다.

    ⚠️ 한 주차에 영상이 여러 개이고 **동시에 재생되지 않는다** — 하나를 켜면
    다른 하나가 멈춘다. 그래서 순차로 돌린다.

    ⚠️ 서버는 `runtime`(벽시계)과 `playtime`(영상 위치)을 함께 받는다. 2배까지는
    진도가 깎이지 않는 것을 확인했으니 그 위로는 올리지 않는다.

    return: {"seq", "speed", "clips": [{"clip","status","dur"}…]}
    """
    from watch import (_play_until_end, clamp_speed, clip_inventory,
                       wall_clock_seconds)

    sp = clamp_speed(speed if speed is not None
                     else getattr(cfg, "playback_speed", 2.0))
    open_week(page, week)
    try:    # 돌발퀴즈가 띄우는 네이티브 대화상자로 흐름이 멈추지 않게
        page.on("dialog", lambda d: d.accept())
    except Exception:
        pass

    inv = clip_inventory(page)
    actives = [c for c in inv if c["has"]]
    on_event(f"{week.seq}주차 '{week.name}' — 영상 {len(actives)}개 "
             f"(진도 {week.percent}%)")
    if not actives:
        return {"seq": week.seq, "speed": sp, "clips": [],
                "note": "no_active_clip"}

    if only is not None:    # 한 영상만 시험할 때(검증용)
        actives = [c for c in actives if c["index"] in set(only)]
        on_event(f"  대상 영상만: {[c['index'] for c in actives]}")

    results = []
    for c in actives:
        idx = c["index"]
        if not start_clip(page, idx, sp):
            results.append({"clip": idx, "status": "no_video"})
            continue
        # ⚠️ 길이는 **재생을 시작한 뒤에** 읽는다. Kollus 는 메타데이터를 늦게
        # 채워서 clip_inventory 시점에는 0 으로 나온다 — 그대로 쓰면 예산이
        # 60초가 되어 408초짜리가 108초에 '시간 초과'로 끝난다(실측 사고).
        dur = clip_duration(page, idx, fallback=c.get("dur") or 0)
        if dur > 0:
            budget = wall_clock_seconds(dur / 60.0, sp) * max_wait_factor + 60.0
        else:   # 끝내 못 읽으면 넉넉히 준다. 완청 판정은 예산이 아니라
                # _play_until_end 가 하므로, 예산은 상한 노릇만 한다.
            budget = UNKNOWN_BUDGET_S
        on_event(f"  영상 {idx}: {int(dur)}초 · {sp}배속 · 예산 {int(budget)}초")
        # 대상 영상만 살려 두면서 끝까지 민다(solo_guard 설명 참고)
        ended = _play_until_end(page, idx, sp, budget, poll,
                                solo_guard(page, idx, sp, on_progress))
        trigger_save(page)
        results.append({"clip": idx, "status": "ended" if ended else "timeout",
                        "dur": dur})
        on_event(f"  영상 {idx}: {'완료' if ended else '시간 초과'}")
    trigger_save(page)
    return {"seq": week.seq, "speed": sp, "clips": results}
