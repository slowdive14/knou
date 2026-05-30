"""download 모듈 순수 로직 단위 테스트 (Phase 4).

파일명 규칙 / 다운로드 필요판정 / PDF URL 구성 / 차시→강의자료글 매칭만 검증.
실제 네트워크 다운로드(브라우저/HTTP)는 수동 검증(download_one.py).

강의자료실 실측(recon_shots/lecturedata_list.json):
  - 분류 '강의자료' + apndFileNm 이 'NN-' 로 시작 = 차시별 강의록 PDF
  - 다운로드 URL: /user_uploading?pathkey=COURSE.DATA&addSavePath={sbjtId}
                  &getfile={apndFileSaveNm}&realFileName={표시명}
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from download import (  # noqa: E402
    build_filename,
    build_file_url,
    match_pdf_post,
    needs_download,
    sanitize,
)

# 강의자료실 목록에서 가져온 실제 글 형태(축약)
POSTS = [
    {"bdotNo": "135170", "sbjtBdotClcd": "강의자료", "fileCnt": "1",
     "sbjtNotcTitNm": "[필독] &lt;이산수학&gt; 교재 및 워크북 정오표(2023)",
     "apndFileNm": "이산수학 정오표(교재 및 워크북)-2023-03-18.pdf",
     "apndFileSaveNm": "1679272285122.pdf"},
    {"bdotNo": "106970", "sbjtBdotClcd": "강의자료", "fileCnt": "1",
     "sbjtNotcTitNm": "1강-이산수학의 개요",
     "apndFileNm": "01-이산수학의개요(수정).pdf",
     "apndFileSaveNm": "1612862659831.pdf"},
    {"bdotNo": "108293", "sbjtBdotClcd": "강의자료", "fileCnt": "1",
     "sbjtNotcTitNm": "13-정수론",
     "apndFileNm": "13-정수론 (녹화용)(수정).pdf",
     "apndFileSaveNm": "1620605193391.pdf"},
    {"bdotNo": "108532", "sbjtBdotClcd": "강의자료", "fileCnt": "1",
     "sbjtNotcTitNm": "15-이산수학 학습내용 정리",
     "apndFileNm": "15-교과목 정리 (강의자료).pdf",
     "apndFileSaveNm": "1621064315148.pdf"},
    {"bdotNo": "106830", "sbjtBdotClcd": "기출문제", "fileCnt": "2",
     "sbjtNotcTitNm": "[2019-1학기] 기말시험 기출문제",
     "apndFileNm": "251-이산수학-2학년-2교시.pdf:251-이산수학-2학년-2교시.hwp",
     "apndFileSaveNm": "1561354724902.pdf:1561354730308.hwp"},
]


# ---- sanitize -------------------------------------------------------------
def test_sanitize_removes_illegal_chars():
    assert sanitize("이산수학") == "이산수학"
    assert sanitize('a/b:c*d?e"f<g>h|i') == "a_b_c_d_e_f_g_h_i"
    # 앞뒤 공백/점 제거
    assert sanitize("  x. ") == "x"


# ---- build_filename -------------------------------------------------------
def test_build_filename_basic():
    assert build_filename("이산수학", 1, "mp3") == "이산수학_1강.mp3"
    assert build_filename("이산수학", 13, "pdf") == "이산수학_13강.pdf"


def test_build_filename_strips_dot_and_sanitizes():
    # 확장자 점 유무 모두 허용
    assert build_filename("이산수학", 2, ".pdf") == "이산수학_2강.pdf"
    # 과목명에 금지문자가 있으면 치환
    assert build_filename("운영체제: 기초", 3, "mp3") == "운영체제_ 기초_3강.mp3"


# ---- needs_download -------------------------------------------------------
def test_needs_download_missing_file(tmp_path):
    assert needs_download(tmp_path / "nope.pdf") is True


def test_needs_download_empty_file(tmp_path):
    p = tmp_path / "empty.pdf"
    p.write_bytes(b"")
    assert needs_download(p) is True


def test_needs_download_existing_nonempty(tmp_path):
    p = tmp_path / "ok.pdf"
    p.write_bytes(b"%PDF-1.4 data")
    assert needs_download(p) is False


# ---- build_file_url -------------------------------------------------------
def test_build_file_url_minimal():
    url = build_file_url("KNOU1545001", "1612862659831.pdf")
    assert url.startswith("https://ucampus.knou.ac.kr/user_uploading?")
    assert "pathkey=COURSE.DATA" in url
    assert "addSavePath=KNOU1545001" in url
    assert "getfile=1612862659831.pdf" in url


def test_build_file_url_with_realname_encoded():
    url = build_file_url("KNOU1545001", "x.pdf", real_nm="01-이산수학의개요(수정).pdf")
    # 표시 파일명은 URL 인코딩되어야 함(한글/괄호)
    assert "realFileName=" in url
    assert "이산수학" not in url  # 인코딩되어 원문 한글이 그대로 남지 않음


# ---- match_pdf_post -------------------------------------------------------
def test_match_pdf_post_finds_lecture_by_prefix():
    m = match_pdf_post(POSTS, 1)
    assert m is not None
    assert m["bdotNo"] == "106970"
    assert m["save_nm"] == "1612862659831.pdf"
    assert m["display_nm"] == "01-이산수학의개요(수정).pdf"
    assert m["ext"] == "pdf"


def test_match_pdf_post_seq13_and_15():
    assert match_pdf_post(POSTS, 13)["bdotNo"] == "108293"
    assert match_pdf_post(POSTS, 15)["bdotNo"] == "108532"


def test_match_pdf_post_ignores_non_lecture_categories():
    # 정오표(강의자료지만 NN- 접두사 없음), 기출문제는 차시 매칭 안 됨
    assert match_pdf_post(POSTS, 251) is None  # 251-... 은 기출(기출문제 분류)
    # 없는 차시
    assert match_pdf_post(POSTS, 99) is None


def test_match_pdf_post_empty_list():
    assert match_pdf_post([], 1) is None
