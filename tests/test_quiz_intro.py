"""quiz_intro 단위테스트 — 지문이 없으면 문제를 풀 수 없다.

실측 불편: '위 문장의 출력 결과는 무엇인가?' 인데 그 위 문장이 화면에 없었다.
지문은 문항 form 안 `.exam-print` 에 있고, 글일 때도 그림일 때도 있다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import quiz_intro as qi  # noqa: E402

PNG = (b"\x89PNG\r\n\x1a\n" + b"0" * 40)      # 그림 흉내(내용은 보지 않는다)


def _q(qid="121930", question="Q2 위 문장의 출력 결과는 무엇인가?", **over):
    d = {"qid": qid, "source": "형성평가", "question": question,
         "options": [{"no": 1, "text": "가"}], "answer_no": 1,
         "answer_text": "가", "explanation": ""}
    d.update(over)
    return d


def _bank(*qs, course="C프로그래밍", seq=5):
    return {"course": course, "seq": seq, "name": "선택 제어문과 반복 제어문",
            "questions": list(qs)}


def _dir(tmp_path, bank, name="b.json"):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / name).write_text(json.dumps(bank, ensure_ascii=False), encoding="utf-8")
    return d


# --- 코드처럼 생겼는가 -------------------------------------------------------
def test_code_goes_to_the_monospace_box():
    assert qi.looks_like_code('if (a > 3 && --b < 10) printf("true");')
    assert qi.looks_like_code("int a = 10;")
    assert not qi.looks_like_code("다음은 어떤 자료형에 대한 설명이다")
    assert not qi.looks_like_code("") and not qi.looks_like_code(None)


# --- 지문이 있는가 / 있어야 하는가 -------------------------------------------
def test_has_intro_counts_text_code_and_picture():
    assert qi.has_intro(_q(intro="지문입니다"))
    assert qi.has_intro(_q(code="int a;"))
    assert qi.has_intro(_q(intro_image="a.png"))
    assert not qi.has_intro(_q())


def test_needs_intro_spots_a_question_that_points_upward():
    """'위 문장' 을 가리키는데 지문이 없으면 지금은 풀 수 없는 문항이다."""
    assert qi.needs_intro(_q())
    assert qi.needs_intro(_q(question="위 지문과 같이 선언한 배열은?"))
    assert qi.needs_intro(_q(question="다음 프로그램의 실행결과는?"))
    assert not qi.needs_intro(_q(question="다음 중 반복 제어문은?"))
    assert not qi.needs_intro(_q(intro_image="a.png"))   # 이미 있으면 아니다


# --- 담기 -------------------------------------------------------------------
def test_apply_puts_code_in_the_code_box():
    got = qi.apply_intro(_q(), text='if (a > 3) printf("t");')
    assert got["code"] == 'if (a > 3) printf("t");'
    assert not got.get("intro")


def test_apply_puts_prose_in_the_intro_box():
    got = qi.apply_intro(_q(), text="다음은 학생 자료를 나타낸 것이다")
    assert got["intro"] == "다음은 학생 자료를 나타낸 것이다"


def test_apply_records_the_picture():
    got = qi.apply_intro(_q(), image="C프로그래밍_5강_121930.png")
    assert got["intro_image"] == "C프로그래밍_5강_121930.png"


def test_apply_never_overwrites_what_is_there():
    """손으로 채워 둔 지문을 덮으면 되돌릴 수 없다."""
    q = _q(code="원래 코드", intro_image="원래.png")
    got = qi.apply_intro(q, text="int a;", image="새.png")
    assert got["code"] == "원래 코드" and got["intro_image"] == "원래.png"


def test_apply_leaves_the_original_alone():
    q = _q()
    qi.apply_intro(q, text="int a;")
    assert "code" not in q


def test_image_name_keeps_course_and_lecture():
    assert qi.image_name("C프로그래밍", 5, "121930") == \
        "C프로그래밍_5강_121930.png"


# --- 어디가 비었나 -----------------------------------------------------------
def test_missing_lectures_lists_what_cannot_be_solved():
    banks = [_bank(_q(qid="a"), _q(qid="b", question="다음 중 옳은 것은?")),
             _bank(_q(qid="c"), course="자료구조", seq=3)]
    got = qi.missing_lectures(banks)
    assert got == [("C프로그래밍", 5, "선택 제어문과 반복 제어문", ["a"]),
                   ("자료구조", 3, "선택 제어문과 반복 제어문", ["c"])]


def test_missing_lectures_skips_the_exam_banks():
    """기출은 PDF 에서 지문까지 함께 읽어 온다 — 여기서 찾을 것이 없다."""
    b = _bank(_q(qid="a"))
    b["exam"] = {"year": 2019, "term": 1}
    assert qi.missing_lectures([b]) == []


# --- 화면에서 읽기 -----------------------------------------------------------
class _Frame:
    def __init__(self, rows):
        self.rows = rows

    def evaluate(self, _js):
        return json.dumps(self.rows)


class _BadFrame:
    def evaluate(self, _js):
        raise RuntimeError("프레임이 닫힘")


class _Resp:
    def __init__(self, body, status=200):
        self._b, self.status = body, status

    def body(self):
        return self._b


class _Req:
    def __init__(self, body=PNG, status=200):
        self.body_, self.status, self.urls = body, status, []

    def get(self, url):
        self.urls.append(url)
        return _Resp(self.body_, self.status)


def test_scan_reads_text_and_picture_per_question():
    fr = _Frame([{"qid": "1", "text": "int a;", "src": ""},
                 {"qid": "2", "text": "", "src": "https://x/user_uploading?k=1"}])
    got = qi.scan_intros(fr)
    assert got["1"]["text"] == "int a;"
    assert got["2"]["src"].endswith("k=1")


def test_scan_survives_a_closed_frame():
    """지문을 못 읽는다고 이수를 막지 않는다."""
    assert qi.scan_intros(_BadFrame()) == {}


def test_fetch_image_refuses_anything_but_200():
    assert qi.fetch_image(_Req(status=404), "https://x/a") == b""
    assert qi.fetch_image(_Req(), "") == b""


def test_download_fills_questions_and_saves_the_picture(tmp_path):
    d = tmp_path / "퀴즈"
    qs = [_q(qid="1"), _q(qid="2"), _q(qid="3", question="다음 중 옳은 것은?")]
    fr = _Frame([{"qid": "1", "text": "", "src": "https://x/img"},
                 {"qid": "2", "text": "int a = 10;", "src": ""}])
    n = qi.download_intros(fr, qs, d, "C프로그래밍", 5, requester=_Req())
    assert n == 2
    assert qs[0]["intro_image"] == "C프로그래밍_5강_1.png"
    assert (d / "지문" / "C프로그래밍_5강_1.png").read_bytes() == PNG
    assert qs[1]["code"] == "int a = 10;"
    assert not qi.has_intro(qs[2])          # 화면에 지문이 없던 문항은 그대로


def test_download_skips_a_question_that_already_has_one(tmp_path):
    qs = [_q(qid="1", code="원래 코드")]
    fr = _Frame([{"qid": "1", "text": "새 코드;", "src": ""}])
    assert qi.download_intros(fr, qs, tmp_path, "C", 5, requester=_Req()) == 0
    assert qs[0]["code"] == "원래 코드"


# --- 파일에 써넣기 -----------------------------------------------------------
def test_store_writes_the_intro_into_the_bank(tmp_path):
    d = _dir(tmp_path, _bank(_q(qid="a"), _q(qid="b")))
    n = qi.store_intros(d, {"course": "C프로그래밍", "seq": 5},
                        {"a": {"text": "int a;", "image": "a.png"}})
    assert n == 1
    got = json.loads((d / "b.json").read_text(encoding="utf-8"))["questions"]
    assert got[0]["code"] == "int a;" and got[0]["intro_image"] == "a.png"
    assert "code" not in got[1]
    assert not list(d.glob("*.tmp"))        # 임시 파일이 남지 않는다


def test_store_does_nothing_when_there_is_nothing_new(tmp_path):
    d = _dir(tmp_path, _bank(_q(qid="a", code="이미 있음")))
    assert qi.store_intros(d, {"course": "C프로그래밍", "seq": 5},
                           {"a": {"text": "새 코드;", "image": ""}}) == 0


def test_store_says_no_when_the_bank_is_missing(tmp_path):
    d = _dir(tmp_path, _bank(_q(qid="a")))
    assert qi.store_intros(d, {"course": "없는과목", "seq": 1},
                           {"a": {"text": "int a;"}}) == 0


# --- 그림 찾아가기 -----------------------------------------------------------
def test_intro_file_finds_the_picture_in_the_quiz_folder(tmp_path):
    d = tmp_path / "퀴즈"
    qi.save_image(d, "a.png", PNG)
    assert qi.intro_file(_q(intro_image="a.png"), d).name == "a.png"
    assert qi.intro_file(_q(intro_image="없음.png"), d) is None
    assert qi.intro_file(_q(), d) is None


def test_stamp_paths_marks_where_the_picture_is(tmp_path):
    d = tmp_path / "퀴즈"
    qi.save_image(d, "a.png", PNG)
    banks = [_bank(_q(qid="1", intro_image="a.png"), _q(qid="2"))]
    qi.stamp_paths(banks, d)
    assert banks[0]["questions"][0]["intro_path"].endswith("a.png")
    assert "intro_path" not in banks[0]["questions"][1]


def test_data_uri_carries_the_picture(tmp_path):
    d = tmp_path / "퀴즈"
    qi.save_image(d, "a.png", PNG)
    uri = qi.data_uri(d / "지문" / "a.png")
    assert uri.startswith("data:image/png;base64,")
    assert qi.data_uri(tmp_path / "없음.png") == ""


# --- 다시 담아도 지워지지 않는가 ---------------------------------------------
# ⚠️ merge_questions 는 기존 문항도 normalize_question 에 통과시킨다. 거기서
#    지문 칸을 빠뜨리면 같은 차시를 다시 담을 때 채워 둔 지문을 통째로 잃는다.
def test_normalize_keeps_the_intro_and_the_lecture():
    from quizbank import normalize_question
    got = normalize_question(_q(intro="지문", code="int a;",
                               intro_image="a.png", lecture=5))
    assert got["intro"] == "지문" and got["code"] == "int a;"
    assert got["intro_image"] == "a.png" and got["lecture"] == 5


def test_normalize_leaves_the_extras_out_when_empty():
    from quizbank import normalize_question
    got = normalize_question(_q())
    assert "intro" not in got and "lecture" not in got


def test_recapturing_a_lecture_does_not_wipe_the_intro():
    from quizbank import merge_questions
    old = [_q(qid="a", code="int a;", intro_image="a.png", lecture=5)]
    new = [_q(qid="a", explanation="새 해설")]      # 다시 담아 온 것(지문 없음)
    got = merge_questions(old, new)[0]
    assert got["code"] == "int a;" and got["intro_image"] == "a.png"
    assert got["lecture"] == 5 and got["explanation"] == "새 해설"


# --- 화면에 실제로 걸리는가 --------------------------------------------------
import flet as ft  # noqa: E402


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def test_the_app_hangs_the_picture_on_the_card(tmp_path):
    from app.views.quiz_view import build_quiz_view
    d = _dir(tmp_path, _bank(_q(qid="1", intro_image="a.png")))
    qi.save_image(d, "a.png", PNG)
    v = build_quiz_view(quiz_dir=d)
    imgs = [c for c in _walk(v) if isinstance(c, ft.Image)]
    assert len(imgs) == 1 and imgs[0].src.endswith("a.png")


def test_the_app_shows_no_picture_when_the_file_is_gone(tmp_path):
    """볼트가 잠깐 안 보일 때 깨진 그림 자리가 생기면 안 된다."""
    from app.views.quiz_view import build_quiz_view
    d = _dir(tmp_path, _bank(_q(qid="1", intro_image="없음.png")))
    v = build_quiz_view(quiz_dir=d)
    assert [c for c in _walk(v) if isinstance(c, ft.Image)] == []


def test_the_html_page_carries_the_picture_inside_it(tmp_path):
    """한 장짜리 HTML 이라 그림을 본문에 실어 보낸다 — 폴더를 옮겨도 보인다."""
    from quiz_page import build_quiz_page
    d = _dir(tmp_path, _bank(_q(qid="1", intro_image="a.png")))
    qi.save_image(d, "a.png", PNG)
    html = build_quiz_page(d)
    assert 'class="q-intro-img"' in html
    assert "data:image/png;base64," in html


# --- 이수할 때 함께 담기는가 -------------------------------------------------
# 지문을 그때 담지 않으면 나중에 차시마다 플레이어를 다시 열어야 한다.
def test_the_capture_path_asks_for_the_intro():
    import inspect

    import main
    src = inspect.getsource(main)
    assert src.count("download_intros") == 2       # 돌발퀴즈 · 형성평가 둘 다


def test_the_scanner_points_at_who_fetches_the_intro():
    """스캐너만 보고 '지문도 담기겠지' 하고 넘어가지 않게."""
    import quiz_capture
    assert "download_intros" in (quiz_capture.__doc__ or "")


# --- 줄바꿈 -----------------------------------------------------------------
# 실측: 세 줄짜리 코드가 'float x = 1.5f;float *pF;int a = 20;' 한 줄로 담겼고,
# LMS 가 글자 그대로 적어 둔 '<br>' 이 그대로 보였다.
def test_a_literal_br_becomes_a_line_break():
    assert qi.clean_text("int a = 10;<br>a += b++;") == "int a = 10;\na += b++;"
    assert qi.clean_text("a<BR/>b") == "a\nb"


def test_clean_text_drops_empty_lines():
    assert qi.clean_text("  int a;  \n\n\n  int b;  ") == "int a;\nint b;"
    assert qi.clean_text("") == "" and qi.clean_text(None) == ""


def test_apply_uses_the_cleaned_text():
    got = qi.apply_intro(_q(), text="int a = 10;<br>a += b++;")
    assert got["code"] == "int a = 10;\na += b++;"


def test_refill_overwrites_a_badly_read_intro():
    """읽는 방법을 고쳤으면 예전에 뭉개 담은 지문을 바로잡을 수 있어야 한다."""
    got = qi.apply_intro(_q(code="int a;int b;"), text="int a;\nint b;",
                         force=True)
    assert got["code"] == "int a;\nint b;"


def test_refill_is_off_by_default():
    assert qi.apply_intro(_q(code="손으로 고친 코드"),
                          text="int a;")["code"] == "손으로 고친 코드"


def test_store_can_refill(tmp_path):
    d = _dir(tmp_path, _bank(_q(qid="a", code="int a;int b;")))
    n = qi.store_intros(d, {"course": "C프로그래밍", "seq": 5},
                        {"a": {"text": "int a;\nint b;"}}, force=True)
    assert n == 1
    got = json.loads((d / "b.json").read_text(encoding="utf-8"))["questions"]
    assert got[0]["code"] == "int a;\nint b;"


def test_the_scanner_keeps_line_breaks():
    """화면에서 읽을 때부터 줄을 살린다(<br> 과 </p> 를 줄로 바꾼다)."""
    assert "<br" in qi.INTRO_SCAN_JS and "&lt;br" in qi.INTRO_SCAN_JS
    assert "innerHTML" in qi.INTRO_SCAN_JS


# --- 어느 차시를 찾아갈 것인가 -----------------------------------------------
def test_refill_targets_the_lectures_that_were_filled():
    """읽는 방법을 고친 뒤에는 **이미 담은 차시**를 다시 찾아가야 한다."""
    from fetch_intros import targets
    banks = [_bank(_q(qid="a", code="이미 담김")),
             _bank(_q(qid="b", question="다음 중 옳은 것은?"), seq=6)]
    assert [r[1] for r in targets(banks, refill=True)] == [5]
    assert targets(banks) == []              # 평소에는 갈 곳이 없다
    assert [r[1] for r in targets(banks, every=True)] == [5, 6]
