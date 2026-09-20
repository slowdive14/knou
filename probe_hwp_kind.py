"""읽기 전용: 기출 HWP 가 **배포용 문서**인지 아닌지 가려 본다.

정답표 HWP 는 잘 읽힌다. 그런데 기출 HWP 하나를 열었더니 본문 대신 '최신 버전의
한글이 필요합니다' 한 줄만 나왔다 — 배포용 문서는 본문 스트림이 잠겨 있다.

파일 하나만 보고 단정할 수는 없다. 정답표가 있는 회차부터 여러 개를 받아
스트림 구성을 살핀다(DistributeDocData 가 있으면 배포용이다).

    .venv/Scripts/python.exe -u probe_hwp_kind.py --course 자료구조

⚠️ 자료를 받아 읽기만 한다. 서버에 아무것도 제출하지 않는다.
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

import build_exam_bank as bx
import exam_bank as eb

PLACEHOLDER = "상위 버전의 배포용 문서"


def look(path: Path) -> dict:
    """HWP 한 장의 속살 — 스트림 이름과 본문 첫 줄."""
    import olefile

    out = {"name": path.name, "size": path.stat().st_size, "streams": [],
           "distribute": False, "lines": 0, "head": ""}
    try:
        ole = olefile.OleFileIO(str(path))
    except Exception as e:  # noqa: BLE001
        out["head"] = f"열지 못함: {str(e)[:60]}"
        return out
    names = ["/".join(x) for x in ole.listdir()]
    out["streams"] = sorted(names)[:14]
    out["distribute"] = any("Distribute" in n for n in names)
    body = [str(x).strip() for x in eb.hwp_text(path) if str(x).strip()]
    out["lines"] = len(body)
    out["head"] = body[0][:70] if body else "(빈 본문)"
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="기출 HWP 살피기(읽기 전용)")
    ap.add_argument("--course", default="자료구조")
    ap.add_argument("--limit", type=int, default=4, help="이만큼만 받아 본다")
    a = ap.parse_args(argv)

    from playwright.sync_api import sync_playwright

    from auth import ensure_logged_in
    from config import load_config
    from recon import launch_context

    cfg = load_config()
    work = Path(cfg.downloads_dir) / "_기출"
    work.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        course, rows = bx.survey(page, ctx, work, lambda m: None, a.course)
        # PDF 가 없어 건너뛰던 회차 = HWP 만 있는 것들
        want = [r for r in rows if r["key"] and not r["pdf"]
                and eb.exam_kind(r["title"]) == eb.KIND_FINAL]
        want.sort(key=lambda r: r["key"], reverse=True)
        print(f"■ {a.course} — HWP 뿐인 기말 회차 {len(want)}개", flush=True)
        for r in want[:a.limit]:
            f = bx.download_attachment(ctx, course.sbjt_id, r["post"],
                                       (".hwp", ".hwpx"), work)
            if f is None:
                print(f"  {r['title'][:34]} — HWP 첨부도 없음", flush=True)
                continue
            got = look(f)
            mark = "배포용" if got["distribute"] else "일반"
            if PLACEHOLDER in got["head"]:
                mark = "배포용(본문 잠김)"
            print(f"  {r['key']} {mark} · {got['size']}바이트 · "
                  f"글줄 {got['lines']}개", flush=True)
            print(f"     첫 줄: {got['head']}", flush=True)
            print(f"     스트림: {got['streams']}", flush=True)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
