"""Phase 2 — 과목/차시 목록 + 진도 파싱.

순수 로직(단위테스트 대상):
  - parse_lecture(raw)      : 차시 1건 JSON dict → Lecture
  - parse_lectures(payload) : retrieveUMYAtlcLectList.ajax 응답 → list[Lecture]
  - filter_incomplete(lects): 영상 있고 아직 미이수인 차시만
  - parse_course_row(row)   : 나의학습 DOM 추출 dict → Course
  - parse_progress(text)    : "55분 / 55분" → (55, 55)

브라우저 연동(수동 검증):
  - list_courses(page)             : 나의학습 페이지 DOM → list[Course]
  - fetch_lectures(page, course)   : 차시 AJAX 호출 → list[Lecture]
  - discover(page)                 : 전 과목 (Course, list[Lecture]) 수집

데이터 출처/필드는 docs/lms-map.md §2~3 참조.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass

LECT_LIST_AJAX = "/ekp/user/study/retrieveUMYAtlcLectList.ajax"


@dataclass(frozen=True)
class Lecture:
    """차시 1개. 진도/이수 + 재생에 필요한 식별자."""
    seq: int            # lectPldcTocSeq (1강, 2강 …)
    name: str           # lectPldcTocNm
    watched_min: int    # stdyHrMnt (시청한 분)
    total_min: int      # vidoHrSec (전체 분)
    prog_rt: int        # lectProgRt (차시 진도 0~100)
    video_done: bool    # stdyCmyn == 'Y' (학습영상 이수완료)
    exam_done: bool     # valuCmyn == 'Y' or examRespYn == 'Y' (연습문제)
    has_video: bool     # useYn == 'Y' (제작 완료된 영상 존재)
    cnts_tc: str        # '01' 내부영상 / '03' 외부링크
    # 재생/식별자
    sbjt_id: str        # sbjtId (KNOU1545001)
    toc_no: str         # lectPldcTocNo
    atlc_no: str        # atlcNo
    enc_sbjt_id: str    # strSbjtId (fnCntsPopup 인자, 암호화)
    enc_toc_no: str     # strLectPldcTocNo
    enc_atlc_no: str    # strAtlcNo
    video_url: str      # vidoUrl (상대경로)
    audio_url: str = ""  # strVidoAudoUrl (MP3 음성 절대 URL, Phase 4 다운로드용)


@dataclass(frozen=True)
class Course:
    """수강 과목 1개."""
    sbjt_id: str        # KNOU1545001 (id="lecture-{sbjtId}" 에서 추출)
    name: str           # 과목명
    progress: float     # 과목 진도율 %
    atlc_no: str        # data-atlc (차시 AJAX 호출용)
    s_type: str         # data-stype
    fmtv_done: bool     # '형성평가완료' 배지 존재


def _to_int(v) -> int:
    """문자열/None/'' → int (실패 시 0). '85.71' 같은 소수도 버림 처리."""
    if v is None:
        return 0
    s = str(v).strip()
    if not s:
        return 0
    try:
        return int(float(s))
    except (ValueError, TypeError):
        return 0


def _to_float(v) -> float:
    if v is None:
        return 0.0
    s = str(v).strip()
    if not s:
        return 0.0
    try:
        return float(s)
    except (ValueError, TypeError):
        return 0.0


def parse_lecture(raw: dict) -> Lecture:
    """차시 1건 raw dict(JSON) → Lecture. 누락/None 필드는 안전 기본값."""
    raw = raw or {}
    return Lecture(
        seq=_to_int(raw.get("lectPldcTocSeq")),
        name=(raw.get("lectPldcTocNm") or "").strip(),
        watched_min=_to_int(raw.get("stdyHrMnt")),
        total_min=_to_int(raw.get("vidoHrSec")),
        prog_rt=_to_int(raw.get("lectProgRt")),
        video_done=raw.get("stdyCmyn") == "Y",
        exam_done=(raw.get("valuCmyn") == "Y") or (raw.get("examRespYn") == "Y"),
        has_video=raw.get("useYn") == "Y",
        cnts_tc=(raw.get("cntsTc") or "").strip(),
        sbjt_id=(raw.get("sbjtId") or "").strip(),
        toc_no=(raw.get("lectPldcTocNo") or "").strip(),
        atlc_no=(raw.get("atlcNo") or "").strip(),
        enc_sbjt_id=(raw.get("strSbjtId") or "").strip(),
        enc_toc_no=(raw.get("strLectPldcTocNo") or "").strip(),
        enc_atlc_no=(raw.get("strAtlcNo") or "").strip(),
        video_url=(raw.get("vidoUrl") or "").strip(),
        audio_url=(raw.get("strVidoAudoUrl") or "").strip(),
    )


def parse_lectures(payload) -> list[Lecture]:
    """retrieveUMYAtlcLectList.ajax 응답(dict 또는 JSON 문자열) → list[Lecture]."""
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return []
    if not isinstance(payload, dict):
        return []
    atlc_list = payload.get("atlcList") or []
    if not atlc_list:
        return []
    lect_list = (atlc_list[0] or {}).get("lectList") or []
    return [parse_lecture(r) for r in lect_list]


def filter_incomplete(lectures) -> list[Lecture]:
    """자동이수 대상: 영상이 있고(has_video) 아직 이수 안 된(video_done=False) 차시."""
    return [l for l in lectures if l.has_video and not l.video_done]


_SBJT_ID_RE = re.compile(r"lecture-([A-Za-z0-9]+)")


def parse_course_row(row: dict) -> Course:
    """list_courses 가 DOM에서 뽑은 dict → Course.

    row 키: id(lecture-{sbjtId}), title, progress, badge, atlcNo, sType
    """
    row = row or {}
    m = _SBJT_ID_RE.search(row.get("id") or "")
    sbjt_id = m.group(1) if m else ""
    badge = (row.get("badge") or "")
    return Course(
        sbjt_id=sbjt_id,
        name=(row.get("title") or "").strip(),
        progress=_to_float(row.get("progress")),
        atlc_no=(row.get("atlcNo") or "").strip(),
        s_type=(row.get("sType") or "").strip(),
        fmtv_done="형성평가완료" in badge,
    )


_PROGRESS_RE = re.compile(r"(\d+)\s*분\s*/\s*(\d+)\s*분")


def parse_progress(text: str) -> tuple[int, int]:
    """'55분 / 55분' → (55, 55). 매칭 실패('-', '') → (0, 0)."""
    m = _PROGRESS_RE.search(text or "")
    if not m:
        return (0, 0)
    return (int(m.group(1)), int(m.group(2)))


# ---------------------------------------------------------------------------
# 브라우저 연동 (수동 검증; 단위테스트 대상 아님)
# ---------------------------------------------------------------------------

_COURSES_JS = """
() => {
  const items = [...document.querySelectorAll('.lecture-progress-item')];
  return items.map(it => {
    const ul = it.querySelector('ul.lecture-list');
    const titleEl = it.querySelector('.lecture-title a, .lecture-title');
    const valEl = it.querySelector('.lecture-per .value');
    const badge = it.querySelector('.divi2');
    return {
      id: it.id || '',
      title: titleEl ? titleEl.textContent.trim() : '',
      progress: valEl ? valEl.textContent.trim() : '',
      badge: badge ? badge.textContent.trim() : '',
      atlcNo: ul ? ul.getAttribute('data-atlc') : null,
      sType: ul ? (ul.getAttribute('data-stype') || ul.getAttribute('data-sType')) : null,
    };
  });
}
"""

# 페이지 컨텍스트에서 jQuery와 동일하게 form-encoded body 로 AJAX 호출 (쿠키 자동 포함)
_FETCH_LECT_JS = """
async ({atlcNo, sType}) => {
  const body = 'atlcNo=' + encodeURIComponent(atlcNo) +
               '&sType=' + encodeURIComponent(sType || '');
  const res = await fetch('%s', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body,
    credentials: 'include',
  });
  return await res.text();
}
""" % LECT_LIST_AJAX


def list_courses(page) -> list[Course]:
    """현재 '나의 학습' 페이지 DOM에서 수강 과목 목록을 읽는다.

    호출 전 page 는 retrieveUMYStudy.sdo 에 로그인된 상태여야 한다
    (auth.ensure_logged_in 이 남겨둔 상태 그대로; 재이동 시 세션 끊김 주의).
    """
    page.wait_for_selector(".lecture-progress-item", timeout=15000)
    rows = page.evaluate(_COURSES_JS)
    return [parse_course_row(r) for r in rows]


def fetch_lectures(page, course: Course) -> list[Lecture]:
    """과목의 차시 목록을 AJAX(JSON)로 가져와 파싱한다."""
    text = page.evaluate(_FETCH_LECT_JS,
                         {"atlcNo": course.atlc_no, "sType": course.s_type})
    return parse_lectures(text)


def discover(page) -> list[tuple[Course, list[Lecture]]]:
    """전 과목 + 각 차시 목록을 수집해 (Course, [Lecture]) 리스트로 반환."""
    result = []
    for course in list_courses(page):
        if not course.atlc_no:
            continue
        result.append((course, fetch_lectures(page, course)))
    return result
