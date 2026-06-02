"""[list_lectures] 경량 강의 목록 수집 — GUI 새로고침용.

로그인 후 전 과목·차시 메타(차시번호/제목/영상이수/연습문제 여부)만 빠르게 모아
프로젝트 루트의 `lectures.json` 으로 저장한다. 영상 시청·다운로드·요약은 하지 않아
GUI '새로고침' 비용을 최소화한다(`runner.parse_lectures_snapshot` 가 읽는 형식).

CLI:  python list_lectures.py            → lectures.json 갱신

⚠️ 비밀번호·GEMINI_API_KEY 등 비밀값은 출력하지 않는다(자식이 .env 에서만 읽음).
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

PROJECT_DIR = Path(__file__).resolve().parent
SNAPSHOT_PATH = PROJECT_DIR / "lectures.json"


def collect_snapshot(cfg=None) -> dict:
    """로그인→전과목 차시 메타 수집→스냅샷 dict 반환(IO; 수동 검증)."""
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from discover import fetch_lectures, list_courses
    from recon import launch_context

    cfg = cfg or load_config()
    courses_out: list[dict] = []
    with sync_playwright() as p:
        ctx = launch_context(p)
        try:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            ensure_logged_in(page, cfg)
            for course in list_courses(page):
                lectures: list[dict] = []
                try:
                    for lec in fetch_lectures(page, course):
                        lectures.append({
                            "seq": lec.seq,
                            "name": lec.name,
                            "video_done": bool(lec.video_done),
                            "exam_done": bool(lec.exam_done),
                            "has_video": bool(lec.has_video),
                            "watched_min": int(getattr(lec, "watched_min", 0)),
                            "total_min": int(getattr(lec, "total_min", 0)),
                        })
                except Exception as e:  # noqa: BLE001 - 과목 단위 격리
                    print(f"  ! 과목 '{course.name}' 차시 조회 실패: "
                          f"{str(e)[:120]}", flush=True)
                courses_out.append({
                    "name": course.name,
                    "sbjt_id": getattr(course, "sbjt_id", ""),
                    "lectures": lectures,
                })
        finally:
            try:
                ctx.close()
            except Exception:
                pass

    return {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "courses": courses_out,
    }


def save_snapshot(snapshot: dict, path=SNAPSHOT_PATH) -> Path:
    """스냅샷을 lectures.json 으로 저장(UTF-8, 한글 보존)."""
    path = Path(path)
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    return path


def main() -> None:
    snap = collect_snapshot()
    out = save_snapshot(snap)
    n_courses = len(snap["courses"])
    n_lect = sum(len(c["lectures"]) for c in snap["courses"])
    print(f"\n강의 목록 저장: {out.name} (과목 {n_courses}개 · 차시 {n_lect}개)",
          flush=True)


if __name__ == "__main__":
    main()
