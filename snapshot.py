"""[snapshot] 강의 목록 스냅샷(lectures.json) 만들기·저장.

앱은 **로그인 없이 즉시** 뜨어야 하므로 과목·차시 목록을 파일로 들고 있는다
(드롭다운·현황 화면이 이걸 읽는다). 문제는 이수를 마쳐도 이 파일이 그대로라
차시 목록의 ✅ 가 안 붙고, 사람이 [목록 새로고침]을 눌러야 했다는 것.

그런데 `main.run()` 은 실행할 때마다 이미 LMS 에서 전 과목 차시를 받아온다.
로그인된 브라우저가 열려 있는 그 순간에 다시 한 번 받아 저장하면, 새 로그인
없이 목록이 최신이 된다 → 사람이 새로고침을 누를 일이 거의 없어진다.

  - lecture_entry(lec)              : Lecture → 스냅샷 항목 dict (순수)
  - build_snapshot(pairs)           : [(course, [lec…])] → 스냅샷 dict (순수)
  - save_snapshot(snap, path)       : lectures.json 저장(UTF-8, 한글 보존)
  - refresh_snapshot(page, path)    : 열린 세션으로 받아 저장(IO)

⚠️ 비밀값은 담지 않는다(차시 메타만).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = PROJECT_DIR / "lectures.json"


def lecture_entry(lec) -> dict:
    """Lecture(또는 같은 속성을 가진 객체) → 스냅샷 한 항목.

    `runner.parse_lectures_snapshot` 가 읽는 형식과 같아야 한다.
    """
    return {
        "seq": int(getattr(lec, "seq", 0)),
        "name": getattr(lec, "name", "") or "",
        "video_done": bool(getattr(lec, "video_done", False)),
        "exam_done": bool(getattr(lec, "exam_done", False)),
        "has_video": bool(getattr(lec, "has_video", False)),
        "watched_min": int(getattr(lec, "watched_min", 0) or 0),
        "total_min": int(getattr(lec, "total_min", 0) or 0),
    }


def build_snapshot(pairs, now=None) -> dict:
    """[(course, [lec, …]), …] → 스냅샷 dict(과목 순서 유지)."""
    courses = []
    for course, lectures in pairs:
        courses.append({
            "name": getattr(course, "name", "") or "",
            "sbjt_id": getattr(course, "sbjt_id", "") or "",
            "lectures": [lecture_entry(l) for l in lectures],
        })
    stamp = now or datetime.now()
    return {"generated_at": stamp.isoformat(timespec="seconds"),
            "courses": courses}


def snapshot_counts(snap: dict) -> tuple[int, int]:
    """(과목 수, 차시 수) — 로그 문구용."""
    courses = list(snap.get("courses") or [])
    return len(courses), sum(len(c.get("lectures") or []) for c in courses)


def save_snapshot(snapshot: dict, path=SNAPSHOT_PATH) -> Path:
    """스냅샷을 lectures.json 으로 저장(UTF-8, 한글 보존)."""
    path = Path(path)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def refresh_snapshot(page, path=SNAPSHOT_PATH, on_event=lambda m: None):
    """**이미 로그인된** page 로 목록을 다시 받아 저장한다. 반환: 스냅샷 dict|None.

    실행이 끝난 뒤 부르면 이수 결과가 반영된 목록이 저장된다. 여기서 실패해도
    실행 자체는 이미 끝났으므로 예외를 밖으로 내보내지 않는다(None 반환).
    """
    from discover import fetch_lectures, list_courses

    try:
        pairs = []
        for course in list_courses(page):
            try:
                pairs.append((course, list(fetch_lectures(page, course))))
            except Exception as e:  # noqa: BLE001 - 과목 단위 격리
                on_event(f"목록 갱신: 과목 '{getattr(course, 'name', '?')}' "
                         f"조회 실패 — {str(e)[:100]}")
        if not pairs:
            return None
        snap = build_snapshot(pairs)
        save_snapshot(snap, path)
        n_c, n_l = snapshot_counts(snap)
        on_event(f"강의 목록 갱신: 과목 {n_c}개 · 차시 {n_l}개")
        return snap
    except Exception as e:  # noqa: BLE001 - 갱신 실패가 실행 결과를 가리지 않게
        on_event(f"강의 목록 갱신 실패(무시): {str(e)[:120]}")
        return None
