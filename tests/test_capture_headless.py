"""영상 주소를 플레이어 창 없이 받기 — 예습노트만 만들 때 창이 뜨지 않게.

학교의 fnCntsPopup 은 빈 창을 띄우고 frmStudy 를 그 창으로 제출할 뿐이다.
같은 요청을 '나의 학습' 페이지 안에서 보내고 응답에서 주소만 꺼낸다. 받은
주소가 열리지 않으면 예전처럼 창을 연다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pytest  # noqa: E402

import capture  # noqa: E402
import watch  # noqa: E402

# retrieveUSTStudy.do 응답의 생김새(주석·작은따옴표·변수 참조가 섞인 JS 객체)
STUDY_HTML = """
<script>
var arrChapter=[];
var ifrmVODPlayer_data1 = {
    "lectPldcTocNo" : "221135",
    "frmId"         : 'ifrmVODPlayer_1',
    "speedYn"       : speedYn,                      // 배속 사용 여부
    "source"    : [
        {
            "fileId"        : "221135",
            "fileTitle"     : "학습하기",   // 강의명 선택 (선택)
            "stream":[
                {
                    "label"     : "고화질",
                    "hlsUrl"    : "https://vod.example/hi/study.m3u8?t=AAA",
                    "httpUrl"   : "https://vod.example/hi/study.mp4"
                },{
                    "label"     : "저화질",
                    "hlsUrl"    : "https://vod.example/lo/study.m3u8?t=BBB"
                }
            ],
            "chapter": arrChapter,
            "continuePos"   : '0'
        }
    ]
};
var ifrmVODPlayer_data0 = {
    "lectPldcTocNo" : "221134",
    "source"    : [
        {
            "fileId"        : "221134",
            "fileTitle"     : '들어가기',
            "stream":[ { "label" : "고화질",
                         "hlsUrl" : "https://vod.example/hi/intro.m3u8?t=CCC" } ]
        }
    ]
};
$('document').ready(function () {});
</script>
"""


class _Lec:
    enc_sbjt_id, enc_toc_no, enc_atlc_no, sbjt_id = "S", "T", "A", "KNOU1"


# --- 응답 읽기 --------------------------------------------------------------
def test_every_clip_is_read_in_order():
    got = capture.parse_clip_data(STUDY_HTML)
    assert [c["idx"] for c in got] == [0, 1]
    assert [c["title"] for c in got] == ["들어가기", "학습하기"]
    assert [c["fileId"] for c in got] == ["221134", "221135"]


def test_the_first_quality_is_taken_like_the_player_does():
    """플레이어는 stream[0](고화질)을 쓴다 — 같은 것을 고른다."""
    got = capture.parse_clip_data(STUDY_HTML)
    assert got[1]["hlsUrl"] == "https://vod.example/hi/study.m3u8?t=AAA"


def test_a_response_without_clips_gives_nothing():
    assert capture.parse_clip_data("<html>로그인하세요</html>") == []
    assert capture.parse_clip_data(None) == []


def test_a_clip_without_an_address_is_kept_empty():
    html = 'var ifrmVODPlayer_data0 = { "source": [ { "fileTitle": "빈" } ] };'
    assert capture.parse_clip_data(html) == [
        {"idx": 0, "title": "빈", "fileId": "", "hlsUrl": ""}]


# --- 요청 보내기 ------------------------------------------------------------
class _Page:
    def __init__(self, html=STUDY_HTML):
        self.url = "https://ucampus.knou.ac.kr/ekp/user/study/retrieveUMYStudy.sdo"
        self.html, self.sent = html, []

    def evaluate(self, js, args):
        self.sent.append(args)
        return self.html

    def goto(self, url, **_k):
        self.url = url


def test_the_same_form_the_popup_sends_is_posted():
    page = _Page()
    got = capture.fetch_clips(page, _Lec())
    assert page.sent == [{"s": "S", "t": "T", "atlc": "A",
                          "path": "/ekp/user/study/retrieveUSTStudy.do"}]
    assert len(got) == 2


def test_the_request_goes_out_from_my_study():
    """다른 사이트(knouon)에 가 있으면 학교 쿠키·출처가 맞지 않는다."""
    page = _Page()
    page.url = "https://knouon.knou.ac.kr/lms/classroom/view.do"
    capture.fetch_clips(page, _Lec())
    assert "retrieveUMYStudy" in page.url


# --- 창 없이 먼저, 안 되면 창으로 ----------------------------------------------
class _Popup:
    closed = False

    def close(self):
        _Popup.closed = True


def _no_window(*_a, **_k):
    pytest.fail("플레이어 창을 열었습니다")


def test_a_working_address_opens_no_window(monkeypatch):
    monkeypatch.setattr(capture, "probe_duration", lambda url: 2793.6)
    monkeypatch.setattr(watch, "open_player", _no_window)
    with capture.lecture_clips(_Page(), _Lec()) as clips:
        assert [c["duration"] for c in clips] == [2793.6, 2793.6]


def test_an_address_that_will_not_open_falls_back_to_the_window(monkeypatch):
    monkeypatch.setattr(capture, "probe_duration",
                        lambda url: 100.0 if "window" in url else None)
    _Popup.closed = False
    monkeypatch.setattr(watch, "open_player", lambda page, lec: _Popup())
    monkeypatch.setattr(capture, "wait_for_clips", lambda popup: [
        {"idx": 0, "title": "학습하기", "hlsUrl": "https://window/x.m3u8"}])
    said = []
    with capture.lecture_clips(_Page(), _Lec(), said.append) as clips:
        assert clips[0]["duration"] == 100.0
        assert not _Popup.closed            # 쓰는 동안은 창을 살려 둔다
    assert _Popup.closed
    assert any("열리지 않아 플레이어를 엽니다" in m for m in said)


def test_a_failed_request_falls_back_to_the_window(monkeypatch):
    class _Broken(_Page):
        def evaluate(self, js, args):
            raise RuntimeError("fetch 실패")
    monkeypatch.setattr(capture, "probe_duration", lambda url: 50.0)
    monkeypatch.setattr(watch, "open_player", lambda page, lec: _Popup())
    monkeypatch.setattr(capture, "wait_for_clips", lambda popup: [
        {"idx": 0, "title": "학습하기", "hlsUrl": "https://window/x.m3u8"}])
    with capture.lecture_clips(_Broken(), _Lec()) as clips:
        assert clips[0]["hlsUrl"] == "https://window/x.m3u8"


def test_the_address_never_reaches_the_log(monkeypatch):
    """응답에는 시한부 영상 토큰이 들어 있다 — 기록에 남기지 않는다."""
    monkeypatch.setattr(capture, "probe_duration", lambda url: 10.0)
    said = []
    with capture.lecture_clips(_Page(), _Lec(), said.append):
        pass
    assert said and not any("m3u8" in m or "t=AAA" in m for m in said)


def test_the_main_clip_is_the_longest():
    from deck_match import _pick_main_clip
    clips = [{"idx": 0, "title": "들어가기", "duration": 40.0, "hlsUrl": "a"},
             {"idx": 1, "title": "학습하기", "duration": 2793.6, "hlsUrl": "b"},
             {"idx": 2, "title": "정리하기", "duration": None, "hlsUrl": ""}]
    assert _pick_main_clip(clips)["idx"] == 1
    assert _pick_main_clip([]) is None
