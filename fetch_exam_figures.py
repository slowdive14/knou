"""기출 문항에 그림 붙이기 — '아래 그림은 …' 인데 그림이 없던 자리.

기출은 시험지 PDF 를 AI 가 읽어 만들었다. 글은 잘 옮겨졌지만 그림은 남지
않아서, 그림을 봐야 풀리는 문항을 아예 풀 수가 없었다.

시험지에서 그 문항의 그림만 잘라 형성평가 지문과 같은 자리(intro_image)에
붙인다. 앱도 HTML 도 이미 그 칸을 그리므로 붙이기만 하면 보인다.

⚠️ 글자까지 벡터로 인쇄된 PDF 는 건너뛴다. 한글 배포용 문서를 '인쇄' 로
   변환한 시험지가 그렇다 — 글줄이 없어 문항 경계를 찾을 수 없다.

실행:
    .venv/Scripts/python.exe fetch_exam_figures.py --dry
    .venv/Scripts/python.exe fetch_exam_figures.py
    .venv/Scripts/python.exe fetch_exam_figures.py --course 컴퓨터구조
    .venv/Scripts/python.exe fetch_exam_figures.py --force   # 이미 붙은 것도
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

import exam_figure as ef
import quiz_intro as qi


def _log(m):
    print(m, flush=True)


def gemini_client():
    """Gemini 클라이언트 — 글줄 없는 시험지를 읽을 때만 쓴다(없으면 None).

    ⚠️ API 키는 여기서만 읽고 어디에도 적지 않는다.
    """
    try:
        from google import genai

        from config import load_config
        return genai.Client(api_key=load_config().gemini_api_key)
    except Exception:  # noqa: BLE001 - 키가 없어도 글줄 있는 시험지는 된다
        return None


def exam_banks(quiz_dir: Path, course=None) -> list:
    """기출 은행들 — [(경로, 데이터)]."""
    out = []
    for p in sorted(Path(quiz_dir).glob("*.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if not d.get("exam"):
            continue
        if course and str(d.get("course") or "") != course:
            continue
        out.append((p, d))
    return out


def bank_key(bank) -> tuple:
    """은행의 (연도, 학기) — 시험지 PDF 와 맞추는 열쇠."""
    ex = (bank or {}).get("exam") or {}
    try:
        return (int(ex.get("year")), int(ex.get("term")))
    except (TypeError, ValueError):
        return (0, 0)


def convert_hwp(work: Path, course: str, on_event=None) -> int:
    """PDF 가 없는 한글 시험지를 변환한다 → 새로 만든 개수.

    자료실에서 받은 시험지는 한글 문서인 경우가 많다. 손으로 PDF 를 만들어
    넣어 두지 않아도 되게 여기서 한 번 돌린다(한글이 깔려 있어야 한다).

    ⚠️ 변환본은 **이름을 달리해서** 둔다. 게시글 번호가 같은데 학년도가 다른
       시험지가 실제로 있었다 — 같은 이름으로 쓰면 멀쩡한 PDF 를 덮는다.
    """
    import hwp_convert as hc

    log = on_event or (lambda _m: None)
    key = str(course or "").replace(" ", "")
    made = 0
    files = sorted(work.glob("*.hwp")) + sorted(work.glob("*.hwpx"))
    for h in files:
        if not key or key not in h.name:
            continue
        out = h.with_name(h.stem + "_한글.pdf")
        if out.exists():
            continue
        log(f"   {h.name} — 한글로 PDF 를 만듭니다(몇 분 걸립니다)")
        res = hc.hwp_to_pdf(h, out)
        if res.get("ok"):
            made += 1
            log(f"   만들었습니다: {out.name}")
        else:
            log(f"   만들지 못했습니다 — {res.get('why') or '까닭을 모릅니다'}")
    return made


def usable_pdfs(work: Path, course: str, client=None, on_event=None) -> dict:
    """{(연도, 학기): (PDF 경로, 읽는 길)} — 그 과목의 시험지들.

    읽는 길은 'text'(글줄로 좌표를 찾는다) 또는 'ai'(지면을 보여 주고
    묻는다)다. client 가 없으면 글줄이 있는 시험지만 돌려준다.

    회차는 회차표(exam_files)에 적힌 것을 먼저 본다 — 한 번 AI 로 읽은
    시험지를 실행할 때마다 다시 묻지 않는다.
    """
    import exam_files as xf

    log = on_event or (lambda _m: None)
    idx = xf.load_index(work)
    before = json.dumps(idx, sort_keys=True)
    out = {}
    for p in ef.find_pdfs(work, course):
        how = "text" if ef.has_text_layer(p) else "ai"
        if how == "ai" and client is None:
            continue
        key = xf.sheet_key(p, client, idx, work, log)
        if key:
            out.setdefault(key, (p, how))
        else:
            log(f"   {p.name} — 학년도·학기를 읽지 못했습니다")
    if json.dumps(idx, sort_keys=True) != before:
        xf.save_index(work, idx)
    return out


def figures_of(pdf: Path, how: str, client=None, on_event=None) -> dict:
    """그 시험지의 {문항번호: (쪽, 네모)} — 읽는 길에 맞는 방법으로."""
    if how == "ai":
        return ef.ai_pdf_figures(client, pdf, on_event)
    return ef.pdf_figures(pdf)


BODY_CHARS = 20     # 첫 줄 뒤로 이만큼 적혀 있으면 자료가 이미 글로 들어왔다


def written_out(text) -> bool:
    """이 글에 자료가 **이미 옮겨져** 있는가.

    지문의 첫 줄은 '※ (7~9) 아래 그림은 …' 같은 안내문이다. 그 뒤로 내용이
    이어지면 프로그램이나 표가 글로 옮겨진 것이라, 그림을 또 얹으면 같은
    것이 두 번 나온다.

        '※ (14~16) 아래 그림은 처리장치의 블록도이다.'        → 안내문뿐
        '※ (3~5) 다음 프로그램을 …\\nLOAD A ; AC ← M[A] …'   → 이미 옮겨졌다
    """
    lines = str(text or "").split("\n")
    return len("\n".join(lines[1:]).strip()) >= BODY_CHARS


def wants_figure(q, force: bool = False) -> bool:
    """이 문항에 그림을 붙여야 하는가.

    ⚠️ 시험지의 상자를 그림으로 또 얹으면 같은 내용이 두 번 나온다. 글이
       그림보다 읽기 좋으므로, **글로 이미 들어온 자료는 건드리지 않는다**
       (C프로그래밍 기출은 20문항이 모두 이런 경우였다).
    """
    q = q or {}
    if q.get(qi.INTRO_FIELD) and not force:
        return False                    # 이미 있는 그림을 덮지 않는다
    if str(q.get("code") or "").strip():
        return False
    return not (written_out(q.get("intro")) or written_out(q.get("question")))


def strip_figures(bank) -> int:
    """이 은행에 붙여 둔 그림을 모두 뗀다 → 뗀 개수.

    판정 기준을 고쳤을 때 잘못 붙은 것을 걷어내려고 쓴다. **기출 은행에만**
    쓴다 — 형성평가 그림은 LMS 에서 받아 온 것이라 다시 만들 수 없다.
    """
    n = 0
    for q in bank.get("questions") or []:
        if q.pop(qi.INTRO_FIELD, None):
            n += 1
    return n


def attach(bank, figures, pdf, quiz_dir: Path, force: bool) -> int:
    """문항에 그림을 붙인다 → 새로 붙인 개수(파일도 함께 남긴다)."""
    course, seq = bank.get("course"), bank.get("seq")
    n = 0
    for q in bank.get("questions") or []:
        if not wants_figure(q, force):
            continue
        no = ef.q_no(q.get("qid"))
        got = figures.get(no) if no else None
        if not got:
            continue
        data = ef.render(pdf, got[0], got[1])
        if not data:
            continue
        name = qi.image_name(course, seq, q.get("qid"))
        if qi.save_image(quiz_dir, name, data) is None:
            continue
        q[qi.INTRO_FIELD] = name
        n += 1
    return n


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 문항에 시험지 그림 붙이기")
    ap.add_argument("--course", help="이 과목만(기본: 모든 기출)")
    ap.add_argument("--dry", action="store_true", help="붙이지 않고 보기만")
    ap.add_argument("--force", action="store_true",
                    help="이미 그림이 있는 문항도 다시")
    ap.add_argument("--redo", action="store_true",
                    help="붙여 둔 그림을 모두 떼고 처음부터 다시 판정")
    ap.add_argument("--no-ai", action="store_true",
                    help="글줄 없는 시험지를 AI 에게 묻지 않는다")
    ap.add_argument("--no-hwp", action="store_true",
                    help="한글 시험지를 PDF 로 바꾸지 않는다")
    a = ap.parse_args(argv)
    if a.redo:
        a.force = True

    from config import load_config
    from quiz_page import default_quiz_paths
    cfg = load_config()
    quiz_dir = Path(default_quiz_paths(cfg)[0])
    work = Path(cfg.downloads_dir) / "_기출"

    banks = exam_banks(quiz_dir, a.course)
    if not banks:
        _log("■ 기출 은행이 없습니다.")
        return 1

    client = None if a.no_ai else gemini_client()
    courses = sorted({str(d.get("course") or "") for _p, d in banks})
    pdfs = {}
    for c in courses:
        _log(f"■ {c} — 시험지를 훑습니다")
        if not a.no_hwp:
            convert_hwp(work, c, _log)
        got = usable_pdfs(work, c, client, _log)
        pdfs[c] = got
        by_ai = sum(1 for _p, how in got.values() if how == "ai")
        skipped = len(ef.find_pdfs(work, c)) - len(got)
        _log(f"   쓸 수 있는 시험지 {len(got)}벌"
             + (f"(그중 {by_ai}벌은 지면을 보여 주고 읽습니다)" if by_ai else "")
             + (f" · 못 쓰는 것 {skipped}벌" if skipped else ""))

    total = 0
    for p, bank in banks:
        course = str(bank.get("course") or "")
        if a.redo and not a.dry:
            off = strip_figures(bank)
            if off:
                p.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                             encoding="utf-8")
                _log(f"   {bank.get('name')} — 붙여 둔 그림 {off}개를 뗐습니다")
        got = pdfs.get(course, {}).get(bank_key(bank))
        left = sum(1 for q in bank.get("questions") or []
                   if not q.get(qi.INTRO_FIELD))
        if got is None:
            _log(f"   {bank.get('name')} — 맞는 시험지가 없습니다"
                 f"(그림 없는 문항 {left}개)")
            continue
        pdf, how = got
        figures = figures_of(pdf, how, client, _log)
        if a.dry:
            hit = sum(1 for q in bank.get("questions") or []
                      if ef.q_no(q.get("qid")) in figures
                      and wants_figure(q, a.force))
            _log(f"   {bank.get('name')} — {pdf.name} 에서 그림 "
                 f"{len(figures)}개 · 붙일 문항 {hit}개")
            total += hit
            continue
        n = attach(bank, figures, pdf, quiz_dir, a.force)
        if n:
            p.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                         encoding="utf-8")
        _log(f"   {bank.get('name')} — {pdf.name} · 그림 {n}개 붙였습니다")
        total += n

    _log("")
    if a.dry:
        _log(f"■ 붙일 그림 {total}개 (보기만 했습니다 — 붙이려면 --dry 를 빼세요)")
    else:
        _log(f"■ 그림 {total}개를 붙였습니다. 퀴즈 화면에서 [새로고침] 하세요.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
