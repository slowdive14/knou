"""형성평가 문항 모으기 — 이수할 때 못 담은 강의까지 퀴즈 페이지에 넣는다.

형성평가는 이수(형성평가 풀이)를 돌릴 때만 담겼다. 브라우저에서 직접 풀었거나
문항 담기가 생기기 전에 끝낸 강의는 퀴즈 페이지에 문항이 없었다(컴퓨터구조 0,
자료구조 16문항).

강의마다 학습 페이지를 **창 없이** 받아 그 안의 형성평가 문항·보기·지문을
읽는다. 서버에 답을 내지 않는다 — 읽기만 한다.

⚠️ 학교 정답·해설은 답을 제출해야 내려온다. 그래서 읽어 온 문항은 정답이
   비어 있다. --ai 를 주면 AI 가 풀어 답을 적고 'AI 풀이 답(공식 정답 아님)'
   으로 표시한다. 나중에 이수로 그 강의를 풀면 학교 정답으로 바뀐다.

실행:
    .venv/Scripts/python.exe harvest_quiz.py --course 컴퓨터구조
    .venv/Scripts/python.exe harvest_quiz.py --course 자료구조 --ai
    .venv/Scripts/python.exe harvest_quiz.py --ai-only --course 자료구조
        # 로그인 없이, 정답 없는 문항(형성평가·정답표 없는 기출)만 AI 로 풀기
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

from quizbank import correct_nos

SOURCE = "형성평가"
SOLVE_CHUNK = 12        # 한 번에 풀게 할 문항 수


def _log(m):
    print(m, flush=True)


def unanswered(questions) -> list:
    """정답을 모르는 객관식 문항들(보기가 있어야 풀 수 있다)."""
    return [q for q in questions or []
            if not correct_nos(q) and not str(q.get("answer_text") or "").strip()
            and (q.get("options") or [])]


def apply_ai_answers(questions, picked: dict) -> int:
    """{순번(1부터): 고른 번호} 를 문항에 적는다 → 적은 개수.

    보기에 없는 번호는 버린다. 'AI 풀이' 로 표시해 학교 정답과 가른다.
    """
    n = 0
    for i, q in enumerate(questions or [], start=1):
        got = picked.get(i)
        nos = {int(o.get("no") or 0) for o in q.get("options") or []}
        if got is None or int(got) not in nos:
            continue
        q["answer_no"] = int(got)
        q["answer_by"] = "AI"
        n += 1
    return n


def solve_with_ai(client, questions, course: str, on_event=None) -> int:
    """정답 없는 문항을 AI 에게 풀게 해 적는다 → 적은 개수.

    문항 번호는 순번으로 다시 매겨 묻는다 — 형성평가 qid(74151 …)는 은행마다
    겹칠 수 있어 그대로 쓰면 답이 엉뚱한 문항에 붙는다.
    """
    import exam_verify as ev

    todo = unanswered(questions)
    if not todo or client is None:
        return 0
    n = 0
    for s in range(0, len(todo), SOLVE_CHUNK):
        part = todo[s:s + SOLVE_CHUNK]
        tagged = [dict(q, qid=f"x-{i}") for i, q in enumerate(part, start=1)]
        picked = ev.solve(client, tagged, course, on_event=on_event,
                          chunk=SOLVE_CHUNK)
        n += apply_ai_answers(part, picked)
    return n


def gemini_client():
    """Gemini 클라이언트(없으면 None). ⚠️ 키는 여기서만 읽고 어디에도 적지 않는다."""
    try:
        from google import genai

        from config import load_config
        return genai.Client(api_key=load_config().gemini_api_key)
    except Exception:  # noqa: BLE001
        return None


def harvest(courses=None, on_event=None) -> int:
    """로그인해 강의마다 형성평가 문항을 읽어 담는다 → 담은 문항 수."""
    from playwright.sync_api import sync_playwright

    import knouon
    import quiz_capture as qc
    import quiz_intro as qi
    from auth import LoginFailed, ensure_logged_in
    from capture import fetch_study_html
    from config import load_config
    from discover import fetch_lectures, list_courses
    from quiz_page import default_quiz_paths, persist_questions
    from recon import launch_context

    log = on_event or _log
    cfg = load_config()
    quiz_dir = default_quiz_paths(cfg)[0]
    want = {str(c).strip() for c in courses or [] if str(c).strip()}
    total = 0
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            log("1) 로그인…")
            try:
                if not ensure_logged_in(page, cfg):
                    log("■ 로그인하지 못했습니다.")
                    return 0
            except LoginFailed as e:
                log(f"■ 로그인하지 못했습니다 — {e}")
                return 0
            for course in list_courses(page):
                if want and course.name not in want:
                    continue
                if knouon.is_knouon_course(course.name):
                    log(f"■ {course.name} — 다른 학습 사이트 과목이라 건너뜁니다")
                    continue
                log(f"■ {course.name}")
                for lec in fetch_lectures(page, course):
                    try:
                        html = fetch_study_html(page, lec)
                    except Exception as e:  # noqa: BLE001 - 한 강의 실패로 멈추지 않게
                        log(f"   {lec.seq}강: 페이지를 받지 못했습니다 — {str(e)[:60]}")
                        continue
                    qs = qc.scan_quiz_html(page, html, SOURCE)
                    if not qs:
                        log(f"   {lec.seq}강: 형성평가 없음")
                        continue
                    qi.download_intros(page, qs, quiz_dir, course.name,
                                       lec.seq, requester=page.request,
                                       html=html)
                    persist_questions(cfg, course.name, lec.seq, lec.name, qs)
                    total += len(qs)
                    log(f"   {lec.seq}강: {len(qs)}문항 담음")
        finally:
            ctx.close()
    return total


def fill_ai_answers(courses=None, on_event=None) -> int:
    """은행 파일에서 정답 없는 문항을 찾아 AI 로 푼다 → 적은 개수(로그인 없음)."""
    from config import load_config
    from quiz_page import default_quiz_paths

    log = on_event or _log
    quiz_dir = Path(default_quiz_paths(load_config())[0])
    want = {str(c).strip() for c in courses or [] if str(c).strip()}
    client = gemini_client()
    if client is None:
        log("■ Gemini 키가 없어 풀지 못합니다.")
        return 0
    total = 0
    for p in sorted(quiz_dir.glob("*.json")):
        try:
            bank = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not isinstance(bank, dict):
            continue
        course = str(bank.get("course") or "")
        if want and course not in want:
            continue
        todo = unanswered(bank.get("questions"))
        if not todo:
            continue
        n = solve_with_ai(client, bank.get("questions"), course,
                          on_event=log)
        if n:
            tmp = p.with_suffix(".tmp")
            tmp.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                           encoding="utf-8")
            tmp.replace(p)
        log(f"   {bank.get('name') or p.stem}: 정답 없는 {len(todo)}문항 중 "
            f"{n}문항을 AI 로 풀었습니다")
        total += n
    return total


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="형성평가 문항 모으기")
    ap.add_argument("--course", action="append",
                    help="이 과목만(여러 번 줄 수 있다. 기본: 모든 과목)")
    ap.add_argument("--ai", action="store_true",
                    help="모은 뒤 정답 없는 문항을 AI 로 풀어 적는다")
    ap.add_argument("--ai-only", action="store_true",
                    help="로그인하지 않고 정답 없는 문항만 AI 로 푼다")
    a = ap.parse_args(argv)
    if not a.ai_only:
        n = harvest(a.course)
        _log(f"\n■ 형성평가 {n}문항을 담았습니다(이미 있던 문항은 합쳤습니다).")
    if a.ai or a.ai_only:
        _log("\n■ 정답 없는 문항을 AI 로 풉니다…")
        n = fill_ai_answers(a.course)
        _log(f"■ {n}문항에 'AI 풀이 답(공식 정답 아님)' 을 적었습니다.")
    _log("퀴즈 화면에서 [새로고침] 하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
