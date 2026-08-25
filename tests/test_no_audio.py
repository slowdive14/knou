"""MP3 링크가 없는 과목에서도 예습 노트가 나오는지 — download 단계 폴백 테스트.

실측(logs/run_20260821_000016.log · AI네이티브가되기위한기초소양 1강):
    MP3 URL 없음(audio_url 비어있음)
    PDF 다운로드: ..._1강.pdf ← 1강_교안.pdf      ← 강의록은 멀쩡히 받아짐
    ✗ download 실패: MP3 다운로드 실패
    · summarize: 앞 단계 실패로 건너뜀
영상(51분)도 강의록도 있는데 노트가 하나도 안 만들어졌다. 이제 두 단계로 구한다:
  ① 영상(HLS)에서 오디오만 뽑아 MP3 를 만든다 → 평소와 똑같은 품질의 노트
  ② 그것도 안 되면 강의록만으로 요약한다(단계를 실패로 만들지 않는다)
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import main  # noqa: E402


class _Lec:
    seq = 1
    name = "AI 기술 발전 동향 및 활용 사례"


class _Cfg:
    def __init__(self, tmp):
        self.downloads_dir = tmp / "downloads"
        self.summary_dir = tmp / "notes"


@pytest.fixture
def ctx(tmp_path):
    c = main._Ctx(_Cfg(tmp_path), object(), object(), None,
                  logging.getLogger("test-no-audio"))
    return c


def _fake_download(mp3_ok: bool, pdf_ok: bool):
    """download_lecture 대역 — MP3/PDF 성공 여부만 흉내낸다."""
    def _dl(*_a, **_kw):
        return {"seq": 1,
                "mp3": {"ok": mp3_ok},
                "pdf": {"ok": pdf_ok},
                "posts": []}
    return _dl


def _patch(monkeypatch, *, mp3_ok, pdf_ok, from_video):
    import download
    monkeypatch.setattr(download, "download_lecture",
                        _fake_download(mp3_ok, pdf_ok))
    calls = {"n": 0}

    def _mfv(*_a, **_kw):
        calls["n"] += 1
        return from_video

    monkeypatch.setattr(main, "_mp3_from_video", _mfv)
    return calls


# --- ① 영상에서 오디오를 뽑아 성공하는 길 ----------------------------------
def test_missing_mp3_falls_back_to_video_audio(ctx, monkeypatch):
    calls = _patch(monkeypatch, mp3_ok=False, pdf_ok=True, from_video=True)
    res = main._stage_download(ctx, "AI네이티브", _Lec())
    assert res["ok"] is True
    assert res["detail"]["mp3_from_video"] is True
    assert calls["n"] == 1


def test_working_mp3_link_does_not_touch_the_video(ctx, monkeypatch):
    # 평소 과목은 예전 경로 그대로 — 괜히 플레이어를 열지 않는다
    calls = _patch(monkeypatch, mp3_ok=True, pdf_ok=True, from_video=True)
    res = main._stage_download(ctx, "자료구조", _Lec())
    assert res["ok"] is True and calls["n"] == 0
    assert "mp3_from_video" not in res["detail"]


# --- ② 강의록만으로라도 요약하는 길 -----------------------------------------
def test_pdf_only_still_succeeds(ctx, monkeypatch):
    # 예전에는 여기서 download 실패 → summarize/capture 가 통째로 건너뛰어졌다
    _patch(monkeypatch, mp3_ok=False, pdf_ok=True, from_video=False)
    res = main._stage_download(ctx, "AI네이티브", _Lec())
    assert res["ok"] is True
    assert res["detail"]["audio"] is False
    assert res["detail"]["pdf"] is True


def test_pdf_only_does_not_block_summarize():
    # 단계 의존성상 download 가 ok 면 요약·덱은 그대로 진행된다
    assert main.dependent_stages("download", ["download", "summarize"]) == {
        "summarize"}


# --- 아무것도 못 구하면 정직하게 실패 ---------------------------------------
def test_no_audio_and_no_pdf_is_a_real_failure(ctx, monkeypatch):
    _patch(monkeypatch, mp3_ok=False, pdf_ok=False, from_video=False)
    res = main._stage_download(ctx, "AI네이티브", _Lec())
    assert res["ok"] is False
    assert "강의록" in res["error"]


def test_failure_message_no_longer_blames_mp3_only(ctx, monkeypatch):
    # 예전 문구('MP3 다운로드 실패')는 원인을 오해하게 만들었다
    _patch(monkeypatch, mp3_ok=False, pdf_ok=False, from_video=False)
    res = main._stage_download(ctx, "AI네이티브", _Lec())
    assert res["error"] != "MP3 다운로드 실패"
