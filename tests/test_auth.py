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
