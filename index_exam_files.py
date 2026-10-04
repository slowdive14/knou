"""기출 원본 회차표 만들기 — 시험지마다 몇 년도 몇 학기인지 적어 둔다.

퀴즈 화면의 '시험지' 단추는 이 표를 보고 파일을 연다. 화면은 AI 를 부르지
않으므로, 글자 층이 없는 시험지(대부분이다)는 여기서 한 번 읽어 둬야 한다.
이미 적힌 시험지는 다시 묻지 않는다.

정답표는 표가 필요 없다 — 파일 안의 '20XX학년도 N학기' 머리줄로 그때그때
찾는다. 여기서는 과목마다 어느 회차가 짝지어졌는지 보여 주기만 한다.

실행:
    .venv/Scripts/python.exe index_exam_files.py              # 아직 안 읽은 것만
    .venv/Scripts/python.exe index_exam_files.py --no-ai      # 표에 적힌 것만 보기
    .venv/Scripts/python.exe index_exam_files.py --course 자료구조

⚠️ 원본 파일은 읽기만 한다. 서버에 아무것도 보내지 않는다(AI 에 첫 쪽 그림만).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 콘솔이 없어도 돈다
    pass

import exam_files as xf
from fetch_exam_figures import exam_banks, gemini_client


def _log(m):
    print(m, flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 원본 회차표 만들기")
    ap.add_argument("--course", help="이 과목만(기본: 기출 은행이 있는 과목 전부)")
    ap.add_argument("--no-ai", action="store_true",
                    help="글줄 없는 시험지를 AI 에게 묻지 않는다")
    a = ap.parse_args(argv)

    from config import load_config
    from quiz_page import default_quiz_paths
    cfg = load_config()
    quiz_dir = Path(default_quiz_paths(cfg)[0])
    work = Path(cfg.downloads_dir) / "_기출"

    courses = [a.course] if a.course else sorted(
        {str(d.get("course") or "") for _p, d in exam_banks(quiz_dir)} - {""})
    if not courses:
        _log("■ 기출 은행이 없습니다.")
        return 1
    client = None if a.no_ai else gemini_client()

    for c in courses:
        _log(f"■ {c}")
        sheets = xf.sheet_files(work, c, client, _log)
        answers = xf.answer_spots(work, c)
        found = {p for ps in sheets.values() for p in ps}
        for p in xf.sheet_pdfs(work, c):
            if p not in found:
                _log(f"   ? {p.name} — 회차를 모릅니다"
                     + ("" if client else "(--no-ai 를 빼면 AI 가 읽습니다)"))
        for key in sorted(set(sheets) | set(answers)):
            ps = sheets.get(key) or []
            sp = answers.get(key)
            sheet = ps[0].name if ps else "시험지 없음"
            more = f" 외 {len(ps) - 1}벌" if len(ps) > 1 else ""
            ans = (f"{sp['file'].name}" + (" (여러 회차 중)" if sp["many"] else "")
                   if sp else "정답표 없음")
            _log(f"   {xf.term_label(key)} | {sheet}{more} | {ans}")
    _log(f"\n회차표: {xf.index_path(work)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
