"""[status_page] 학습 현황 수집 — 과목·차시별로 무엇이 만들어졌는지 한 곳에 모은다.

흩어져 있는 네 곳을 한 줄로 합친다:
  - lectures.json  : LMS 기준 영상이수(video_done)·형성평가(exam_done)·진도
  - state.json     : 우리가 돌린 단계 기록(watch/exam/download/summarize/…)
  - downloads/     : MP3(…_N강.mp3) · 강의록(…_N강.pdf|pptx|ppt|hwp…)
  - 볼트 요약폴더  : 예습노트(…N강 - 제목.md) · 두 번째 영상 노트 (2) · 퀴즈 은행

  - scan_lecture(row, state, …)  : 차시 1줄 → 현황 dict(파일 경로·링크 포함)
    (파일 dict = {name, path, url, ext, size_mb} — path 는 앱 화면이, url 은 HTML 이 쓴다)
  - collect_status(cfg, …)       : 과목별로 묶은 현황 [{course, rows, stats}]
  - course_stats(rows)           : 과목 요약(이수 n/N · 노트 n/N · 형성평가 n/N)
  - default_status_path(cfg)     : 볼트/학습현황.html
  - write_status_page(cfg, …)    : 현황 HTML 생성·저장(+퀴즈 페이지 링크)

파일 존재만 보고 판단하므로 로그인·네트워크가 필요 없다(오프라인).
⚠️ 비밀값은 담기지 않는다(과목명·차시명·파일 경로만).
"""
from __future__ import annotations

import json
from pathlib import Path

from download import sanitize

# 강의록으로 인정하는 확장자(우선순위 순) — download.py 가 저장하는 형식들
DOC_EXTS = ("pdf", "pptx", "ppt", "hwpx", "hwp", "zip")
DOC_KIND = {"pdf": "PDF", "pptx": "PPT", "ppt": "PPT",
            "hwpx": "한글", "hwp": "한글", "zip": "ZIP"}


def _file_info(path) -> dict | None:
    """파일이 있으면 {name,url,size_mb,ext}, 없으면 None."""
    p = Path(path)
    try:
        if not p.exists() or p.stat().st_size == 0:
            return None
        size = p.stat().st_size
    except OSError:
        return None
    return {"name": p.name, "path": str(p), "url": p.as_uri(),
            "ext": p.suffix.lstrip(".").lower(),
            "size_mb": round(size / (1024 * 1024), 1)}


def find_doc(downloads_dir, course: str, seq) -> dict | None:
    """차시 강의록 파일(pdf/ppt/한글…) 하나 — DOC_EXTS 우선순위로 찾는다."""
    base = f"{sanitize(course)}_{int(seq)}강"
    for ext in DOC_EXTS:
        info = _file_info(Path(downloads_dir) / f"{base}.{ext}")
        if info:
            info["kind"] = DOC_KIND.get(ext, ext.upper())
            return info
    return None


def find_notes(summary_dir, course: str, seq, name: str) -> list[dict]:
    """예습노트 목록 — 본노트 먼저, 두 번째 영상 노트((2)…)가 뒤따른다."""
    from summarize import note_filename
    out = []
    main = _file_info(Path(summary_dir) / note_filename(course, seq, name))
    if main:
        main["part"] = 1
        out.append(main)
    part = 2
    while True:
        from extra_video import extra_note_name
        p = Path(summary_dir) / note_filename(course, seq,
                                              extra_note_name(name, part))
        info = _file_info(p)
        if not info:
            break
        info["part"] = part
        out.append(info)
        part += 1
    return out


def quiz_count(quiz_dir, course: str, seq) -> int:
    """이 차시 퀴즈 은행에 모인 문항 수(없으면 0)."""
    p = Path(quiz_dir) / f"{sanitize(course)}_{int(seq)}강.json"
    if not p.exists():
        return 0
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    return len((data or {}).get("questions") or [])


def _stage_rec(state: dict, key: str, stage: str) -> dict:
    return ((state.get(key, {}) or {}).get(stage) or {})


def _stage_ok(state: dict, key: str, stage: str) -> bool:
    return bool(_stage_rec(state, key, stage).get("ok"))


def ran_after_snapshot(state: dict, key: str, stage: str,
                       snapshot_at: str) -> bool:
    """그 단계를 '목록 스냅샷을 받아온 뒤'에 성공했으면 True.

    lectures.json 은 새로고침할 때만 갱신되므로, 스냅샷 이후에 이수/형성평가를
    돌렸다면 LMS 기준 미완료로 보이는 게 당연하다 — 이 경우를 구분해 표시한다.
    (둘 다 같은 ISO-8601 형식이라 문자열 비교로 충분하다.)
    """
    rec = _stage_rec(state, key, stage)
    at = str(rec.get("at") or "")
    return bool(rec.get("ok") and at and snapshot_at and at > str(snapshot_at))


