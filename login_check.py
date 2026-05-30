"""Phase 1 수동 검증: 실제 자동 로그인이 되는지 1회 확인.

진짜 Chrome 창을 열어 .env의 아이디/비밀번호로 자동 로그인 →
'나의 학습' 도달 여부를 출력하고 세션을 .auth/에 저장한 뒤 닫는다.

실행:
    .venv/Scripts/python.exe login_check.py
"""
from __future__ import annotations

import sys

# Windows 콘솔(cp949)에서도 한글/이모지 출력이 깨지거나 죽지 않게
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import login_context
from config import load_config


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx, page = login_context(p, cfg)
        print("-" * 50)
        print(f"최종 URL : {page.url}")
        try:
            print(f"제목     : {page.title()}")
        except Exception:
            pass
        # 비밀번호는 절대 출력하지 않는다
        ctx.close()
    print("완료. 세션은 .auth/ 에 저장됨.")


if __name__ == "__main__":
    main()
