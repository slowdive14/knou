"""기출문제 은행 만들기 — 자료실에서 받아 문항으로 바꿔 퀴즈 폴더에 저장한다.

정답표가 있는 회차만 만든다(기본). 정답이 없는 기출은 한 칸 밀린 답으로 외우게
될 위험이 있어 따로 다룬다.

실행:
    .venv/Scripts/python.exe build_exam_bank.py --list          # 뭐가 있는지만
    .venv/Scripts/python.exe build_exam_bank.py --year 2019     # 한 회차
    .venv/Scripts/python.exe build_exam_bank.py                 # 정답 있는 전부

⚠️ 자료를 **읽기만** 한다. 서버에 아무것도 제출하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

import exam_bank as eb

COURSE = "C프로그래밍"
CAT_EXAM = "기출문제"
CAT_ANSWER = "기출문제정답"


def _log(m):
    print(m, flush=True)


def fetch_posts(page, course_name: str):
    """자료실 글 목록에서 기출·정답표만 추린다."""
    from discover import list_courses
    from download import _cnts_id_of, fetch_data_posts

    course = next((c for c in list_courses(page) if course_name in c.name), None)
    if course is None:
        raise LookupError(f"'{course_name}' 과목을 찾지 못했습니다")
    posts = fetch_data_posts(page, course.atlc_no, course.sbjt_id,
                             _cnts_id_of(course.sbjt_id))
    exams, answers = [], []
    for p in posts:
        cat = (p.get("sbjtBdotClcd") or "").strip()
        if cat == CAT_EXAM:
            exams.append(p)
        elif cat == CAT_ANSWER:
            answers.append(p)
    return course, exams, answers


def _title(post) -> str:
    return (post.get("sbjtNotcTitNm") or "").strip()


def _pick_file(post, exts):
    """글의 첨부 중 원하는 확장자 첫 개 — (표시명, 저장명)."""
    from download import _split_files
    for dn, sn in _split_files(post):
        if dn.lower().endswith(tuple(exts)):
            return dn, sn
    return None, None


def download_attachment(ctx, sbjt_id, post, exts, dest_dir: Path):
    """첨부를 내려받아 경로 반환(원하는 확장자가 없으면 None)."""
    from download import build_file_url, download_url
    dn, sn = _pick_file(post, exts)
    if not dn:
        return None
    dest = dest_dir / dn
    if dest.exists() and dest.stat().st_size > 0:
        return dest                       # 이미 받아 둔 것은 다시 받지 않는다
    res = download_url(ctx, build_file_url(sbjt_id, sn, dn), dest)
    return dest if res.get("ok") else None


def answer_files(zip_path: Path, dest_dir: Path) -> dict:
    """정답표 ZIP 을 풀어 {(연도, 학기): 파일} 로. 학기는 파일명에서 읽는다."""
    out: dict[tuple[int, int], Path] = {}
    try:
        with zipfile.ZipFile(zip_path) as z:
            z.extractall(dest_dir)
    except Exception as e:  # noqa: BLE001
        _log(f"정답표 압축 풀기 실패: {str(e)[:120]}")
        return out
    for f in sorted(dest_dir.rglob("*")):
        if f.suffix.lower() not in (".hwp", ".hwpx", ".pdf"):
            continue
        got = eb.parse_exam_title(f.name) or eb.parse_exam_title(f.parent.name)
        if got:
            out.setdefault(got, f)
    return out


def build_one(client, ctx, course, post, ans_path, quiz_dir: Path,
              work: Path) -> dict:
    """기출 한 회차 → 은행 JSON 저장. 반환: 요약 dict."""
    title = _title(post)
    got = eb.parse_exam_title(title)
    if not got:
        return {"title": title, "ok": False, "why": "연도·학기를 못 읽음"}
    year, term = got

    pdf = download_attachment(ctx, course.sbjt_id, post, (".pdf",), work)
    if pdf is None:
        return {"title": title, "ok": False, "why": "PDF 첨부가 없음(HWP 뿐)"}

    _log(f"── {title}  ({pdf.name})")
    questions = eb.extract_questions(client, pdf, COURSE, year, term,
                                     on_event=_log)
    if not questions:
        return {"title": title, "ok": False, "why": "문항을 읽지 못함"}

    answers = eb.answers_from_hwp(ans_path, COURSE) if ans_path else []
    questions, warn = eb.attach_answers(questions, answers)
    for w in warn:
        _log(f"  ⚠️ {w}")

    bank = eb.make_bank(COURSE, year, term, questions)
    out = quiz_dir / eb.bank_filename(COURSE, year, term)
    out.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    scored = sum(1 for q in questions if q.get("answer_no"))
    _log(f"  저장: {out.name} — 문항 {len(questions)}개 (정답 있는 것 {scored}개)")
    return {"title": title, "ok": True, "n": len(questions), "scored": scored,
            "path": str(out)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출문제 은행 만들기")
    ap.add_argument("--year", type=int, help="이 연도만")
    ap.add_argument("--list", action="store_true", help="목록만 보여준다")
    ap.add_argument("--all", action="store_true",
                    help="정답표가 없는 회차도 만든다(정답 없이 저장)")
    a = ap.parse_args(argv)

    from google import genai
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config

    cfg = load_config()
    quiz_dir = Path(cfg.summary_dir) / "퀴즈"
    quiz_dir.mkdir(parents=True, exist_ok=True)
    work = Path(cfg.downloads_dir) / "_기출"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        from recon import launch_context
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _log("1) 로그인·자료실…")
        ensure_logged_in(page, cfg)
        course, exams, answers = fetch_posts(page, COURSE)
        _log(f"   기출 {len(exams)}건 · 정답표 {len(answers)}건")

        # 정답표 ZIP 을 먼저 풀어 (연도, 학기) → 파일 로 만들어 둔다
        table: dict = {}
        for ap_post in answers:
            z = download_attachment(ctx, course.sbjt_id, ap_post, (".zip",), work)
            if z:
                table.update(answer_files(z, work / "정답표"))
        _log(f"   정답표에 든 회차: "
             f"{sorted(f'{y}-{t}' for y, t in table)}")

        rows = []
        for post in exams:
            got = eb.parse_exam_title(_title(post))
            dn, _sn = _pick_file(post, (".pdf",))
            rows.append({"post": post, "key": got, "pdf": dn,
                         "ans": table.get(got) if got else None})

        if a.list:
            _log("\n연도-학기 | PDF | 정답표 | 제목")
            for r in sorted(rows, key=lambda x: x["key"] or (0, 0), reverse=True):
                k = f"{r['key'][0]}-{r['key'][1]}" if r["key"] else "?"
                _log(f"  {k:>8s} | {'O' if r['pdf'] else '-'}   | "
                     f"{'O' if r['ans'] else '-'}      | {_title(r['post'])[:44]}")
            ctx.close()
            return 0

        todo = [r for r in rows if r["pdf"] and (r["ans"] or a.all)]
        if a.year:
            todo = [r for r in todo if r["key"] and r["key"][0] == a.year]
        _log(f"\n2) 만들 회차 {len(todo)}개")
        if not todo:
            _log("   조건에 맞는 회차가 없습니다(--list 로 확인하세요).")
            ctx.close()
            return 1

        client = genai.Client(api_key=cfg.gemini_api_key)
        done = []
        for r in todo:
            try:
                done.append(build_one(client, ctx, course, r["post"], r["ans"],
                                      quiz_dir, work))
            except Exception as e:  # noqa: BLE001 - 회차 단위 격리
                _log(f"  ✗ 실패: {str(e)[:140]}")
                done.append({"title": _title(r["post"]), "ok": False,
                             "why": str(e)[:100]})
        ctx.close()

    ok = [d for d in done if d.get("ok")]
    _log(f"\n■ 완료: {len(ok)}/{len(done)}회차 · "
         f"문항 {sum(d.get('n', 0) for d in ok)}개 "
         f"(정답 있는 것 {sum(d.get('scored', 0) for d in ok)}개)")
    for d in done:
        if not d.get("ok"):
            _log(f"   건너뜀: {d['title'][:40]} — {d.get('why')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
