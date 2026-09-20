"""기출문제 은행 만들기 — 자료실에서 받아 문항으로 바꿔 퀴즈 폴더에 저장한다.

정답표가 있는 회차만 만든다(기본). 정답이 없는 기출은 한 칸 밀린 답으로 외우게
될 위험이 있어 따로 다룬다.

실행:
    .venv/Scripts/python.exe build_exam_bank.py --courses        # 어느 과목에 있나
    .venv/Scripts/python.exe build_exam_bank.py --list           # 뭐가 있는지만
    .venv/Scripts/python.exe build_exam_bank.py --year 2019      # 한 회차
    .venv/Scripts/python.exe build_exam_bank.py                  # 정답 있는 전부
    .venv/Scripts/python.exe build_exam_bank.py --course 자료구조 --list

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
import hwp_convert as hc

DEFAULT_COURSE = "C프로그래밍"     # --course 를 안 주면 이 과목
COURSE = DEFAULT_COURSE            # 예전 이름(다른 모듈이 쓴다)
CAT_EXAM = "기출문제"
CAT_ANSWER = "기출문제정답"

# ⚠️ 글 목록은 요청한 개수만큼만 온다. 기본값 100 이면 자료가 많은 과목에서
#    딱 100건에 잘려 오래된 기출이 통째로 안 보인다(실측: 컴퓨터구조·자료구조).
POST_COUNT = 400


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
                             _cnts_id_of(course.sbjt_id), count=POST_COUNT)
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


def bank_exists(quiz_dir, year, term, course: str = COURSE) -> bool:
    """이 회차를 이미 만들어 두었는가."""
    return (Path(quiz_dir) / eb.bank_filename(course, year, term)).exists()


def plan_imports(rows, quiz_dir, want_all: bool = False, year=None,
                 course: str = COURSE) -> tuple[list, list]:
    """가져올 회차와 건너뛸 회차를 가른다 → (가져올 것, [(행, 사유)]).

    - 이미 만든 회차는 건너뛴다(버튼을 다시 눌러도 다시 만들지 않는다)
    - PDF 첨부가 없으면 못 읽는다. HWP 는 **배포용 문서**라 본문이 안 열린다
      (실측: 본문 대신 '최신 버전의 한글이 필요합니다' 한 줄만 나온다)
    - 정답표가 없는 회차는 want_all 일 때만 — 정답 없이 외우면 헛공부다
    """
    todo, skip = [], []
    for r in rows or []:
        key = r.get("key")
        if not key:
            skip.append((r, "연도·학기를 못 읽었습니다"))
            continue
        kind = eb.exam_kind(r.get("title"))
        if kind == eb.KIND_NOTE:
            skip.append((r, "시험지가 아니라 문제해설 자료입니다"))
            continue
        if kind == eb.KIND_MAKEUP:
            # 기말과 (연도, 학기) 가 같아 파일·문항번호가 겹치고, 정답표는
            # 기말 것뿐이라 붙이면 통째로 어긋난다.
            skip.append((r, "출석수업대체시험은 아직 담지 않습니다"
                            "(기말과 회차가 겹치고 정답표가 없습니다)"))
            continue
        if year and key[0] != int(year):
            continue
        if bank_exists(quiz_dir, key[0], key[1], course):
            skip.append((r, "이미 가져왔습니다"))
            continue
        if not (r.get("pdf") or r.get("manual") or r.get("hwp")):
            skip.append((r, "PDF 도 HWP 도 없습니다"))
            continue
        if not r.get("ans") and not want_all:
            skip.append((r, "정답표가 없습니다"))
            continue
        todo.append(r)
    todo.sort(key=lambda x: x["key"], reverse=True)
    return todo, skip


def summary_text(done) -> str:
    """가져오기 결과 한 줄."""
    ok = [d for d in done or [] if d.get("ok")]
    if not done:
        return "새로 가져올 회차가 없습니다"
    return (f"{len(ok)}/{len(done)}회차 · 문항 "
            f"{sum(d.get('n', 0) for d in ok)}개"
            f"(정답 있는 것 {sum(d.get('scored', 0) for d in ok)}개)")


def build_one(client, ctx, course, post, ans_path, quiz_dir: Path,
              work: Path, name: str = DEFAULT_COURSE, on_event=None) -> dict:
    """기출 한 회차 → 은행 JSON 저장. 반환: 요약 dict.

    ⚠️ 진행 상황은 **넘겨받은 통로**로 보낸다. 콘솔에만 찍으면 앱에서는 가장
       오래 걸리는 구간이 통째로 잠잠해 멈춘 것처럼 보인다.
    """
    log = on_event or _log
    title = _title(post)
    got = eb.parse_exam_title(title)
    if not got:
        return {"title": title, "ok": False, "why": "연도·학기를 못 읽음"}
    year, term = got

    log(f"── {title}")
    pdf = hc.manual_pdf(work, name, year, term)
    if pdf is not None:
        log(f"   직접 넣어 두신 PDF 를 씁니다: {pdf.name}")
    else:
        log("   PDF 받는 중…")
        pdf = download_attachment(ctx, course.sbjt_id, post, (".pdf",), work)
    if pdf is None:
        # PDF 첨부가 없으면 HWP 를 한글에 시켜 바꿔 본다(배포용이면 거부당한다)
        hwp = download_attachment(ctx, course.sbjt_id, post,
                                  (".hwp", ".hwpx"), work)
        if hwp is None:
            return {"title": title, "ok": False, "why": "PDF 도 HWP 도 없음"}
        log(f"   HWP 를 PDF 로 바꾸는 중: {hwp.name}")
        res = hc.hwp_to_pdf(hwp, work / (hwp.stem + ".pdf"))
        log(f"   {hc.convert_note(res)}")
        if not res.get("ok"):
            return {"title": title, "ok": False, "why": hc.convert_note(res)}
        pdf = Path(res["path"])

    log(f"   받음: {pdf.name} — 문항을 읽습니다(몇 분 걸립니다)")
    questions = eb.extract_questions(client, pdf, name, year, term,
                                     on_event=log)
    if not questions:
        return {"title": title, "ok": False, "why": "문항을 읽지 못함"}

    answers = eb.answers_from_hwp(ans_path, name) if ans_path else []
    questions, warn = eb.attach_answers(questions, answers)
    for w in warn:
        log(f"  ⚠️ {w}")

    bank = eb.make_bank(name, year, term, questions)
    out = quiz_dir / eb.bank_filename(name, year, term)
    out.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    scored = sum(1 for q in questions if q.get("answer_no"))
    log(f"  저장: {out.name} — 문항 {len(questions)}개 (정답 있는 것 {scored}개)")
    return {"title": title, "ok": True, "n": len(questions), "scored": scored,
            "path": str(out)}


def survey(page, ctx, work: Path, on_event=None,
           name: str = DEFAULT_COURSE) -> tuple:
    """자료실을 훑어 (과목, 회차 행 목록) 을 만든다. 아무것도 만들지 않는다."""
    log = on_event or _log
    course, exams, answers = fetch_posts(page, name)
    log(f"   기출 {len(exams)}건 · 정답표 {len(answers)}건")

    # 정답표 ZIP 을 먼저 풀어 (연도, 학기) → 파일 로 만들어 둔다
    table: dict = {}
    for ap_post in answers:
        z = download_attachment(ctx, course.sbjt_id, ap_post, (".zip",), work)
        if z:
            table.update(answer_files(z, work / "정답표"))
    log(f"   정답표에 든 회차: {sorted(f'{y}-{t}' for y, t in table)}")

    rows = []
    for post in exams:
        got = eb.parse_exam_title(_title(post))
        dn, _sn = _pick_file(post, (".pdf",))
        hn, _hs = _pick_file(post, (".hwp", ".hwpx"))
        # 사람이 한글에서 인쇄해 넣어 둔 PDF 가 있으면 그것도 '있는 것' 이다
        manual = hc.manual_pdf(work, name, *got) if got else None
        rows.append({"post": post, "key": got, "pdf": dn, "hwp": hn,
                     "manual": manual,
                     "ans": table.get(got) if got else None,
                     "title": _title(post)})
    return course, rows


def import_exams(on_event=None, want_all: bool = False, year=None,
                 quiz_dir=None, course: str = DEFAULT_COURSE) -> dict:
    """로그인 → 자료실 → **아직 없는 회차만** 만든다. 화면에서도 부른다.

    반환: {"done": [회차별 결과], "skip": [(제목, 사유)], "made": 만든 회차 수}
    ⚠️ 자료를 읽기만 한다. 서버에 아무것도 제출하지 않는다.
    """
    from google import genai
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from recon import launch_context

    log = on_event or _log
    cfg = load_config()
    qd = Path(quiz_dir) if quiz_dir else Path(cfg.summary_dir) / "퀴즈"
    qd.mkdir(parents=True, exist_ok=True)
    work = Path(cfg.downloads_dir) / "_기출"
    work.mkdir(parents=True, exist_ok=True)

    done, skip = [], []
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log(f"1) 로그인·자료실({course})…")
        ensure_logged_in(page, cfg)
        obj, rows = survey(page, ctx, work, log, course)
        todo, skipped = plan_imports(rows, qd, want_all, year, course)
        skip = [(r.get("title") or "?", why) for r, why in skipped]
        log(f"\n2) 새로 가져올 회차 {len(todo)}개")
        if todo:
            client = genai.Client(api_key=cfg.gemini_api_key)
            for r in todo:
                try:
                    done.append(build_one(client, ctx, obj, r["post"],
                                          r["ans"], qd, work, course, log))
                except Exception as e:  # noqa: BLE001 - 회차 단위 격리
                    log(f"  ✗ 실패: {str(e)[:140]}")
                    done.append({"title": r.get("title") or "?", "ok": False,
                                 "why": str(e)[:100]})
        ctx.close()

    log(f"\n■ 완료: {summary_text(done)}")
    # 배포용 문서 때문에 막힌 회차가 있으면 어디에 넣어 주면 되는지 알린다
    if any("배포용" in str(d.get("why") or "") for d in done):
        log(f"   한글에서 열어 'PDF로 저장' 한 뒤 여기에 넣어 주세요: "
            f"{hc.manual_dir(work)}")
        log(f"   이름은 이렇게: {hc.manual_name(course, 2016, 2)}")
    return {"done": done, "skip": skip,
            "made": sum(1 for d in done if d.get("ok"))}


def survey_courses(page, on_event=None, cfg=None) -> list:
    """수강 중인 과목마다 자료실에 기출이 몇 건 있는지 센다.

    과목마다 자료실 사정이 다르다 — 기출이 아예 없는 과목도 있고, 정답표만
    올라온 과목도 있다. 가져오기를 돌리기 전에 먼저 이걸 본다.
    """
    from auth import ensure_logged_in
    from discover import list_courses
    from download import _cnts_id_of, fetch_data_posts

    log = on_event or _log
    out = []
    # ⚠️ 과목 목록을 **먼저 확정**한다. 아래에서 페이지를 옮겨 다니므로 늦게
    #    읽으면 'Execution context was destroyed' 로 터진다.
    for c in list(list_courses(page)):
        try:
            # ⚠️ 자료실을 한 번 읽고 나면 **로그인 페이지로 튕긴다**. 그대로
            #    다음 과목을 읽으면 0건으로 온다 — 과목마다 로그인 상태를
            #    다시 확인한다(이미 살아 있으면 바로 지나간다).
            if cfg is not None:
                ensure_logged_in(page, cfg)
            posts = fetch_data_posts(page, c.atlc_no, c.sbjt_id,
                                     _cnts_id_of(c.sbjt_id), count=POST_COUNT)
        except Exception as e:  # noqa: BLE001 - 과목 하나가 막혀도 계속
            log(f"   ! {c.name}: {str(e)[:60]}")
            posts = []
        cats = [(p.get("sbjtBdotClcd") or "").strip() for p in posts]
        pdfs = sum(1 for p in posts
                   if (p.get("sbjtBdotClcd") or "").strip() == CAT_EXAM
                   and _pick_file(p, (".pdf",))[0])
        out.append({"name": c.name,
                    "exams": cats.count(CAT_EXAM),
                    "pdfs": pdfs,
                    "answers": cats.count(CAT_ANSWER)})
        log(f"   {c.name} — 기출 {out[-1]['exams']}건"
            f"(PDF {pdfs}건) · 정답표 {out[-1]['answers']}건")
    return out


def list_courses_with_exams(on_event=None) -> list:
    """로그인해서 과목별 기출 현황을 훑는다(아무것도 만들지 않는다)."""
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from recon import launch_context

    log = on_event or _log
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log("1) 로그인·수강 과목…")
        ensure_logged_in(page, cfg)
        rows = survey_courses(page, log, cfg)
        ctx.close()
    return rows


def list_exams(on_event=None, course: str = DEFAULT_COURSE) -> list:
    """자료실의 회차 목록만 읽어 온다(아무것도 만들지 않는다)."""
    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from recon import launch_context

    log = on_event or _log
    cfg = load_config()
    work = Path(cfg.downloads_dir) / "_기출"
    work.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        log("1) 로그인·자료실…")
        ensure_logged_in(page, cfg)
        _obj, rows = survey(page, ctx, work, log, course)
        ctx.close()
    return rows


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출문제 은행 만들기")
    ap.add_argument("--course", default=DEFAULT_COURSE, help="과목 이름")
    ap.add_argument("--year", type=int, help="이 연도만")
    ap.add_argument("--list", action="store_true", help="목록만 보여준다")
    ap.add_argument("--courses", action="store_true",
                    help="어느 과목에 기출이 있는지 훑어본다")
    ap.add_argument("--all", action="store_true",
                    help="정답표가 없는 회차도 만든다(정답 없이 저장)")
    a = ap.parse_args(argv)

    if a.courses:
        rows = list_courses_with_exams()
        _log("\n기출 | PDF | 정답표 | 과목")
        for r in sorted(rows, key=lambda x: -x["pdfs"]):
            _log(f"{r['exams']:>4d} | {r['pdfs']:>3d} | {r['answers']:>6d} "
                 f"| {r['name']}")
        _log("\n가져오려면: build_exam_bank.py --course \"과목이름\" --list")
        return 0

    if a.list:
        from config import load_config
        quiz_dir = Path(load_config().summary_dir) / "퀴즈"
        rows = list_exams(course=a.course)
        _log("\n연도-학기 | PDF | 정답표 | 가져옴 | 제목")
        for r in sorted(rows, key=lambda x: x["key"] or (0, 0), reverse=True):
            k = f"{r['key'][0]}-{r['key'][1]}" if r["key"] else "?"
            have = (r["key"] and bank_exists(quiz_dir, *r["key"], a.course))
            _log(f"  {k:>8s} | {'O' if r['pdf'] else '-'}   | "
                 f"{'O' if r['ans'] else '-'}      | {'O' if have else '-'}     "
                 f"| {r['title'][:40]}")
        return 0

    res = import_exams(want_all=a.all, year=a.year, course=a.course)
    for title, why in res["skip"]:
        _log(f"   건너뜀: {title[:40]} — {why}")
    return 0 if res["made"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
