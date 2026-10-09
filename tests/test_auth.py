"""auth.is_logged_in 판정 로직 단위 테스트.

실제 브라우저 로그인은 수동 검증(login_check.py)으로 확인한다.
여기서는 HTML/URL 스니펫만으로 '로그인됨' 판정이 정확한지 본다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from auth import is_logged_in  # noqa: E402

LOGIN_URL = (
    "https://ucampus.knou.ac.kr/ekp/user/login/retrieveULOLogin.do"
    "?cm_cg_id=ABC.jvmsso2&rserpubk=MIIxxx&c_s_t=1780027602960"
)
STUDY_URL = "https://ucampus.knou.ac.kr/ekp/user/study/retrieveUMYStudy.sdo"

LOGIN_HTML = """
<html><head><title>통합로그인</title></head><body>
  <form id="loginForm" name="loginForm">
    <input type="text" name="username" id="username">
    <input type="password" name="password" id="password">
    <button onclick="actionLogin();return false;">로그인</button>
  </form>
</body></html>
"""

STUDY_HTML = """
<html><head><title>마이페이지-학습목록</title></head><body>
  <a href="/ekp/user/login/processULOLogout.do">로그아웃</a>
  <div class="study-list">...</div>
</body></html>
"""


def test_login_page_is_not_logged_in():
    assert is_logged_in(LOGIN_HTML, LOGIN_URL) is False


def test_study_page_is_logged_in():
    assert is_logged_in(STUDY_HTML, STUDY_URL) is True


def test_password_field_means_not_logged_in():
    # URL이 비어 있어도 비밀번호 입력칸이 있으면 로그인 안 된 것
    assert is_logged_in(LOGIN_HTML, "") is False


def test_login_url_means_not_logged_in_even_without_pw_field():
    # 리다이렉트 직후 등 본문이 비어도 URL이 로그인 페이지면 False
    assert is_logged_in("<html></html>", LOGIN_URL) is False


def test_logout_link_means_logged_in():
    html = '<html><title>학습</title><a href="...Logout.do">로그아웃</a></html>'
    assert is_logged_in(html, STUDY_URL) is True


def test_hidden_header_login_form_still_logged_in():
    # 방송대 실제 사례: 로그인된 페이지에도 헤더에 숨은 로그인 폼(password)이 있음.
    # 로그아웃 링크가 있으면 password 입력칸이 있어도 로그인된 것으로 판정해야 한다.
    html = """
    <html><head><title>마이페이지-학습목록</title></head><body>
      <header><a href="/ekp/user/login/processULOLogout.do">로그아웃</a>
        <form id="loginForm"><input type="password" name="password"></form>
      </header>
      <div class="study-list">강의목록</div>
    </body></html>
    """
    assert is_logged_in(html, STUDY_URL) is True


# --- 바이오통계학(knouon)에 다녀온 뒤 '나의 학습' 으로 돌아오기 --------------
# 실측(2026-10-05): 주차를 읽으러 knouon 에 건너간 채로 자료구조 5강을 열어
# 'fnCntsPopup is not defined' 로 영상·형성평가가 통째로 실패했다.
class _Page:
    def __init__(self, url):
        self.url = url
        self.went = []

    def goto(self, url, **_k):
        self.went.append(url)
        self.url = url


def test_a_page_left_on_knouon_comes_back():
    from auth import MY_STUDY_URL, back_to_my_study
    p = _Page("https://knouon.knou.ac.kr/lms/classroom/view.do")
    assert back_to_my_study(p) is True
    assert p.went == [MY_STUDY_URL]


def test_a_page_already_home_stays():
    from auth import MY_STUDY_URL, back_to_my_study
    p = _Page(MY_STUDY_URL)
    assert back_to_my_study(p) is False
    assert p.went == []


# --- 2026-10 에 바뀐 로그인 화면 ---------------------------------------------
# 사용자 유형이 LEGACY((구)로그인, 기본) · STUDENT(모바일·아이디·패스키) ·
# GENERAL 로 갈렸다. 예전 셀렉터는 숨은 칸을 30초 기다리다 멈췄다.
from contextlib import contextmanager  # noqa: E402

import pytest  # noqa: E402

import auth  # noqa: E402

LEGACY_PAGE = {
    "#username_legacy": False, "#password_legacy": False,
    "button[onclick*='actionLegacyLogin']": True,
    "#username_id": False, "#password": False, "#btn_login": False,
    "#username": False,
    "#addAuthSendBtn": False,
}
# 라디오를 고르면 보이게 되는 칸
REVEALS = {
    "#legacy_tab_stu": ("#username_legacy", "#password_legacy"),
    "#ucampus-tab_id": ("#username_id", "#password", "#btn_login"),
}


class _El:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    def is_visible(self):
        return self.page.dom[self.sel]


class _LoginPage:
    def __init__(self, dom, after_url=None, after_dom=None):
        self.dom = dict(dom)
        self.url = auth.LOGIN_URL
        self.filled, self.clicked, self.picked = {}, [], []
        self.after_url = after_url or auth.MY_STUDY_URL
        self.after_dom = after_dom
        self.context = self

    def clear_cookies(self):
        pass

    def goto(self, url, **_k):
        if self.clicked and url == auth.MY_STUDY_URL:
            self.url = self.after_url
        elif not self.clicked:
            self.url = auth.LOGIN_URL

    def content(self):
        if self.url == auth.MY_STUDY_URL:
            return '<a href="/ekp/user/login/processULOLogout.do">로그아웃</a>'
        return '<input type="password" id="password">'

    def query_selector(self, sel):
        return _El(self, sel) if sel in self.dom else None

    def evaluate(self, _js, sel):
        self.picked.append(sel)
        for s in REVEALS.get(sel, ()):
            if s in self.dom:
                self.dom[s] = True

    def wait_for_selector(self, sel, state="visible", timeout=0):
        if not self.dom.get(sel):
            raise TimeoutError(sel)

    def fill(self, sel, value):
        if not self.dom.get(sel):
            raise TimeoutError(sel)
        self.filled[sel] = value

    def click(self, sel):
        self.clicked.append(sel)
        if self.after_dom:
            self.dom.update(self.after_dom)

    @contextmanager
    def expect_navigation(self, **_k):
        yield

    def wait_for_timeout(self, _ms):
        pass


class _Cfg:
    knou_id = "student01"
    knou_pw = "pw-secret"


def test_the_old_style_login_is_used_while_it_lasts():
    page = _LoginPage(LEGACY_PAGE)
    way = auth.submit_login(page, _Cfg())
    assert way.name == "(구)로그인"
    assert page.picked[:2] == ["input[name=user_type][value=LEGACY]",
                               "#legacy_tab_stu"]
    assert page.filled == {"#username_legacy": "student01",
                           "#password_legacy": "pw-secret"}
    assert page.clicked == ["button[onclick*='actionLegacyLogin']"]


def test_when_the_old_style_closes_the_id_login_is_used():
    dom = {k: v for k, v in LEGACY_PAGE.items() if "legacy" not in k.lower()}
    page = _LoginPage(dom)
    way = auth.submit_login(page, _Cfg())
    assert way.name == "아이디 로그인"
    assert "#ucampus-tab_id" in page.picked
    assert page.filled == {"#username_id": "student01",
                           "#password": "pw-secret"}
    assert page.clicked == ["#btn_login"]


def test_a_way_whose_fields_never_show_is_skipped():
    """(구)로그인 칸이 안 보이면 오래 기다리지 않고 아이디 로그인으로 간다."""
    page = _LoginPage(LEGACY_PAGE)
    saved = dict(REVEALS)
    REVEALS["#legacy_tab_stu"] = ()
    try:
        way = auth.submit_login(page, _Cfg())
    finally:
        REVEALS.update(saved)
    assert way.name == "아이디 로그인"


def test_the_page_before_the_change_still_works():
    page = _LoginPage({"#username": True, "#password": True,
                       "button[onclick*='actionLogin']": True})
    assert auth.submit_login(page, _Cfg()).name == "예전 로그인"


def test_an_unknown_login_page_says_so_without_the_password():
    page = _LoginPage({"#somethingElse": True})
    with pytest.raises(auth.LoginFailed) as e:
        auth.submit_login(page, _Cfg())
    assert "로그인 화면이 또 바뀐" in str(e.value)
    assert "pw-secret" not in str(e.value)


def test_a_full_login_lands_on_my_study():
    page = _LoginPage(LEGACY_PAGE)
    assert auth.ensure_logged_in(page, _Cfg()) is True


def test_extra_authentication_stops_with_a_clear_reason():
    """이메일·앱 인증번호는 앱이 대신 넘길 수 없다 — 멈추고 알린다."""
    page = _LoginPage(LEGACY_PAGE, after_dom={"#addAuthSendBtn": True})
    with pytest.raises(auth.LoginFailed) as e:
        auth.ensure_logged_in(page, _Cfg())
    assert "추가 인증" in str(e.value)


def test_coming_back_to_the_login_page_is_a_failure():
    page = _LoginPage(LEGACY_PAGE, after_url=auth.LOGIN_URL)
    with pytest.raises(auth.LoginFailed) as e:
        auth.ensure_logged_in(page, _Cfg())
    assert "아이디·비밀번호를 확인" in str(e.value)