def scan_lecture(row, state: dict, *, downloads_dir, summary_dir,
                 quiz_dir, snapshot_at: str = "") -> dict:
    """차시 1개(runner.LectureRow) → 현황 dict.

    'LMS 기준 완료'(video_done/exam_done)와 '우리가 돌린 기록'(state)을 나눠 담는다
    — 실행은 했는데 서버 이수는 아직인 경우를 구분해 보여주기 위함.
    """
    from extra_video import STATE_FIELD
    key = f"{row.course}|{int(row.seq)}"
    rec = state.get(key, {}) or {}
    notes = find_notes(summary_dir, row.course, row.seq, row.name)
    return {
        "course": row.course,
        "seq": int(row.seq),
        "name": row.name,
        "video_done": bool(row.video_done),
        "exam_done": bool(row.exam_done),
        "watched_min": int(getattr(row, "watched_min", 0) or 0),
        "total_min": int(getattr(row, "total_min", 0) or 0),
        "watch_run": _stage_ok(state, key, "watch"),
        "exam_run": _stage_ok(state, key, "exam"),
        "watch_new": ran_after_snapshot(state, key, "watch", snapshot_at),
        "exam_new": ran_after_snapshot(state, key, "exam", snapshot_at),
        "notes": notes,
        "mp3": _file_info(Path(downloads_dir)
                          / f"{sanitize(row.course)}_{int(row.seq)}강.mp3"),
        "doc": find_doc(downloads_dir, row.course, row.seq),
        "quiz_count": quiz_count(quiz_dir, row.course, row.seq),
        "extra_videos": list(rec.get(STATE_FIELD) or []),
        "extra_done": _stage_ok(state, key, "extra"),
    }


def course_stats(rows) -> dict:
    """과목 요약 — 전체 차시 수와 이수·노트·형성평가·MP3·강의록 개수.

    이수/형성평가는 '목록 갱신 전에 실행한 것'(watch_new/exam_new)도 센다 —
    줄에는 ✅ 로 보이는데 합계는 0 으로 나오는 모순을 막기 위함.
    """
    rows = list(rows or [])
    return {
        "total": len(rows),
        "watched": sum(1 for r in rows
                       if r["video_done"] or r.get("watch_new")),
        "noted": sum(1 for r in rows if r["notes"]),
        "exam": sum(1 for r in rows if r["exam_done"] or r.get("exam_new")),
        "mp3": sum(1 for r in rows if r["mp3"]),
        "doc": sum(1 for r in rows if r["doc"]),
        "quiz": sum(r["quiz_count"] for r in rows),
    }


def collect_status(cfg, snapshot_path, state_path) -> list[dict]:
    """lectures.json + state.json + 파일 스캔 → 과목별 현황 목록.

    return: [{"course","rows":[…],"stats":{…}}, …] (스냅샷 등장 순서 유지)
    """
    from extra_video import read_state
    from runner import parse_lectures_snapshot

    snap = Path(snapshot_path)
    data = {}
    if snap.exists():
        try:
            data = json.loads(snap.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data = {}
    rows = parse_lectures_snapshot(data)
    state = read_state(state_path)
    snap_at = str((data or {}).get("generated_at") or "")

    summary_dir = Path(cfg.summary_dir)
    quiz_dir = summary_dir / "퀴즈"
    downloads_dir = Path(cfg.downloads_dir)

    out: list[dict] = []
    by_course: dict[str, list] = {}
    for row in rows:
        if row.course not in by_course:
            by_course[row.course] = []
            out.append({"course": row.course, "rows": by_course[row.course]})
        by_course[row.course].append(
            scan_lecture(row, state, downloads_dir=downloads_dir,
                         summary_dir=summary_dir, quiz_dir=quiz_dir,
                         snapshot_at=snap_at))
    for c in out:
        c["rows"].sort(key=lambda r: r["seq"])
        c["stats"] = course_stats(c["rows"])
    return out


def snapshot_time(snapshot_path) -> str:
    """lectures.json 의 generated_at(목록을 언제 받아왔는지). 없으면 ''."""
    p = Path(snapshot_path)
    if not p.exists():
        return ""
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return ""
    return str((data or {}).get("generated_at") or "")


def default_status_path(cfg) -> Path:
    """현황 페이지 기본 경로 — 볼트 요약폴더/학습현황.html."""
    return Path(cfg.summary_dir) / "학습현황.html"


def write_status_page(cfg, snapshot_path, state_path, out_path=None,
                      title: str = "방송대 학습 현황") -> Path:
    """현황 HTML 을 만들어 저장하고 경로를 돌려준다.

    퀴즈 은행에 문항이 있으면 퀴즈 복습 페이지도 함께 갱신해 링크를 건다
    (현황 페이지의 '형성평가 N문항' 을 눌러 바로 풀어볼 수 있게).
    """
    from status_html import render_status_html

    out = Path(out_path) if out_path else default_status_path(cfg)
    courses = collect_status(cfg, snapshot_path, state_path)

    quiz_url = None
    try:
        from quiz_page import collect_banks, default_quiz_paths, write_quiz_page
        quiz_dir, quiz_out = default_quiz_paths(cfg)
        if collect_banks(quiz_dir):
            quiz_url = write_quiz_page(quiz_dir, quiz_out).as_uri()
    except Exception:  # noqa: BLE001 - 퀴즈 페이지 실패가 현황 페이지를 막지 않게
        quiz_url = None

    html = render_status_html(courses, title=title, quiz_url=quiz_url,
                              generated_at=snapshot_time(snapshot_path))
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    return out
