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
#
# ⚠️ 2026-10 에 로그인 페이지가 바뀌었다. 사용자 유형이 셋으로 갈리고
#    (user_type = LEGACY · STUDENT · GENERAL), 기본으로 열리는 것은
#    '(구)로그인'(LEGACY)이다. 학교 안내: "서비스 안정화를 위한 과도기 동안
#    한시적으로 제공되며 추후 종료될 예정". 새 방식(STUDENT)은 모바일 인증 ·
#    아이디 · 패스키 탭으로 나뉜다.
#    예전 셀렉터(#username + #password + actionLogin 단추)는 더 이상 맞지
#    않는다 — #username 은 숨은 칸이 되었고 #password 는 숨은 탭 안에 있어,
#    보일 때까지 기다리다 30초 뒤에 실패했다(실측: 10-07 · 10-09 실행이
#    시작하자마자 멈춤).
SEL_USERNAME = "#username"
SEL_PASSWORD = "#password"
SEL_LOGIN_BTN = "button[onclick*='actionLogin']"


class LoginWay:
    """로그인 길 하나 — 어떤 칸에 아이디·비밀번호를 넣고 무엇을 누르는가.

    picks 는 칸을 보이게 하려고 먼저 골라야 하는 라디오(사용자 유형·탭)다.
    """

    def __init__(self, name, user, pw, button, picks=()):
        self.name, self.user, self.pw = name, user, pw
        self.button, self.picks = button, tuple(picks)

    def __repr__(self):
        return f"LoginWay({self.name})"


# 앞의 것부터 시도한다. (구)로그인이 남아 있는 동안은 예전과 같은 서버 경로라
# 추가 인증이 없다. 닫히면 새 아이디 로그인(학생 → 아이디 탭)으로 간다.
LOGIN_WAYS = (
    LoginWay("(구)로그인", "#username_legacy", "#password_legacy",
             "button[onclick*='actionLegacyLogin']",
             ("input[name=user_type][value=LEGACY]", "#legacy_tab_stu")),
    LoginWay("아이디 로그인", "#username_id", "#password", "#btn_login",
             ("input[name=user_type][value=STUDENT]", "#ucampus-tab_id")),
    LoginWay("예전 로그인", SEL_USERNAME, SEL_PASSWORD, SEL_LOGIN_BTN),
)

# 아이디·비밀번호 다음에 학교가 더 묻는 단계(이메일·앱 인증번호 등)가 떴는가.
# 앱이 대신 넘길 수 없다 — 사람이 직접 해야 한다.
EXTRA_AUTH_SELECTORS = ("#addAuthSendBtn", "#addAuthOtpCode",
                        "#mobileConfirmBtn", "#qrConfirmBtn")


