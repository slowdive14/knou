"""기출 PDF 한 건과 정답표를 받아 텍스트가 어떻게 뽑히는지 본다(읽기 전용)."""
from __future__ import annotations
import json, re, sys, zipfile
from pathlib import Path
try: sys.stdout.reconfigure(encoding="utf-8")
except Exception: pass
from playwright.sync_api import sync_playwright
from auth import ensure_logged_in
from config import load_config
from discover import list_courses
from download import _cnts_id_of, _split_files, build_file_url, download_url, fetch_data_posts
from recon import launch_context

OUT = Path("recon_shots/exam_files"); OUT.mkdir(parents=True, exist_ok=True)
WANT_TITLES = ("[2019-1학기]", "정답표")

with sync_playwright() as p:
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    cfg = load_config()
    ensure_logged_in(page, cfg)
    course = next(c for c in list_courses(page) if "C프로그래밍" in c.name)
    posts = fetch_data_posts(page, course.atlc_no, course.sbjt_id,
                             _cnts_id_of(course.sbjt_id))
    got = []
    for po in posts:
        t = (po.get("sbjtNotcTitNm") or "")
        if not any(w in t for w in WANT_TITLES): continue
        for dn, sn in _split_files(po):
            if not (dn.lower().endswith(".pdf") or dn.lower().endswith(".zip")): continue
            url = build_file_url(course.sbjt_id, sn, dn)
            dest = OUT / dn
            r = download_url(ctx, url, dest)
            print(f"{'OK ' if r.get('ok') else '실패'} {dn} ({dest.stat().st_size if dest.exists() else 0}바이트)", flush=True)
            if r.get("ok"): got.append(dest)
    ctx.close()

print()
for f in got:
    if f.suffix.lower() == ".zip":
        with zipfile.ZipFile(f) as z:
            names = z.namelist()
            print(f"[{f.name}] 안에 {len(names)}개:", flush=True)
            for n in names[:20]: print("   ", n, flush=True)
            z.extractall(OUT / f.stem)
    elif f.suffix.lower() == ".pdf":
        import fitz
        doc = fitz.open(str(f))
        print(f"[{f.name}] {doc.page_count}쪽", flush=True)
        txt = "\n".join(doc.load_page(i).get_text() for i in range(min(2, doc.page_count)))
        print("---- 앞 2쪽 텍스트(1200자) ----", flush=True)
        print(txt[:1200], flush=True)
