"""실습 자료 — 강의 후반부의 코딩 실습을 노트에 담기 위해.

오픈소스기반데이터분석 5강은 57분 중 26분부터 노트북 빈칸을 채우는 실습인데,
노트는 26분에서 끝났다. 요약 모델이 음성과 강의록(PDF)만 받았고, 강의록에는
실습이 한 줄 소개뿐이었다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import practice  # noqa: E402
import summarize  # noqa: E402

NB = {"cells": [
    {"cell_type": "markdown", "source": ['<a href="https://colab...">배지</a>']},
    {"cell_type": "markdown", "source": ["# 5강 - 데이터 저장"]},
    {"cell_type": "markdown", "source": ["## 5-1 CSV 형식 저장"]},
    {"cell_type": "code", "source": ["data = {'a': [1]}\n", "## DataFrame 생성\n"],
     "outputs": []},
    {"cell_type": "code", "source": ["print(1)"],
     "outputs": [{"output_type": "stream", "text": ["1\n"]}]},
]}


# --- 어느 과목에 실습 자료가 있나 ---------------------------------------------
def test_the_open_source_course_has_a_notebook_source():
    assert practice.source_for("오픈소스기반데이터분석")
    assert practice.source_for("오픈소스 기반 데이터분석")      # 띄어쓰기 무시
    assert practice.source_for("자료구조") is None


def test_the_notebook_is_looked_for_in_both_repositories():
    urls = practice.raw_urls("오픈소스기반데이터분석", 5)
    assert len(urls) == 2
    assert "slowdive15/Data-Analysis-with-Open-Source" in urls[0]
    assert "jaehwachung/Data-Analysis-with-Open-Source" in urls[1]
    assert urls[0].startswith("https://raw.githubusercontent.com/")
    assert "5%EA%B0%95.ipynb" in urls[0]                     # '5강' 이 인코딩됨


def test_a_course_without_practice_has_no_urls():
    assert practice.raw_urls("자료구조", 5) == []


# --- 노트북 → 글 -------------------------------------------------------------
def test_the_notebook_becomes_steps_and_code():
    text = practice.notebook_text(NB)
    assert "## 5-1 CSV 형식 저장" in text
    assert "```python\ndata = {'a': [1]}\n## DataFrame 생성\n```" in text
    assert "배지" not in text                                # 링크 줄은 뺀다


def test_outputs_are_kept_short():
    text = practice.notebook_text(NB)
    assert "출력:\n```\n1\n```" in text


def test_a_broken_notebook_gives_nothing(tmp_path):
    f = tmp_path / "x.ipynb"
    f.write_text("{깨짐", encoding="utf-8")
    assert practice.load_notebook_text(f) == ""


# --- 받기 --------------------------------------------------------------------
def test_the_first_repository_that_answers_wins(tmp_path):
    asked = []

    def opener(url):
        asked.append(url)
        if "slowdive15" in url:
            raise OSError("404")
        return json.dumps(NB).encode("utf-8")
    got = practice.fetch_notebook("오픈소스기반데이터분석", 5, tmp_path,
                                  opener=opener)
    assert got.name == "오픈소스기반데이터분석_5강.ipynb"
    assert len(asked) == 2


def test_a_notebook_already_there_is_not_fetched_again(tmp_path):
    f = tmp_path / "오픈소스기반데이터분석_5강.ipynb"
    f.write_text(json.dumps(NB), encoding="utf-8")
    got = practice.fetch_notebook("오픈소스기반데이터분석", 5, tmp_path,
                                  opener=lambda u: (_ for _ in ()).throw(
                                      AssertionError("받았다")))
    assert got == f


def test_something_that_is_not_a_notebook_is_refused(tmp_path):
    got = practice.fetch_notebook("오픈소스기반데이터분석", 5, tmp_path,
                                  opener=lambda u: b"<html>not found</html>")
    assert got is None


# --- 화면 고르기 ---------------------------------------------------------------
def test_a_still_screen_is_shown_once():
    """강사가 말만 하고 화면이 그대로면 같은 장면을 여러 번 보낼 까닭이 없다."""
    samples = [(0, 0b0000), (15, 0b0001), (30, 0b1111_1111), (45, 0b1111_1110)]
    assert practice.pick_screens(samples, same=2) == [0, 30]


def test_too_many_screens_are_thinned_evenly():
    samples = [(i * 15, (1 << (i % 60)) - 1) for i in range(200)]
    got = practice.pick_screens(samples, cap=10, same=0)
    assert len(got) == 10 and got[0] == 0


def test_the_frames_are_tagged_with_their_lecture(tmp_path):
    """frames_5 는 과목이 달라도 같은 이름이다 — 꼬리표로 가린다."""
    practice.write_stamp(tmp_path, "오픈소스기반데이터분석", 5)
    st = practice.read_stamp(tmp_path)
    assert practice.stamp_matches(st, "오픈소스기반데이터분석", 5)
    assert not practice.stamp_matches(st, "C프로그래밍", 5)
    practice.clear_stamp(tmp_path)
    assert practice.read_stamp(tmp_path) is None


# --- 지시문 ------------------------------------------------------------------
def test_the_prompt_asks_for_the_whole_lecture():
    p = summarize.build_prompt("오픈소스기반데이터분석", 5, "데이터의 저장",
                               duration=57 * 60)
    assert "약 **57분**" in p and "처음부터 끝까지" in p


def test_the_prompt_asks_for_practice_with_finished_code():
    p = summarize.build_prompt("자료구조", 3, "연결 리스트")
    assert "## 실습" in p and "완성 코드" in p


def test_the_notebook_and_screens_are_explained_only_when_given():
    plain = summarize.build_prompt("오픈소스기반데이터분석", 5, "데이터의 저장")
    assert "실습 노트북" not in plain and "화면 사진" not in plain
    full = summarize.build_prompt("오픈소스기반데이터분석", 5, "데이터의 저장",
                                  notebook=True, screens=True)
    assert "실습 노트북" in full and "화면 사진" in full


def test_without_audio_the_practice_rules_are_left_out():
    """음성이 없으면 시각도 실습 순서도 근거가 없다."""
    p = summarize.build_prompt("AI네이티브", 1, "개요", has_audio=False,
                               duration=3000, notebook=True, screens=True)
    assert "처음부터 끝까지" not in p and "화면 사진" not in p


# --- 화면에서 옮겨 온 인증키 가리기 ------------------------------------------
# 실측: 5강 실습 화면의 공공데이터포털 인증키가 노트에 그대로 옮겨졌다.
def test_an_api_key_copied_from_the_screen_is_masked():
    md = "api_key = 'a3ERY4puvBYW5LWLhAQgRqnq'  # 개인 인증키"
    assert summarize.mask_secrets(md) == \
        "api_key = '[발급받은 인증키]'  # 개인 인증키"


def test_a_key_inside_a_dict_is_masked():
    md = "params = {'serviceKey': 'XyZ123456789abcdef=='}"
    assert "XyZ123" not in summarize.mask_secrets(md)


def test_a_reference_or_short_value_is_left_alone():
    for md in ("params = {'serviceKey': api_key}", 'token: "short"',
               'monkey = "bananabananabanana"',
               "api_key = '[발급받은 인증키]'"):
        assert summarize.mask_secrets(md) == md


def test_saved_notes_never_keep_the_key(tmp_path):
    summarize.save_summary("# 5강\n```python\napi_key = 'a3ERY4puvBYW5LWLhAQg'\n```",
                           tmp_path, "오픈소스기반데이터분석", 5, "데이터의 저장")
    saved = next(tmp_path.glob("*.md")).read_text(encoding="utf-8")
    assert "a3ERY" not in saved and "[발급받은 인증키]" in saved


def test_an_empty_note_never_overwrites_a_good_one(tmp_path):
    """빈 응답으로 멀쩡한 노트를 덮으면 되돌릴 수 없다."""
    import pytest
    good = tmp_path / "오픈소스기반데이터분석 5강 - 데이터의 저장.md"
    good.write_text("# 멀쩡한 노트", encoding="utf-8")
    with pytest.raises(ValueError):
        summarize.save_summary("  \n", tmp_path, "오픈소스기반데이터분석", 5,
                               "데이터의 저장")
    assert good.read_text(encoding="utf-8") == "# 멀쩡한 노트"


# --- 덜 쓴 노트 다시 쓰기 ------------------------------------------------------
# 실측: 붐빌 때 flash-lite 가 2강 69분을 35분까지 3천 자로 썼다.
def test_coverage_is_the_last_marker_over_the_audio():
    md = "### a\n🎬 [00:10:00]\n### b\n🎬 [00:35:00]"
    assert round(summarize.note_coverage(md, 70 * 60), 2) == 0.5
    assert summarize.note_coverage(md, None) is None
    assert summarize.note_coverage("마커 없음", 600) == 0.0


def test_the_light_models_are_the_lite_ones():
    lite = summarize.light_models()
    assert lite and all("lite" in m for m in lite)


def test_excluded_models_are_skipped():
    tried = []

    class _Models:
        def generate_content(self, model, contents, config):
            tried.append(model)
            return "ok"

    class _Client:
        models = _Models()
    summarize.generate(_Client(), ["x"], exclude=summarize.model_chain()[:1])
    assert tried == [summarize.model_chain()[1]]


def test_a_thin_note_is_written_again_without_the_light_model(monkeypatch,
                                                              tmp_path):
    """덜 쓴 노트가 오면 가벼운 모델을 빼고 다시 쓰고, 더 많이 다룬 쪽을 고른다."""
    thin = "# 2강\n### a\n🎬 [00:10:00]"
    full = "# 2강\n### a\n🎬 [00:10:00]\n### b\n🎬 [01:05:00]"
    calls = []

    def fake_generate(client, contents, config=None, model=None,
                      on_event=None, wait=0, rounds=0, exclude=()):
        calls.append(tuple(exclude))
        return thin if len(calls) == 1 else full
    monkeypatch.setattr(summarize, "generate", fake_generate)
    monkeypatch.setattr(summarize, "_resp_text", lambda r: r)
    monkeypatch.setattr(summarize, "upload_and_wait",
                        lambda client, path, on_event=None: "uploaded")
    mp3 = tmp_path / "2강.mp3"
    mp3.write_bytes(b"ID3")
    md = summarize.summarize_lecture(object(), "오픈소스기반데이터분석", 2,
                                     "파이썬 1", mp3_path=mp3,
                                     duration=69 * 60)
    assert md == full
    assert calls[1] and all("lite" in m for m in calls[1])


def test_a_doubled_heading_mark_is_tidied():
    """모델이 지시문의 '## 실습' 을 글자 그대로 제목에 붙여 썼다."""
    md = "## ## 실습: 파이썬 1\n### 2-1 리스트\n```python\n## 주석은 그대로\n```"
    out = summarize.tidy_headings(md)
    assert out.startswith("## 실습: 파이썬 1\n")
    assert "## 주석은 그대로" in out