class LoginFailed(RuntimeError):
    """로그인을 끝내지 못했다 — 메시지는 사람에게 그대로 보여 준다."""

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

    way = submit_login(page, cfg, timeout_ms)

    # 로그인 후 보호 페이지로 한 번 더 이동해 상태 확정
    if extra_auth_shown(page):
        raise LoginFailed(EXTRA_AUTH_NOTE)
    page.goto(MY_STUDY_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    ok = _current_state(page)
    if ok:
        print(f"✅ 자동 로그인 성공({way.name})")
        return True
    if "retrieveULOLogin" in (page.url or ""):
        # 로그인 페이지로 되돌아왔다 — 아이디·비밀번호가 틀렸거나 막혔다
        raise LoginFailed(
            f"로그인하지 못했습니다({way.name}) — 설정의 아이디·비밀번호를 "
            "확인해 주세요. 맞는데도 그렇다면 학교 로그인 화면이 또 바뀐 "
            "것입니다.")
    print("❌ 자동 로그인 실패 — 아이디/비밀번호 또는 셀렉터 확인 필요")
    return False


EXTRA_AUTH_NOTE = ("학교가 아이디·비밀번호 다음에 추가 인증(이메일·앱 인증번호)을 "
                   "요구합니다. 앱이 대신 넘길 수 없습니다 — 브라우저에서 한 번 "
                   "직접 로그인해 주세요.")


def _exists(page, selector) -> bool:
    try:
        return page.query_selector(selector) is not None
    except Exception:  # noqa: BLE001 - 페이지가 바뀌는 중일 수 있다
        return False


def _visible(page, selector) -> bool:
    try:
        el = page.query_selector(selector)
        return bool(el and el.is_visible())
    except Exception:  # noqa: BLE001
        return False


def extra_auth_shown(page) -> bool:
    """아이디·비밀번호 다음 단계(인증번호 등)가 화면에 떠 있는가."""
    return any(_visible(page, s) for s in EXTRA_AUTH_SELECTORS)


def present(page, way) -> bool:
    """이 길이 지금 로그인 페이지에 있는가 — 단추와 아이디 칸이 둘 다."""
    return _exists(page, way.button) and _exists(page, way.user)


def _choose(page, selector) -> None:
    """숨은 라디오(사용자 유형·탭)를 고른다 — 페이지가 그 칸을 보여 주게.

    라디오 자체는 화면에 없고 라벨만 보인다. 요소의 click() 을 부르면 사람이
    라벨을 누른 것과 같은 change 이벤트가 난다.
    """
    page.evaluate(
        "(sel) => { const r = document.querySelector(sel);"
        " if (r && !r.checked) r.click(); }", selector)


def submit_login(page, cfg, timeout_ms: int = 30000):
    """로그인 페이지에서 아이디·비밀번호를 넣고 제출한다 → 쓴 길.

    길마다 칸이 보일 때까지 잠깐만 기다린다. 안 보이면 다음 길로 넘어간다 —
    예전처럼 숨은 칸을 30초 기다리다 통째로 멈추지 않는다.

    ⚠️ 비밀번호는 칸에 넣기만 한다. 로그·화면·예외 메시지에 남기지 않는다.
    """
    tried = []
    for way in LOGIN_WAYS:
        if not present(page, way):
            continue
        for sel in way.picks:
            try:
                _choose(page, sel)
            except Exception:  # noqa: BLE001 - 고르지 못하면 칸이 안 보인다
                pass
        try:
            page.wait_for_selector(way.user, state="visible",
                                   timeout=min(timeout_ms, 8000))
            page.fill(way.user, cfg.knou_id)
            page.fill(way.pw, cfg.knou_pw)
        except Exception:  # noqa: BLE001 - 이 길의 칸이 보이지 않는다
            tried.append(way.name)
            continue
        # 진짜 로그인 버튼 클릭 → 페이지 JS 가 제출을 처리한다
        try:
            with page.expect_navigation(wait_until="domcontentloaded",
                                        timeout=timeout_ms):
                page.click(way.button)
        except Exception:  # noqa: BLE001 - 같은 화면에 인증 창만 뜰 수도 있다
            page.wait_for_timeout(3000)
        return way
    raise LoginFailed(
        "학교 로그인 화면에서 아이디·비밀번호 칸을 찾지 못했습니다"
        + (f"({', '.join(tried)} 칸이 보이지 않음)" if tried else "")
        + " — 로그인 화면이 또 바뀐 것 같습니다.")


MY_STUDY_MARK = "retrieveUMYStudy"     # '나의 학습' 주소에 든 글자


def on_my_study(url) -> bool:
    """이 주소가 '나의 학습' 인가 — 강의 팝업(fnCntsPopup)·차시 조회가 사는 곳."""
    return MY_STUDY_MARK in str(url or "")


def back_to_my_study(page, timeout_ms: int = 30000) -> bool:
    """'나의 학습' 밖에 나가 있으면 돌아온다 → 옮겼는가.

    바이오통계학은 별도 사이트(knouon)라, 그 주차를 읽고 나면 페이지가 그쪽에
    남는다. 그대로 전자캠퍼스 강의를 열면 'fnCntsPopup is not defined' 로
    영상·형성평가가 통째로 실패한다(실측: 2026-10-05 자료구조 5강).

    ⚠️ ensure_logged_in 과 달리 쿠키를 지우거나 다시 로그인하지 않는다 — 같은
       세션에서 주소만 옮긴다(실행 도중 새로 로그인하면 단일 세션이라 앞 세션이
       끊긴다).
    """
    if on_my_study(getattr(page, "url", "")):
        return False
    page.goto(MY_STUDY_URL, wait_until="domcontentloaded", timeout=timeout_ms)
    return True


def login_context(p, cfg):
    """진짜 Chrome persistent context를 열고 로그인을 보장한 뒤 (ctx, page) 반환."""
    ctx = launch_context(p)
    page = ctx.pages[0] if ctx.pages else ctx.new_page()
    ensure_logged_in(page, cfg)
    return ctx, page
