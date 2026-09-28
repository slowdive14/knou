"""단톡방 인증 → 진도 트래커 — 지난 기록을 한 번에 심는다.

'자료구조 1강 들었습니다' 하고 올린 기록이 곧 실제로 본 강의다(LMS 의 이수는
이 프로그램이 영상을 돌려 채운 것이라 다르다). 카카오톡 대화를 내보내
이 명령에 물리면, 앱의 [진도] 탭이 그대로 채워진다.

한 번 심고 나면 그 뒤로는 앱에서 강 번호를 눌러 가며 쓰면 된다. 다시 심어도
**이미 적혀 있는 날짜는 건드리지 않는다**(손으로 눌러 둔 것을 덮지 않는다).

실행:
    .venv/Scripts/python.exe import_kakao.py --file 대화.txt --nick 잔향 --dry
    .venv/Scripts/python.exe import_kakao.py --file 대화.txt --nick 잔향
    .venv/Scripts/python.exe import_kakao.py --file 대화.txt --nick 잔향 \\
        --goal 2026-11-16
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

import kakao_log as kl
import study_plan as sp

PROJECT_ROOT = Path(__file__).resolve().parent
SNAPSHOT_PATH = PROJECT_ROOT / "lectures.json"

# 목표에서 빼는 과목 — 앱의 [진도] 탭과 같은 기준을 쓴다.
SKIP = sp.SKIP_COURSES + ("AI네이티브가되기위한기초소양",)


def _log(m):
    print(m, flush=True)


def read_log(path) -> str:
    """대화 파일을 읽는다 — 카톡이 내보낸 인코딩을 차례로 시도한다."""
    p = Path(path)
    for enc in ("utf-8", "utf-8-sig", "cp949"):
        try:
            return p.read_text(encoding=enc)
        except UnicodeDecodeError:
            continue
    return p.read_text(encoding="utf-8", errors="replace")


def report(found, plan, before) -> list:
    """무엇이 새로 들어갔는지 과목마다 한 줄."""
    out = []
    for c in sp.course_rows(plan):
        name = c["course"]
        was = len(((before or {}).get("watched") or {}).get(name) or {})
        got = len((found or {}).get(name) or {})
        mark = f" (새로 {c['done'] - was})" if c["done"] > was else ""
        out.append(f"   {name} — {c['done']}/{c['total']}강{mark}"
                   f"{'' if got else '  · 대화에 없음'}")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="단톡방 인증을 진도 트래커에 심기")
    ap.add_argument("--file", required=True, help="카카오톡 대화 내보내기 파일")
    ap.add_argument("--nick", required=True, help="내 닉네임(앞부분만 맞으면 된다)")
    ap.add_argument("--goal", default=sp.DEFAULT_GOAL,
                    help=f"목표일(기본 {sp.DEFAULT_GOAL})")
    ap.add_argument("--dry", action="store_true", help="심지 않고 보기만")
    a = ap.parse_args(argv)

    from config import load_config
    cfg = load_config()
    path = sp.plan_path(cfg)
    plan = sp.load_plan(path)

    courses = plan.get("courses") or sp.courses_from_lectures(SNAPSHOT_PATH,
                                                              skip=SKIP)
    if not courses:
        _log("■ 과목을 찾지 못했습니다 — lectures.json 이 없습니다.")
        return 1

    text = read_log(a.file)
    found = kl.parse_log(text, a.nick, courses)
    if not found:
        _log(f"■ '{a.nick}' 님의 인증을 찾지 못했습니다. 닉네임을 확인해 주세요.")
        return 1

    before = dict(plan)
    if not plan:
        plan = sp.make_plan(courses, a.goal, kl.first_day(found))
    else:
        plan["courses"] = courses
        plan.setdefault("goal", a.goal)
        plan.setdefault("start", kl.first_day(found))
    plan = sp.merge_watched(plan, found)

    _log(f"■ 대화에서 찾은 인증: {kl.count(found)}강 "
         f"(첫 인증 {kl.first_day(found)})")
    for line in report(found, plan, before):
        _log(line)
    _log("")
    _log(f"■ {sp.status_line(plan)}")
    got = sp.drift_text(plan)
    if got:
        _log(f"   {got}")

    if a.dry:
        _log("\n(보기만 했습니다 — 심으려면 --dry 를 빼고 다시 실행하세요)")
        return 0
    sp.save_plan(path, plan)
    _log(f"\n■ 저장: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
