"""읽기 전용: PDF 가 없는 기출(HWP 첨부)을 읽을 수 있는지 살핀다.

자료실의 기출 20건 중 PDF 첨부는 9건뿐이다. 나머지는 HWP 라 지금은 건너뛴다.
HWP 에서 문항 글이 제대로 나오는지(코드가 그림으로만 들어 있지는 않은지) 보고
가져올 수 있을지 판단한다.

    .venv/Scripts/python.exe -u probe_exam_hwp.py --year 2014

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


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="HWP 기출 살피기(읽기 전용)")
    ap.add_argument("--year", type=int, default=2014)
    ap.add_argument("--lines", type=int, default=60)
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
        course, exams, _answers = bx.fetch_posts(page, bx.COURSE)
        for post in exams:
            title = bx._title(post)
            got = eb.parse_exam_title(title)
            if not got or got[0] != a.year:
                continue
            print(f"■ {title} — {got}", flush=True)
            from download import _split_files
            for dn, _sn in _split_files(post):
                print(f"   첨부: {dn}", flush=True)
            f = bx.download_attachment(ctx, course.sbjt_id, post,
                                       (".hwp", ".hwpx"), work)
            if f is None:
                print("   HWP 첨부가 없습니다", flush=True)
                continue
            print(f"   받음: {f.name} ({f.stat().st_size}바이트)", flush=True)
            try:
                lines = [str(x).strip() for x in eb.hwp_text(f)]
            except Exception as ex:  # noqa: BLE001
                print(f"   읽지 못함: {str(ex)[:120]}", flush=True)
                continue
            body = [x for x in lines if x]
            print(f"   글줄 {len(body)}개 — 앞부분:", flush=True)
            for x in body[:a.lines]:
                print(f"     {x[:100]}", flush=True)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
