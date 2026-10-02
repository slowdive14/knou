"""기출 문항 확인·바로잡기 — 시험지와 다르게 옮겨진 문항을 찾아 고친다.

기출은 시험지를 AI 가 읽어 만들었다. 2015-2 컴퓨터구조는 1·2번에 2014-2 의
문제가 들어가 있었고 3번부터 한 칸씩 밀려 있었다. 정답표는 실제 시험지와
맞으므로, 엉뚱한 문항에 엉뚱한 정답이 붙어 맞게 풀어도 오답이 되었다.

하는 일:
  1. 시험지를 다시 읽는다(지면 밖 기억으로 채우지 말라는 규칙을 더해서)
  2. 은행과 번호로 맞대어 본다 — 같으면 그대로 둔다
  3. 다르면 **지면을 보여 주고** 어느 쪽이 맞는지 묻는다
  4. 정답을 모르는 채로 풀게 해 **정답표 번호와 말이 되는지** 대 본다

바로잡을 때(--fix):
  - 은행 파일과 풀이 기록을 먼저 백업한다(퀴즈/_백업/확인-날짜/)
  - 바뀐 문항의 해설·되묻기 대화·강 번호는 버린다(다른 문제를 두고 만든 것)
  - 바뀐 문항의 풀이 기록도 지운다(다른 문제를 푼 기록이다)
  - 정답 번호는 그대로 둔다 — 정답표에서 번호로 붙여 처음부터 맞았다

실행:
    .venv/Scripts/python.exe verify_exams.py                    # 확인만
    .venv/Scripts/python.exe verify_exams.py --fix              # 바로잡기
    .venv/Scripts/python.exe verify_exams.py --course 컴퓨터구조 --year 2015
    .venv/Scripts/python.exe verify_exams.py --no-solve         # 풀어 보기 생략
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 콘솔이 없어도 돈다
    pass

import exam_verify as ev
import fetch_exam_figures as fx
import quiz_progress as qp

BACKUP_DIR = "_백업"


def _log(m):
    print(m, flush=True)


def is_variant(bank) -> bool:
    """변형문제 은행인가 — 시험지를 옮긴 것이 아니라 만든 것이라 대 볼 데가 없다."""
    return str(((bank or {}).get("exam") or {}).get("kind") or "") == "변형문제"


def exam_banks(quiz_dir: Path, course=None, year=None) -> list:
    """시험지를 옮겨 만든 기출 은행들 — [(경로, 데이터)]."""
    out = []
    for p, d in fx.exam_banks(quiz_dir, course):
        if is_variant(d):
            continue
        if year and fx.bank_key(d)[0] != int(year):
            continue
        out.append((p, d))
    return out


def decide(pairs, new_pages, judged) -> dict:
    """번호마다 무엇을 할지 → {번호: (할 일, 까닭, 바꿔 넣을 문항|None)}.

    할 일: keep(같다) · fix(시험지 쪽으로) · flag(사람이 봐야 한다)
           · unread(다시 읽지 못했다) · extra(은행에 없는 문항)

    두 쪽 모두 지면과 다르면, 판정할 때 지면대로 고쳐 적어 받은 것을 쓴다.
    그것마저 없을 때만 사람에게 넘긴다.
    """
    out = {}
    for n, old, new in pairs:
        if old is None:
            out[n] = ("extra", "시험지에는 있는데 은행에 없습니다", None)
            continue
        if new is None:
            out[n] = ("unread", "다시 읽지 못했습니다", None)
            continue
        if ev.similar(old, new) >= ev.SAME:
            out[n] = ("keep", "", None)
            continue
        j = judged.get(n) or {}
        pick, why = j.get("pick"), j.get("why") or ""
        if pick == "new":
            out[n] = ("fix", why, new)
        elif pick in ("old", "both"):
            out[n] = ("keep", why, None)
        elif pick == "neither" and j.get("fixed"):
            out[n] = ("fix", why or "지면대로 고쳐 적었습니다", j["fixed"])
        elif pick == "neither":
            out[n] = ("flag", why or "두 쪽 모두 지면과 다릅니다", None)
        else:
            out[n] = ("flag", "판정을 받지 못했습니다", None)
    return out


def backup(paths, quiz_dir: Path) -> Path:
    """고치기 전에 은행·풀이 기록을 떠 둔다 → 백업 폴더."""
    dest = Path(quiz_dir) / BACKUP_DIR / datetime.now().strftime(
        "확인-%Y%m%d-%H%M%S")
    dest.mkdir(parents=True, exist_ok=True)
    for p in paths:
        p = Path(p)
        if p.exists():
            shutil.copy2(p, dest / p.name)
    return dest


def short(q) -> str:
    """보고용 한 줄 — 물음 앞부분과 상자."""
    q = q or {}
    s = " ".join(str(q.get("question") or "").split())[:34]
    code = " ".join(str(q.get("code") or "").split())[:20]
    return f"{s}" + (f" [{code}]" if code else "")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 문항을 시험지와 대 보고 바로잡기")
    ap.add_argument("--course", help="이 과목만")
    ap.add_argument("--year", type=int, help="이 학년도만")
    ap.add_argument("--fix", action="store_true",
                    help="시험지 쪽으로 바로잡는다(백업 후)")
    ap.add_argument("--no-solve", action="store_true",
                    help="정답표와 맞춰 보는 풀이를 생략한다")
    a = ap.parse_args(argv)

    from config import load_config
    from quiz_page import default_quiz_paths
    cfg = load_config()
    quiz_dir = Path(default_quiz_paths(cfg)[0])
    work = Path(cfg.downloads_dir) / "_기출"

    banks = exam_banks(quiz_dir, a.course, a.year)
    if not banks:
        _log("■ 확인할 기출 은행이 없습니다.")
        return 1
    client = fx.gemini_client()
    if client is None:
        _log("■ Gemini 키를 읽지 못했습니다 — 설정을 확인해 주세요.")
        return 1

    # 회차를 넘어 똑같은 문항인데 정답이 다른 것 — 모델 없이 먼저 본다.
    by_course: dict[str, list] = {}
    for _p, d in exam_banks(quiz_dir, a.course):
        by_course.setdefault(str(d.get("course")), []).append(d)
    for c, bs in sorted(by_course.items()):
        got = ev.conflicts(bs)
        if got:
            _log(f"■ {c} — 같은 문항인데 정답이 다른 것 {len(got)}묶음"
                 "(적어도 하나는 틀렸습니다)")

    pdfs: dict[str, dict] = {}
    for c in sorted({str(d.get("course")) for _p, d in banks}):
        pdfs[c] = fx.usable_pdfs(work, c, client, _log)

    prog_path = qp.progress_path(quiz_dir)
    prog = qp.load(prog_path)
    total = {"keep": 0, "fix": 0, "flag": 0, "unread": 0, "extra": 0}
    misfit_all = []
    touched = []
    dropped_records = 0
    backup_dir = None

    for p, bank in banks:
        course = str(bank.get("course") or "")
        year, term = fx.bank_key(bank)
        name = str(bank.get("name") or "")
        got = pdfs.get(course, {}).get((year, term))
        if got is None:
            _log(f"\n■ {course} {name} — 맞는 시험지가 없어 건너뜁니다")
            continue
        pdf = got[0]
        _log(f"\n■ {course} {name} — {pdf.name} 를 다시 읽습니다")
        new_pages = ev.reread(client, pdf, course, year, term, _log)
        new_by_no = {n: q for n, (_pg, q) in new_pages.items()}
        pairs = ev.align(bank.get("questions"), list(new_by_no.values()))

        # 다른 것만 쪽별로 모아 지면을 보여 주고 묻는다.
        judged = {}
        diff: dict[int, list] = {}
        for n, old, new in pairs:
            if old and new and ev.similar(old, new) < ev.SAME:
                diff.setdefault(new_pages[n][0], []).append((n, old, new))
        for page_no, items in sorted(diff.items()):
            judged.update(ev.judge(client, pdf, page_no, items, course, _log))

        plan = decide(pairs, new_pages, judged)
        counts = {k: sum(1 for v in plan.values() if v[0] == k)
                  for k in total}
        for k in total:
            total[k] += counts[k]
        _log(f"   같음 {counts['keep']} · 바로잡을 것 {counts['fix']}"
             f" · 사람이 볼 것 {counts['flag']}"
             + (f" · 다시 못 읽음 {counts['unread']}" if counts["unread"]
                else "")
             + (f" · 은행에 없음 {counts['extra']}" if counts["extra"]
                else ""))
        for n, old, new in pairs:
            act, why, put = plan.get(n, ("", "", None))
            if act == "fix":
                _log(f"   {n:>2}번 고침  {short(old)}")
                _log(f"          →  {short(put)}")
            elif act == "flag":
                _log(f"   {n:>2}번 확인 필요 — {why}")

        fixed_ids = []
        if a.fix and counts["fix"]:
            if backup_dir is None:
                backup_dir = backup([p for p, _b in banks] + [prog_path],
                                    quiz_dir)
                _log(f"   백업: {backup_dir}")
            qs = []
            for q in bank.get("questions") or []:
                n = ev.q_no(q)
                act, _why, put = plan.get(n, ("", "", None))
                if act == "fix" and put:
                    qs.append(ev.apply_fix(q, put))
                    fixed_ids.append(q.get("qid"))
                else:
                    qs.append(q)
            bank["questions"] = qs
            p.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                         encoding="utf-8")
            touched.append(name)
            # 바뀐 문항의 풀이 기록은 다른 문제를 푼 기록이다.
            for qid in fixed_ids:
                if prog.pop(qp.record_key(bank, qid), None) is not None:
                    dropped_records += 1

        if not a.no_solve:
            picked = ev.solve(client, bank.get("questions"), course, _log)
            misfit = [q for q in bank.get("questions") or []
                      if ev.fits(q, picked.get(ev.q_no(q))) is False]
            misfit_all += [(name, q) for q in misfit]
            _log(f"   정답표와 맞춰 풀어 보기 — 안 맞는 문항 {len(misfit)}개"
                 + (": " + ", ".join(str(ev.q_no(q)) for q in misfit)
                    if misfit else ""))
            # 바로잡은 것이 정말 맞는지 — 정답표 번호와 말이 되어야 한다.
            if fixed_ids:
                bad = {q.get("qid") for q in misfit}
                ok = sum(1 for i in fixed_ids if i not in bad)
                _log(f"   바로잡은 {len(fixed_ids)}문항 중 정답표와 맞는 것 {ok}개")

    if a.fix and dropped_records:
        qp.save(prog_path, prog)

    _log("\n■ 정리")
    _log(f"   같음 {total['keep']} · 바로잡을 것 {total['fix']}"
         f" · 사람이 볼 것 {total['flag']}"
         f" · 다시 못 읽음 {total['unread']} · 은행에 없음 {total['extra']}")
    if not a.no_solve:
        _log(f"   정답표와 안 맞는 문항 {len(misfit_all)}개"
             "(모델이 못 푼 것도 섞여 있습니다 — 참고용)")
    if a.fix:
        _log(f"   바로잡은 회차: {', '.join(touched) or '없음'}")
        if dropped_records:
            _log(f"   다른 문제를 푼 풀이 기록 {dropped_records}개를 지웠습니다")
        if backup_dir:
            _log(f"   되돌리려면: {backup_dir}")
    elif total["fix"]:
        _log("\n(확인만 했습니다 — 바로잡으려면 --fix 를 붙여 다시 실행하세요)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
