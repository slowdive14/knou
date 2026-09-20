"""기출 변형 문제 만들기 — 같은 개념, 다른 숫자·코드.

기출을 여러 번 풀면 답을 외워 버린다. 개념은 그대로 두고 숫자·코드만 바꾼 문제를
만들어 **따로 된 은행**에 담는다(기출과 섞지 않는다 — '진짜 기출을 풀었다'는
감각이 흐려진다).

⚠️ 코드 실행 결과를 묻는 문항은 **실제로 컴파일·실행해** 정답을 확인한다.
   C 컴파일러가 없으면 그런 문항은 건너뛴다. 설치하려면:

       winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT

실행:
    .venv/Scripts/python.exe build_variants.py --year 2019
    .venv/Scripts/python.exe build_variants.py --year 2019 --per 2
    .venv/Scripts/python.exe build_variants.py --allow-unverified   # 검증 없이도
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import exam_bank as eb
import quiz_variant as qv

COURSE = "C프로그래밍"


def _log(m):
    print(m, flush=True)


def variant_filename(course: str, year: int, term: int) -> str:
    """변형 은행 파일명 — 기출과 한눈에 구분된다."""
    from download import sanitize
    return f"{sanitize(course)}_변형{int(year)}-{int(term)}.json"


def make_bank(course: str, year: int, term: int, questions) -> dict:
    """변형 은행 dict — 기출과 같은 모양이되 kind 가 '변형' 이다."""
    b = eb.make_bank(course, year, term, questions, kind="변형문제")
    b["seq"] = eb.exam_seq(year, term) + 5       # 같은 회차의 기출 바로 뒤
    return b


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 변형 문제 만들기")
    ap.add_argument("--year", type=int, help="이 연도 기출에서만")
    ap.add_argument("--per", type=int, default=1, help="문항당 변형 개수")
    ap.add_argument("--limit", type=int, help="원본 문항을 이만큼만(시험용)")
    ap.add_argument("--allow-unverified", action="store_true",
                    help="컴파일러가 없어도 코드 문항을 만든다(검증 안 됨 표시)")
    a = ap.parse_args(argv)

    from google import genai

    from config import load_config

    cfg = load_config()
    quiz_dir = Path(cfg.summary_dir) / "퀴즈"
    banks = sorted(quiz_dir.glob(f"*_기출*.json"))
    if a.year:
        banks = [p for p in banks if f"기출{a.year}-" in p.name]
    if not banks:
        _log("기출 은행이 없습니다. 먼저 build_exam_bank.py 를 돌리세요.")
        return 1

    client = genai.Client(api_key=cfg.gemini_api_key)
    total_made = 0
    for p in banks:
        src = json.loads(p.read_text(encoding="utf-8"))
        ex = src.get("exam") or {}
        year, term = int(ex.get("year") or 0), int(ex.get("term") or 0)
        qs = src.get("questions") or []
        # 정답을 모르는 원본은 변형해 봐야 기준이 없다 — 건너뛴다
        qs = [q for q in qs if q.get("answer_no")]
        if a.limit:
            qs = qs[:a.limit]
        _log(f"── {src.get('name')} — 원본 {len(qs)}문항")

        made = qv.make_variants(client, qs, COURSE, per=a.per,
                                allow_unverified=a.allow_unverified,
                                on_event=_log)
        if not made:
            _log("   만들어진 변형이 없습니다.")
            continue
        out = quiz_dir / variant_filename(COURSE, year, term)
        out.write_text(json.dumps(make_bank(COURSE, year, term, made),
                                  ensure_ascii=False, indent=1),
                       encoding="utf-8")
        checked = sum(1 for q in made if q.get("verified"))
        _log(f"   저장: {out.name} — 변형 {len(made)}개 "
             f"(실행으로 확인한 것 {checked}개)")
        total_made += len(made)

    _log(f"\n■ 완료: 변형 {total_made}개")
    if qv.find_compiler() is None:
        _log("   C 컴파일러를 설치하면 코드 문항도 실행으로 확인해 만듭니다:")
        _log("   winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
