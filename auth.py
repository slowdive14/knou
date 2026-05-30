"""Phase 1 — 로그인 & 세션 유지.

- `is_logged_in(html, url)`: 순수 판정 로직 (단위테스트 대상)
- `ensure_logged_in(page, cfg)`: 페이지가 로그인 안 됐으면 자동 로그인
- `login_context(p, cfg)`: persistent context(진짜 Chrome) 열고 로그인 보장

KNOU 로그인은 비밀번호를 페이지 JS(_enpass_login_/RSA)가 알아서 암호화하므로,
우리는 진짜 입력칸을 채우고 진짜 로그인 버튼을 누르기만 하면 된다.
"""
from __future__ import annotations

import re

# recon.py의 검증된 브라우저 실행 로직(진짜 Chrome 채널, 프로필 잠금정리)을 재사용
from recon import AUTH_DIR, launch_context  # noqa: F401

LOGIN_URL = "https://ucampus.knou.ac.kr/ekp/user/login/retrieveULOLogin.do"
MY_STUDY_URL = "https://ucampus.knou.ac.kr/ekp/user/study/retrieveUMYStudy.sdo"

# 셀렉터 (docs/lms-map.md §1)
SEL_USERNAME = "#username"
SEL_PASSWORD = "#password"
SEL_LOGIN_BTN = "button[onclick*='actionLogin']"

_PW_FIELD_RE = re.compile(r"type\s*=\s*[\"']password[\"']", re.IGNORECASE)
_LOGOUT_RE = re.compile(r"로그아웃|Logout\.do", re.IGNORECASE)


def is_logged_in(html: str, url: str = "") -> bool:
    """HTML/URL 스니펫만으로 '로그인됨' 여부를 판정 (순수 함수).

    규칙:
      - URL이 로그인 페이지(retrieveULOLogin)면 → 로그인 안 됨
      - 본문에 비밀번호 입력칸이 있으면 → 로그인 안 됨
      - 그 외(특히 로그아웃 링크 존재)면 → 로그인됨
    """
    url = url or ""
    html = html or ""
    # 1) 로그인 페이지로 리다이렉트됐으면 확실히 로그인 안 됨 (가장 강한 신호)
    if "retrieveULOLogin" in url or "/login/retrieveULO" in url:
        return False
    # 2) 로그아웃 링크가 보이면 확실히 로그인됨
    #    (방송대는 헤더에 '숨은 로그인 폼'이 있어 password 입력칸만으론 판정 불가)
    if _LOGOUT_RE.search(html):
        return True
    # 3) 로그아웃 링크가 없고 비밀번호 입력칸이 주 콘텐츠면 로그인 안 됨
    if _PW_FIELD_RE.search(html):
        return False
    return True


def _current_state(page) -> bool:
    """현재 페이지가 로그인 상태인지 실제 DOM/URL로 확인."""
    try:
        html = page.content()
    except Exception:
        html = ""
    return is_logged_in(html, page.url)


def ensure_logged_in(page, cfg, timeout_ms: int = 30000,
                     force_fresh: bool = True) -> bool:
    """페이지를 '나의 학습'으로 보내고, 로그인 안 됐으면 자동 로그인한다.

    Returns: 최종 로그인 성공 여부.

    ⚠️ 방송대는 단일세션이라 .auth 에 남은 쿠키로 '재사용'하면 서버가 이전 세션을
       무효화해 학습 페이지가 스스로 닫히거나(TargetClosed) 로그인으로 튕긴다.
       그래서 기본값 force_fresh=True 로 매 실행마다 쿠키를 비워 '신선한 로그인'을
       강제한다(자동 로그인은 수초면 끝나고 훨씬 안정적). 재사용을 원하면 False.
    """
    if force_fresh:
        try:
            page.context.clear_cookies()
        except Exception:
            pass

    page.goto(MY_STUDY_URL, wait_until="domcontentloaded", timeout=timeout_ms)

    if not force_fresh and _current_state(page):
        print("✅ 이미 로그인된 세션 재사용")
        return True

    print("🔑 세션 없음 → 자동 로그인 시도")
    # 로그인 페이지로 확실히 이동(이미 리다이렉트됐을 수 있음)
    if "retrieveULOLogin" not in page.url:
        page.goto(LOGIN_URL, wait_until="domcontentloaded", timeout=timeout_ms)

    page.wait_for_selector(SEL_PASSWORD, timeout=timeout_ms)
    page.fill(SEL_USERNAME, cfg.knou_id)
    page.fill(SEL_PASSWORD, cfg.knou_pw)

    # 진짜 로그인 버튼 클릭 → 페이지 JS가 암호화/제출 처리
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout_ms):
            page.click(SEL_LOGIN_BTN)
    except Exception:
        # 네비게이션 감지 실패 시에도 잠시 대기 후 상태 확인
        page.wait_for_timeout(3000)

    # 로그인 후 보호 페이지로 한 번 더 이동해 상태 확정
    page.goto(MY_STUDY_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    ok = _current_state(page)
    if ok:
        print("✅ 자동 로그인 성공")
    else:
        print("❌ 자동 로그인 실패 — 아이디/비밀번호 또는 셀렉터 확인 필요")
    return ok


def login_context(p, cfg):
    """진짜 Chrome persistent context를 열고 로그인을 보장한 뒤 (ctx, page) 반환."""
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ensure_logged_in(page, cfg)
    return ctx, page
