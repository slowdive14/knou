"""빠진 형성평가 '지문' 채우기 — 문제를 풀 수 있게.

'위 문장의 출력 결과는 무엇인가?' 인데 그 위 문장이 없는 문항들이 있다. 예전
스캐너가 form 안의 문제글과 보기만 읽어서다. 그 차시들을 **다시 열어 읽기만
하고** 지문을 채운다.

  - 지문이 글이면 그대로, 그림이면 내려받아 퀴즈 폴더의 '지문' 아래 둔다
  - 이미 지문이 있는 문항은 건드리지 않는다

실행:
    .venv/Scripts/python.exe -u fetch_intros.py --dry-run   # 어디가 비었는지만
    .venv/Scripts/python.exe -u fetch_intros.py
    .venv/Scripts/python.exe -u fetch_intros.py --course C프로그래밍 --seq 5

⚠️ 아무것도 제출하지 않는다(보기 선택·확인 클릭 없음). 다만 강의 플레이어를
   열기 때문에 영상이 잠깐 재생될 수 있다 — 이미 이수한 차시에 쓰는 도구다.
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

import quiz_intro as qi


def _log(m):
    print(m, flush=True)


def every_lecture(banks, want_all: bool = False) -> list:
    """지문 없는 문항이 하나라도 있는 **모든** 강의 차시.

    '위 문장' 처럼 대놓고 가리키지 않아도 지문이 딸린 문항이 있을 수 있다.
    미심쩍으면 이 목록으로 한 번 훑는다(차시마다 플레이어를 열어 느리다).
    """
    out = []
    for b in banks or []:
        if b.get("exam") or b.get("lecture_pick"):
            continue
        qids = [str(q.get("qid")) for q in (b.get("questions") or [])
                if want_all or not qi.has_intro(q)]
        if qids:
            out.append((str(b.get("course") or ""), int(b.get("seq") or 0),
                        str(b.get("name") or ""), qids))
    return out


def refilled_lectures(banks) -> list:
    """지문을 이미 담았거나 담아야 할 차시 — 읽는 방법을 고친 뒤 다시 읽는다."""
    out = []
    for b in banks or []:
        if b.get("exam") or b.get("lecture_pick"):
            continue
        qids = [str(q.get("qid")) for q in (b.get("questions") or [])
                if qi.has_intro(q) or qi.needs_intro(q)]
        if qids:
            out.append((str(b.get("course") or ""), int(b.get("seq") or 0),
                        str(b.get("name") or ""), qids))
    return out


def targets(banks, course=None, seq=None, every=False, refill=False) -> list:
    """채워야 할 차시만 — 과목·차시를 주면 그것만."""
    if every:
        rows = every_lecture(banks, want_all=True)
    elif refill:
        rows = refilled_lectures(banks)
    else:
        rows = qi.missing_lectures(banks)
    if course:
        rows = [r for r in rows if r[0] == course]
    if seq:
        rows = [r for r in rows if r[1] == int(seq)]
    return rows


def fill_one(page, popup_opener, lec, course, quiz_dir, bank,
             force: bool = False) -> int:
    """차시 하나를 열어 지문을 채운다 → 채운 문항 수."""
    from exercise import _exam_frame, wait_for_exam_frame

    popup = popup_opener(page, lec)
    try:
        try:
            popup.on("dialog", lambda d: d.accept())
        except Exception:  # noqa: BLE001 - 대화상자가 없을 수도 있다
            pass
        if wait_for_exam_frame(popup) is None:
            return 0
        fr = _exam_frame(popup)
        if fr is None:
            return 0
        found = qi.scan_intros(fr)
        if not found:
            return 0
        mapping = {}
        for q in bank.get("questions") or []:
            qid = str(q.get("qid"))
            got = found.get(qid)
            if not got or (qi.has_intro(q) and not force):
                continue
            name = ""
            if got.get("src"):
                data = qi.fetch_image(popup.request, got["src"])
                if data:
                    name = qi.image_name(course, lec.seq, qid)
                    qi.save_image(quiz_dir, name, data)
            if got.get("text") or name:
                mapping[qid] = {"text": got.get("text"), "image": name}
        return qi.store_intros(quiz_dir, bank, mapping, force)
    finally:
        try:
            popup.close()
        except Exception:  # noqa: BLE001
            pass


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="빠진 형성평가 지문 채우기")
    ap.add_argument("--course", help="이 과목만")
    ap.add_argument("--seq", type=int, help="이 차시만")
    ap.add_argument("--refill", action="store_true",
                    help="이미 담긴 지문도 다시 읽어 고쳐 담는다")
    ap.add_argument("--all", action="store_true",
                    help="대놓고 가리키지 않는 문항까지, 모든 차시를 훑는다(느림)")
    ap.add_argument("--dry-run", action="store_true",
                    help="어디가 비었는지만 세어 본다(로그인하지 않는다)")
    a = ap.parse_args(argv)

    from config import load_config
    from quiz_page import collect_banks

    cfg = load_config()
    quiz_dir = Path(cfg.summary_dir) / "퀴즈"
    banks = collect_banks(quiz_dir)
    rows = targets(banks, a.course, a.seq, every=a.all, refill=a.refill)
    if not rows:
        _log("지문이 빠진 문항이 없습니다.")
        return 0
    total = sum(len(qids) for _c, _s, _n, qids in rows)
    what = "다시 읽을" if a.refill else "지문이 빠진"
    _log(f"■ {what} 문항 {total}개 · {len(rows)}차시")
    for c, s, n, qids in rows:
        _log(f"   {c} {s}강 {n} — {len(qids)}문항")
    if a.dry_run:
        return 0

    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from discover import fetch_lectures, list_courses
    from recon import launch_context
    from watch import open_player

    filled = 0
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        courses = {c.name: c for c in list_courses(page)}
        lectures = {}
        for cname, seq, name, qids in rows:
            course = courses.get(cname)
            if course is None:
                _log(f"   ! 수강 목록에 없음: {cname}")
                continue
            if cname not in lectures:
                lectures[cname] = {l.seq: l for l in fetch_lectures(page, course)}
            lec = lectures[cname].get(seq)
            if lec is None:
                _log(f"   ! 차시를 못 찾음: {cname} {seq}강")
                continue
            bank = next((b for b in banks if b.get("course") == cname
                         and int(b.get("seq") or 0) == seq), None)
            if bank is None:
                continue
            _log(f"── {cname} {seq}강 {name} — {len(qids)}문항")
            n = fill_one(page, open_player, lec, cname, quiz_dir, bank,
                         force=a.refill)
            filled += n
            _log(f"   채움: {n}문항")

    _log(f"\n■ 완료: 지문 {filled}문항")
    if filled:
        _log(f"   그림은 여기 있습니다: {qi.intro_dir(quiz_dir)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
