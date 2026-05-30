"""로그인을 보장한 뒤 페이지 구조(HTML/스크린샷)를 recon_shots/ 에 저장하는 개발 도구.

auth.ensure_logged_in 으로 자동 로그인을 보장한 다음 '나의 학습' 페이지를
프레임별 HTML + 전체 스크린샷으로 떠서 저장한다.
개발자(=Claude)가 그 HTML을 읽어 Phase 2 셀렉터를 만든다.

실행:
    .venv/Scripts/python.exe dump_dom.py
"""
from __future__ import annotations

import sys

# Windows 콘솔(cp949)에서도 한글/이모지를 깨지지 않게 출력
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import MY_STUDY_URL, ensure_logged_in
from config import load_config
from recon import SHOTS_DIR, launch_context


def _dump_frames(page, tag: str) -> None:
    """페이지와 모든 프레임의 HTML을 파일로 저장."""
    SHOTS_DIR.mkdir(exist_ok=True)
    for i, fr in enumerate(page.frames):
        try:
            html = fr.content()
        except Exception as e:
            html = f"<!-- frame content 실패: {e} -->"
        url = (fr.url or "")[:80]
        path = SHOTS_DIR / f"dom_{tag}_frame{i}.html"
        path.write_text(f"<!-- URL: {fr.url} -->\n{html}", encoding="utf-8")
        print(f"  저장: {path.name}  ({url})")


def main() -> None:
    SHOTS_DIR.mkdir(exist_ok=True)
    cfg = load_config()

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 로그인 보장 (필요시 자동 로그인)
        ok = ensure_logged_in(page, cfg)
        print(f"로그인 보장 결과: {'✅ 로그인됨' if ok else '❌ 실패'}")

        # 로그인된 '나의 학습' 페이지를 networkidle 까지 기다린 뒤 덤프
        print(f"이동: {MY_STUDY_URL}")
        page.goto(MY_STUDY_URL, wait_until="networkidle", timeout=30000)
        print(f"도달 URL: {page.url}")
        try:
            print(f"제목    : {page.title()}")
        except Exception:
            pass

        try:
            page.screenshot(path=str(SHOTS_DIR / "dom_myStudy.png"), full_page=True)
        except Exception as e:
            print(f"  스크린샷 실패: {e}")
        _dump_frames(page, "myStudy")

        ctx.close()
        print("완료. recon_shots/ 의 dom_*.html 을 확인하세요.")


if __name__ == "__main__":
    main()
