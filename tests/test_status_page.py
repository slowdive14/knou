"""status_page 수집 단위테스트 — 과목·차시별 현황을 파일에서 읽어낸다.

lectures.json(스냅샷) + state.json(단계 기록) + downloads/·볼트 파일 존재를
합쳐 한 줄로 만드는 로직을 tmp_path 로 검증한다(로그인·네트워크 없음).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from runner import LectureRow  # noqa: E402
from status_page import (  # noqa: E402
    collect_status,
    course_stats,
    default_status_path,
    find_doc,
    find_notes,
    quiz_count,
    ran_after_snapshot,
    scan_lecture,
    snapshot_time,
    write_status_page,
)


class _Cfg:
    def __init__(self, summary_dir, downloads_dir):
        self.summary_dir = summary_dir
        self.downloads_dir = downloads_dir


def _touch(p: Path, size: int = 10) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"x" * size)
    return p


def _row(course="C프로그래밍", seq=1, name="C 언어의 개요",
         video_done=False, exam_done=False, watched=0, total=49):
    return LectureRow(course, seq, name, video_done, exam_done, watched, total)


def _dirs(tmp_path):
    return {"downloads_dir": tmp_path / "downloads",
            "summary_dir": tmp_path / "vault",
            "quiz_dir": tmp_path / "vault" / "퀴즈"}


# --- 파일 탐지 -------------------------------------------------------------
def test_find_doc_prefers_pdf(tmp_path):
    _touch(tmp_path / "C프로그래밍_1강.pptx")
    _touch(tmp_path / "C프로그래밍_1강.pdf")
    doc = find_doc(tmp_path, "C프로그래밍", 1)
    assert doc["ext"] == "pdf" and doc["kind"] == "PDF"


def test_find_doc_falls_back_to_ppt(tmp_path):
    _touch(tmp_path / "C프로그래밍_2강.pptx")
    assert find_doc(tmp_path, "C프로그래밍", 2)["kind"] == "PPT"


def test_find_doc_missing_is_none(tmp_path):
    assert find_doc(tmp_path, "C프로그래밍", 9) is None


def test_zero_byte_file_counts_as_missing(tmp_path):
    _touch(tmp_path / "C프로그래밍_3강.pdf", size=0)
    assert find_doc(tmp_path, "C프로그래밍", 3) is None


def test_find_notes_includes_second_video_note(tmp_path):
    _touch(tmp_path / "자료구조 1강 - 배열.md")
    _touch(tmp_path / "자료구조 1강 - 배열 (2).md")
    notes = find_notes(tmp_path, "자료구조", 1, "배열")
    assert [n["part"] for n in notes] == [1, 2]


def test_find_notes_empty_when_none(tmp_path):
    assert find_notes(tmp_path, "자료구조", 1, "배열") == []


def test_quiz_count_reads_bank(tmp_path):
    p = tmp_path / "C프로그래밍_1강.json"
    _touch(p)
    p.write_text(json.dumps({"questions": [{"qid": "1"}, {"qid": "2"}]}),
                 encoding="utf-8")
    assert quiz_count(tmp_path, "C프로그래밍", 1) == 2


def test_quiz_count_missing_is_zero(tmp_path):
    assert quiz_count(tmp_path, "C프로그래밍", 7) == 0


def test_quiz_count_broken_json_is_zero(tmp_path):
    (tmp_path / "C프로그래밍_1강.json").write_text("{oops", encoding="utf-8")
    assert quiz_count(tmp_path, "C프로그래밍", 1) == 0


# --- scan_lecture ----------------------------------------------------------
def test_scan_lecture_collects_every_asset(tmp_path):
    d = _dirs(tmp_path)
    _touch(d["downloads_dir"] / "C프로그래밍_1강.mp3")
    _touch(d["downloads_dir"] / "C프로그래밍_1강.pdf")
    _touch(d["summary_dir"] / "C프로그래밍 1강 - C 언어의 개요.md")
    (d["quiz_dir"] / "").mkdir(parents=True, exist_ok=True)
    (d["quiz_dir"] / "C프로그래밍_1강.json").write_text(
        json.dumps({"questions": [{"qid": "1"}]}), encoding="utf-8")

    r = scan_lecture(_row(video_done=True), {}, **d)
    assert r["video_done"] is True
    assert r["mp3"]["name"].endswith(".mp3")
    assert r["doc"]["kind"] == "PDF"
    assert len(r["notes"]) == 1
    assert r["quiz_count"] == 1
    assert r["notes"][0]["url"].startswith("file:")


def test_scan_lecture_missing_assets_are_none(tmp_path):
    r = scan_lecture(_row(), {}, **_dirs(tmp_path))
    assert r["mp3"] is None and r["doc"] is None and r["notes"] == []
    assert r["quiz_count"] == 0 and r["watch_run"] is False


def test_scan_lecture_reads_stage_records(tmp_path):
    state = {"C프로그래밍|1": {"watch": {"ok": True}, "exam": {"ok": False}}}
    r = scan_lecture(_row(), state, **_dirs(tmp_path))
    assert r["watch_run"] is True and r["exam_run"] is False


def test_scan_lecture_carries_extra_video_record(tmp_path):
    state = {"자료구조|1": {"extra_videos": [{"idx": 1, "duration": 900}]}}
    r = scan_lecture(_row("자료구조", 1, "배열"), state, **_dirs(tmp_path))
    assert len(r["extra_videos"]) == 1 and r["extra_done"] is False


# --- 오래된 스냅샷 구분 -----------------------------------------------------
def test_ran_after_snapshot_true_when_newer():
    state = {"C프로그래밍|1": {"watch": {"ok": True, "at": "2026-08-17T14:04:04"}}}
    assert ran_after_snapshot(state, "C프로그래밍|1", "watch",
                              "2026-08-17T12:09:22") is True


def test_ran_after_snapshot_false_when_older():
    state = {"C프로그래밍|1": {"watch": {"ok": True, "at": "2026-08-16T09:00:00"}}}
    assert ran_after_snapshot(state, "C프로그래밍|1", "watch",
                              "2026-08-17T12:09:22") is False


def test_ran_after_snapshot_false_when_stage_failed():
    state = {"C프로그래밍|1": {"watch": {"ok": False, "at": "2026-08-18T09:00:00"}}}
    assert ran_after_snapshot(state, "C프로그래밍|1", "watch",
                              "2026-08-17T12:09:22") is False


def test_scan_lecture_marks_fresh_run(tmp_path):
    state = {"C프로그래밍|1": {"watch": {"ok": True, "at": "2026-08-17T14:04:04"}}}
    r = scan_lecture(_row(), state, snapshot_at="2026-08-17T12:09:22",
                     **_dirs(tmp_path))
    assert r["watch_new"] is True


# --- 통계 ------------------------------------------------------------------
def test_course_stats_counts_each_column():
    rows = [
        {"video_done": True, "exam_done": True, "notes": [{"part": 1}],
         "mp3": {"name": "a.mp3"}, "doc": {"name": "a.pdf"}, "quiz_count": 4},
        {"video_done": False, "exam_done": False, "notes": [], "mp3": None,
         "doc": None, "quiz_count": 0},
    ]
    st = course_stats(rows)
    assert st == {"total": 2, "watched": 1, "noted": 1, "exam": 1,
                  "mp3": 1, "doc": 1, "quiz": 4}


def test_course_stats_counts_fresh_runs_too():
    # 줄에는 ✅ 로 보이는데 합계만 0 이면 모순 → 갱신 전 실행도 센다
    rows = [{"video_done": False, "watch_new": True, "exam_done": False,
             "exam_new": True, "notes": [], "mp3": None, "doc": None,
             "quiz_count": 0}]
    st = course_stats(rows)
    assert st["watched"] == 1 and st["exam"] == 1


def test_course_stats_empty():
    assert course_stats([])["total"] == 0


# --- collect_status / 저장 --------------------------------------------------
def _snapshot(tmp_path, generated_at="2026-08-17T12:09:22"):
    p = tmp_path / "lectures.json"
    p.write_text(json.dumps({
        "generated_at": generated_at,
        "courses": [
            {"name": "C프로그래밍", "lectures": [
                {"seq": 2, "name": "자료형", "video_done": False},
                {"seq": 1, "name": "C 언어의 개요", "video_done": True}]},
            {"name": "자료구조", "lectures": [
                {"seq": 1, "name": "배열", "video_done": False}]},
        ]}, ensure_ascii=False), encoding="utf-8")
    return p


def test_collect_status_groups_by_course_and_sorts_by_seq(tmp_path):
    cfg = _Cfg(tmp_path / "vault", tmp_path / "downloads")
    out = collect_status(cfg, _snapshot(tmp_path), tmp_path / "state.json")
    assert [c["course"] for c in out] == ["C프로그래밍", "자료구조"]
    assert [r["seq"] for r in out[0]["rows"]] == [1, 2]
    assert out[0]["stats"]["watched"] == 1


def test_collect_status_missing_snapshot_is_empty(tmp_path):
    cfg = _Cfg(tmp_path / "vault", tmp_path / "downloads")
    assert collect_status(cfg, tmp_path / "none.json", tmp_path / "s.json") == []


def test_snapshot_time_reads_generated_at(tmp_path):
    assert snapshot_time(_snapshot(tmp_path)) == "2026-08-17T12:09:22"


def test_snapshot_time_missing_is_blank(tmp_path):
    assert snapshot_time(tmp_path / "none.json") == ""


def test_default_status_path_is_in_vault(tmp_path):
    cfg = _Cfg(tmp_path / "vault", tmp_path / "downloads")
    assert default_status_path(cfg).name == "학습현황.html"


def test_write_status_page_creates_html(tmp_path):
    cfg = _Cfg(tmp_path / "vault", tmp_path / "downloads")
    out = write_status_page(cfg, _snapshot(tmp_path), tmp_path / "state.json")
    text = out.read_text(encoding="utf-8")
    assert out.exists() and text.lstrip().startswith("<!DOCTYPE html>")
    assert "C프로그래밍" in text and "자료구조" in text


def test_write_status_page_without_quiz_bank_is_safe(tmp_path):
    # 퀴즈 은행이 없어도 페이지는 만들어져야 한다(퀴즈 링크만 빠짐)
    cfg = _Cfg(tmp_path / "vault", tmp_path / "downloads")
    out = write_status_page(cfg, _snapshot(tmp_path), tmp_path / "state.json")
    assert "퀴즈 복습 페이지" not in out.read_text(encoding="utf-8")
