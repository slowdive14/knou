"""기출 정답 다시 붙이기 — 중복정답(A~K) 표기를 제대로 읽어서.

정답표 첫머리에는 '중복정답 대조표' 가 있다(C=1,4 / K=1,2,3,4 …). 예전에는
이 글자를 '읽을 수 없는 표기' 로 보고 그 자리를 비워 두어서, 멀쩡한 문항이
'정답을 몰라 설명을 만들 수 없습니다' 로 남아 있었다.

문항은 건드리지 않고 **정답만** 다시 붙인다(비전으로 다시 읽으면 애써 담은
지문·해설이 바뀔 수 있다).

실행:
    .venv/Scripts/python.exe -u fix_answers.py --dry-run
    .venv/Scripts/python.exe -u fix_answers.py
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 콘솔이 없어도 돈다
    pass

import exam_bank as eb

COURSE = "C프로그래밍"
ANSWER_ROOT = Path("downloads/_기출/정답표")


def _log(m):
    print(m, flush=True)


def answer_candidates(root, year, term) -> list:
    """그 회차의 정답표 후보 파일들(학년별로 나뉜 해가 있다)."""
    d = Path(root) / str(year)
    if not d.exists():
        return []
    want = f"{int(term)}학기"
    return [p for p in sorted(d.glob("*.hwp")) if want in p.name]


def read_answers(root, year, term, course=COURSE, expect=25) -> list:
    """정답표에서 그 과목 정답을 읽는다 — 개수가 맞는 첫 파일을 쓴다."""
    for p in answer_candidates(root, year, term):
        try:
            got = eb.parse_answer_lines(eb.hwp_text(p), course, expect)
        except Exception:  # noqa: BLE001 - 학년이 다른 표일 수 있다
            continue
        if len(got) == expect:
            return got
    return []


def changes(questions, answers) -> list:
    """(문항번호, 예전 정답, 새 정답) — 달라지는 것만."""
    fixed, _warn = eb.attach_answers(questions, answers)
    out = []
    for old, new in zip(questions, fixed):
        was = [int(old.get("answer_no") or 0)] if old.get("answer_no") else []
        if isinstance(old.get("answer_nos"), list):
            was = [int(x) for x in old["answer_nos"]]
        now = [int(new.get("answer_no") or 0)] if new.get("answer_no") else []
        if isinstance(new.get("answer_nos"), list):
            now = [int(x) for x in new["answer_nos"]]
        if was != now:
            out.append((str(old.get("qid")), was, now))
    return out


def apply_to_bank(path, answers) -> int:
    """은행 JSON 의 정답만 갈아 끼운다 → 바뀐 문항 수.

    ⚠️ 임시 파일에 쓴 뒤 바꿔치기한다 — 도중에 멈춰 반쪽짜리가 남으면 그
    회차를 통째로 잃는다.
    """
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    qs = data.get("questions") or []
    fixed, _warn = eb.attach_answers(qs, answers)
    if len(fixed) != len(qs):
        return 0
    hit = 0
    for i, (old, new) in enumerate(zip(qs, fixed)):
        if new == old:
            continue
        qs[i] = new
        hit += 1
    if not hit:
        return 0
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        return 0
    return hit


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 정답 다시 붙이기")
    ap.add_argument("--course", default=COURSE)
    ap.add_argument("--root", default=str(ANSWER_ROOT), help="정답표 폴더")
    ap.add_argument("--dry-run", action="store_true", help="무엇이 바뀌는지만")
    a = ap.parse_args(argv)

    from config import load_config

    quiz_dir = Path(load_config().summary_dir) / "퀴즈"
    banks = sorted(quiz_dir.glob("*_기출*.json"))
    if not banks:
        _log("기출 은행이 없습니다.")
        return 1

    total = 0
    for p in banks:
        try:
            b = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if str(b.get("course") or "") != a.course:
            continue
        ex = b.get("exam") or {}
        year, term = int(ex.get("year") or 0), int(ex.get("term") or 0)
        qs = b.get("questions") or []
        ans = read_answers(a.root, year, term, a.course, len(qs))
        if not ans:
            _log(f"── {b.get('name')} — 정답표를 찾지 못했습니다")
            continue
        rows = changes(qs, ans)
        _log(f"── {b.get('name')} — 바뀌는 문항 {len(rows)}개")
        for qid, was, now in rows:
            _log(f"   {qid}: {was or '(모름)'} → {now}")
        if rows and not a.dry_run:
            total += apply_to_bank(p, ans)

    if a.dry_run:
        _log("\n■ 살펴보기만 했습니다(--dry-run).")
    else:
        _log(f"\n■ 완료: {total}문항의 정답을 고쳤습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
