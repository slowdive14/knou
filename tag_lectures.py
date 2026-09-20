"""기출 문항에 강(講) 붙이기 — '3강까지 들었으니 3강 문제만' 이 되게.

기출은 회차로만 묶여 있어서 방금 들은 강의의 문제만 골라 풀 수가 없다. 강의
목차를 놓고 문항마다 몇 강의 내용인지 가려 은행 JSON 에 적어 둔다. 한 번 적어
두면 앱이 그 번호로 모아 보여준다(다시 가리지 않는다).

  - 강의 퀴즈(돌발퀴즈·형성평가) : 은행의 차시가 곧 강이라 가릴 것이 없다
  - 기출                        : 목차를 놓고 묶음으로 가린다(20문항씩 한 번)
  - 기출변형                    : 원본 기출의 강을 물려받는다(API 호출 없음)

실행:
    .venv/Scripts/python.exe tag_lectures.py --dry-run   # 무엇을 가릴지만 보기
    .venv/Scripts/python.exe tag_lectures.py
    .venv/Scripts/python.exe tag_lectures.py --year 2019
    .venv/Scripts/python.exe tag_lectures.py --force     # 이미 붙은 것도 다시
    .venv/Scripts/python.exe tag_lectures.py --inherit-only   # 변형만 원본에 맞춰
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 콘솔이 없어도 돈다
    pass

import quiz_lecture as ql

COURSE = "C프로그래밍"


def _log(m):
    print(m, flush=True)


def load_banks(quiz_dir: Path) -> list:
    """퀴즈 폴더의 은행 파일 → [(경로, 내용)] — 기록 파일은 뺀다."""
    out = []
    for p in sorted(Path(quiz_dir).glob("*.json")):
        if p.name.startswith("_"):
            continue
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            _log(f"   ! 읽지 못함: {p.name}")
    return out


def is_variant(bank) -> bool:
    """변형 은행인가 — 원본 기출에서 물려받을 수 있는 것."""
    return str(((bank or {}).get("exam") or {}).get("kind") or "") == "변형문제"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 문항에 강 붙이기")
    ap.add_argument("--course", default=COURSE, help="과목 이름")
    ap.add_argument("--year", type=int, help="이 연도 기출만")
    ap.add_argument("--chunk", type=int, default=ql.CHUNK,
                    help="한 번에 물어볼 문항 수")
    ap.add_argument("--force", action="store_true",
                    help="이미 붙어 있는 문항도 다시 가린다")
    ap.add_argument("--inherit-only", action="store_true",
                    help="기출은 그대로 두고 변형만 원본의 강에 맞춘다")
    ap.add_argument("--dry-run", action="store_true",
                    help="가릴 대상만 세어 보고 API 를 부르지 않는다")
    a = ap.parse_args(argv)

    from config import load_config

    cfg = load_config()
    quiz_dir = Path(cfg.summary_dir) / "퀴즈"
    rows = [(p, b) for p, b in load_banks(quiz_dir)
            if str(b.get("course") or "") == a.course]
    if not rows:
        _log(f"'{a.course}' 은행이 없습니다: {quiz_dir}")
        return 1

    lectures = ql.catalog([b for _p, b in rows], a.course)
    # 목차 제목만으로는 '(1)' 과 '(2)' 를 가를 수 없다 — 그 강 형성평가가
    # 무엇을 묻는지 함께 보여 준다.
    hints = ql.topic_hints([b for _p, b in rows], a.course)
    if not lectures:
        _log("강의 목차를 만들 수 없습니다 — 강의 퀴즈 은행(N강.json)이 있어야 "
             "'몇 강의 내용인지' 를 가릴 기준이 생깁니다.")
        return 1
    _log(f"■ {a.course} — 강의 목차 {len(lectures)}강, 은행 {len(rows)}개")

    exams = [(p, b) for p, b in rows
             if b.get("exam") and not is_variant(b)]
    variants = [(p, b) for p, b in rows if is_variant(b)]
    if a.year:
        exams = [(p, b) for p, b in exams
                 if int((b.get("exam") or {}).get("year") or 0) == a.year]
        variants = [(p, b) for p, b in variants
                    if int((b.get("exam") or {}).get("year") or 0) == a.year]

    def targets(bank):
        qs = bank.get("questions") or []
        return qs if (a.force or a.inherit_only) else ql.untagged(qs)

    todo = sum(len(targets(b)) for _p, b in exams)
    _log(f"   기출 {len(exams)}회차 · 가릴 문항 {todo}개 / "
         f"변형 {len(variants)}회차")
    if a.dry_run:
        for p, b in exams:
            _log(f"   {b.get('name')} — {len(targets(b))}문항")
        return 0
    if a.inherit_only:
        _log("   기출은 그대로 두고 변형만 원본에 맞춥니다.")
    if not todo and not variants:
        _log("   가릴 것이 없습니다(--force 로 다시 가릴 수 있습니다).")
        return 0

    from google import genai

    client = genai.Client(api_key=cfg.gemini_api_key)
    tagged = 0
    for p, b in (() if a.inherit_only else exams):
        part = targets(b)
        if not part:
            continue
        _log(f"── {b.get('name')} — {len(part)}문항")
        got = ql.make_lectures(client, part, lectures, a.course,
                               chunk=a.chunk, on_event=_log, hints=hints)
        n = ql.write_lectures(p, got)
        tagged += n
        _log(f"   저장: {p.name} — {n}문항")

    # 변형은 원본 기출의 강을 물려받는다 — 개념이 같으므로 다시 묻지 않는다.
    index = ql.lecture_index([json.loads(p.read_text(encoding="utf-8"))
                              for p, _b in rows])
    passed = 0
    for p, b in variants:
        got = ql.inherit_map(targets(b), index,
                             force=a.force or a.inherit_only)
        left = [q for q in targets(b) if str(q.get("qid")) not in got]
        if left and not a.inherit_only:
            got.update(ql.make_lectures(client, left, lectures, a.course,
                                        chunk=a.chunk, on_event=_log,
                                        hints=hints))
        n = ql.write_lectures(p, got)
        passed += n
        if n:
            _log(f"   물려받음: {p.name} — {n}문항")

    _log(f"\n■ 완료: 기출 {tagged}문항 · 변형 {passed}문항")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
