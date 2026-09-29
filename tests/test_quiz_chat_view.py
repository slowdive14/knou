"""되묻기 화면 — 해설을 읽고도 막히면 그 자리에서 묻는다.

해설은 한 번에 한 편만 쓰인다. '왜 20 이 되는지' 가 걸리는 사람도 있고 '이
보기는 왜 틀렸는지' 가 걸리는 사람도 있다. 물음과 답은 은행 JSON 에 남아
같은 문항을 다시 열면 그대로 보인다.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import flet as ft  # noqa: E402

import quiz_chat as qc  # noqa: E402
from app.views import quiz_view  # noqa: E402
from app.views.quiz_view import build_quiz_view  # noqa: E402

EXPL = "a 는 10 에 2 를 곱해 20 이 됩니다."


def _q(**over):
    d = {"qid": "2019-1-07", "source": "기출", "question": "올바른 것은?",
         "code": "int a = 10, b = 3;\na *= (b - 1);",
         "options": [{"no": 1, "text": "a = 20"}, {"no": 2, "text": "a = 30"}],
         "answer_no": 1, "answer_text": "a = 20", "explanation": EXPL}
    d.update(over)
    return d


def _dir(tmp_path, *questions, course="C프로그래밍", seq=20191):
    d = tmp_path / "퀴즈"
    d.mkdir(exist_ok=True)
    (d / "b.json").write_text(json.dumps(
        {"course": course, "seq": seq, "name": "2019학년도 1학기 기말시험",
         "exam": True, "questions": list(questions)}, ensure_ascii=False),
        encoding="utf-8")
    return d


def _walk(c):
    yield c
    for k in (getattr(c, "controls", None) or []):
        yield from _walk(k)
    inner = getattr(c, "content", None)
    if inner is not None and not isinstance(inner, (str, bytes)):
        yield from _walk(inner)


def _texts(view) -> list:
    return [str(t.value or "") for t in _walk(view) if isinstance(t, ft.Text)]


def _text_buttons(view) -> dict:
    return {str(b.content): b for b in _walk(view)
            if isinstance(b, ft.TextButton)}


def _fields(view) -> list:
    return [f for f in _walk(view) if isinstance(f, ft.TextField)]


def _reveal(view):
    """[정답 보기] 를 눌러 정답 상자를 연다."""
    _text_buttons(view)["정답 보기"].on_click(None)


def _open_chat(view):
    _text_buttons(view)["이해가 안 되면 물어보기"].on_click(None)


def _type(view, text):
    """입력창에 글을 친다(화면은 값을 들고 있지 않고 상태에 담는다)."""
    fld = _fields(view)[0]
    fld.value = text
    fld.on_change(type("E", (), {"control": fld})())


def _send(view):
    """보내기 아이콘을 누른다."""
    for b in _walk(view):
        if isinstance(b, ft.IconButton) and b.icon == ft.Icons.SEND:
            b.on_click(None)
            return
    raise AssertionError("보내기 단추가 없습니다")


class _Now:
    """워커 스레드 대신 그 자리에서 돌린다 — 테스트가 기다리지 않게."""

    def __init__(self, target=None, daemon=None, **_kw):
        self._target = target

    def start(self):
        self._target()


def _wire(monkeypatch, answer="10 에 2 를 곱해서입니다.", seen=None):
    """모델을 가짜로 바꾼다 — 테스트가 실제 API 를 부르지 않게."""
    monkeypatch.setattr(quiz_view.threading, "Thread", _Now)
    monkeypatch.setattr(quiz_view, "gemini_client", lambda: object())

    def fake_ask(_client, q, course="", turns=None, question="", model=None):
        if seen is not None:
            seen.append({"course": course, "turns": list(turns or []),
                         "question": question, "qid": q.get("qid")})
        return answer

    monkeypatch.setattr(qc, "ask", fake_ask)


# --- 입구가 어디에 있는가 ----------------------------------------------------
def test_the_question_is_not_asked_before_the_answer_is_open(tmp_path):
    """정답을 열기 전에는 되묻기 입구도 없다 — 먼저 풀어 볼 값어치를 지킨다."""
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    assert "이해가 안 되면 물어보기" not in _text_buttons(v)


def test_an_explained_question_offers_a_way_to_ask(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    assert EXPL in _texts(v)
    assert "이해가 안 되면 물어보기" in _text_buttons(v)


def test_a_question_without_an_explanation_yet_does_not_offer_it(tmp_path):
    """아직 읽지도 않은 해설을 두고 물어볼 수는 없다."""
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q(explanation="")))
    _reveal(v)
    assert "왜 이게 정답인지 설명 보기" in _text_buttons(v)
    assert "이해가 안 되면 물어보기" not in _text_buttons(v)


def test_a_question_with_no_answer_table_can_still_be_asked(tmp_path):
    """정답을 몰라 해설을 못 만드는 문항은 물어볼 데가 여기뿐이다."""
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q(
        answer_no=0, answer_text="", explanation="")))
    _reveal(v)
    assert "정답을 몰라 설명을 만들 수 없습니다." in _texts(v)
    assert "이해가 안 되면 물어보기" in _text_buttons(v)


# --- 묻고 답 받기 -----------------------------------------------------------
def test_pressing_ask_opens_an_input_box(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    assert not _fields(v)
    _open_chat(v)
    assert _fields(v), "물어보기를 눌렀는데 입력창이 열리지 않았습니다"


def test_asking_shows_both_the_question_and_the_answer(tmp_path, monkeypatch):
    _wire(monkeypatch)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    said = _texts(v)
    assert "왜 20 인가요?" in said
    assert "10 에 2 를 곱해서입니다." in said


def test_the_answer_is_kept_in_the_bank(tmp_path, monkeypatch):
    """같은 문항을 다시 열면 지난 대화가 그대로 보여야 한다."""
    _wire(monkeypatch)
    d = _dir(tmp_path, _q())
    v = build_quiz_view(quiz_dir=d)
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    data = json.loads((d / "b.json").read_text(encoding="utf-8"))
    assert data["questions"][0]["chat"] == [
        {"role": "user", "text": "왜 20 인가요?"},
        {"role": "model", "text": "10 에 2 를 곱해서입니다."}]


def test_a_stored_talk_is_announced_on_the_card(tmp_path):
    """오간 말이 있다는 것은 카드에서 바로 보여야 한다."""
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q(chat=[
        {"role": "user", "text": "왜 20 인가요?"},
        {"role": "model", "text": "10 에 2 를 곱해서입니다."}])))
    _reveal(v)
    assert "물어본 것 2마디 — 옆에서 이어가기" in _text_buttons(v)


def test_opening_the_panel_brings_the_stored_talk_back(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q(chat=[
        {"role": "user", "text": "왜 20 인가요?"},
        {"role": "model", "text": "10 에 2 를 곱해서입니다."}])))
    _reveal(v)
    _text_buttons(v)["물어본 것 2마디 — 옆에서 이어가기"].on_click(None)
    said = _texts(v)
    assert "왜 20 인가요?" in said and "10 에 2 를 곱해서입니다." in said
    assert _fields(v), "이어서 물을 수 있어야 합니다"


def test_the_model_gets_the_question_and_the_course(tmp_path, monkeypatch):
    seen = []
    _wire(monkeypatch, seen=seen)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    assert seen[0]["question"] == "왜 20 인가요?"
    assert seen[0]["course"] == "C프로그래밍"
    assert seen[0]["qid"] == "2019-1-07"
    assert seen[0]["turns"] == []          # 첫 물음에는 지난 대화가 없다


def test_the_second_question_carries_the_earlier_talk(tmp_path, monkeypatch):
    seen = []
    _wire(monkeypatch, seen=seen)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    _type(v, "그럼 b 는요?")
    _send(v)
    assert [t["text"] for t in seen[1]["turns"]] == [
        "왜 20 인가요?", "10 에 2 를 곱해서입니다."]
    assert seen[1]["question"] == "그럼 b 는요?"   # 방금 물음은 겹쳐 담지 않는다


def test_an_empty_box_sends_nothing(tmp_path, monkeypatch):
    """빈 칸으로 보내기를 눌러도 돈을 쓰지 않는다."""
    seen = []
    _wire(monkeypatch, seen=seen)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "   ")
    _send(v)
    assert seen == []


def test_the_box_is_empty_again_after_sending(tmp_path, monkeypatch):
    """보낸 물음이 입력창에 남아 있으면 두 번 보내게 된다."""
    _wire(monkeypatch)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    assert not str(_fields(v)[0].value or "").strip()


def test_a_failed_answer_says_so_and_is_not_stored(tmp_path, monkeypatch):
    """답을 못 받았는데 조용하면 보낸 건지 아닌지 알 수 없다."""
    _wire(monkeypatch, answer="")
    d = _dir(tmp_path, _q())
    v = build_quiz_view(quiz_dir=d)
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    assert any("다시 물어봐 주세요" in t for t in _texts(v))
    data = json.loads((d / "b.json").read_text(encoding="utf-8"))
    assert "chat" not in data["questions"][0]


def test_asking_without_a_key_does_not_break_the_screen(tmp_path, monkeypatch):
    """API 키가 없어도 퀴즈는 계속 풀 수 있어야 한다."""
    monkeypatch.setattr(quiz_view.threading, "Thread", _Now)
    monkeypatch.setattr(quiz_view, "gemini_client", lambda: None)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    assert "왜 20 인가요?" in _texts(v)
    assert any("다시 물어봐 주세요" in t for t in _texts(v))


# --- 모아보기 중에도 제자리에 남는다 -----------------------------------------
def test_a_talk_from_a_gathered_view_lands_in_the_real_bank(tmp_path,
                                                            monkeypatch):
    """모아보기 중에는 지금 은행이 가상이다 — 원래 은행 파일에 써야 남는다."""
    _wire(monkeypatch)
    d = tmp_path / "퀴즈"
    d.mkdir()
    for seq, qid in ((20191, "a"), (20192, "b")):
        (d / f"{seq}.json").write_text(json.dumps(
            {"course": "C프로그래밍", "seq": seq, "name": str(seq),
             "exam": True,
             "questions": [_q(qid=qid, lecture=3)]}, ensure_ascii=False),
            encoding="utf-8")
    v = build_quiz_view(quiz_dir=d)
    picks = [p for p in _walk(v) if isinstance(p, ft.Dropdown)
             and p.label == "강 모아보기"]
    picks[0].value = "3"
    picks[0].on_select(None)
    assert _texts(v).count("올바른 것은?") == 2, "두 회차가 한 자리에 모여야 합니다"
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    got = [json.loads((d / f"{s}.json").read_text(encoding="utf-8"))
           ["questions"][0].get("chat") for s in (20191, 20192)]
    assert sum(1 for g in got if g) == 1, "한쪽 은행에만 남아야 합니다"


# --- 오른쪽 붙박이 판 -------------------------------------------------------
# 대화가 문항 아래로 쌓이면 문제를 보려고 위아래로 오르내리게 된다.
def _panel(view):
    """오른쪽 판(찾지 못하면 None)."""
    for c in _walk(view):
        if isinstance(c, ft.Container) and c.width == quiz_view.CHAT_WIDTH:
            return c
    return None


def test_a_wide_window_uses_the_side_panel():
    assert quiz_view.side_chat(1400)
    assert not quiz_view.side_chat(900)


def test_an_unknown_width_counts_as_wide():
    """폭을 모르면(테스트·앱 밖) 넓은 것으로 본다."""
    assert quiz_view.side_chat(None)
    assert quiz_view.side_chat("몰라")


def test_the_panel_head_names_the_question():
    q = _q(question="즉치 주소지정방식과 직접 주소지정방식을 이용한다면?")
    assert quiz_view.chat_head(q, 7).startswith("Q07 · 즉치 주소지정방식")


def test_a_long_question_is_cut_in_the_head():
    q = _q(question="가" * 200)
    assert len(quiz_view.chat_head(q, 1)) < 90
    assert quiz_view.chat_head(q, 1).endswith("…")


def test_the_card_link_counts_what_was_said():
    assert quiz_view.chat_link_text(_q()) == "이해가 안 되면 물어보기"
    assert quiz_view.chat_link_text(_q(chat=[
        {"role": "user", "text": "왜?"}])) == "물어본 것 1마디 — 옆에서 이어가기"


def test_the_panel_is_closed_until_it_is_asked_for(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    assert _panel(v) is not None
    assert not _panel(v).visible


def test_pressing_the_link_opens_the_panel(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    assert _panel(v).visible
    assert any("Q01" in t for t in _texts(v))


def test_the_talk_lives_in_the_panel_not_under_the_question(tmp_path,
                                                            monkeypatch):
    """문제는 제자리에 두고 대화만 옆으로 — 그게 이 판의 전부다."""
    _wire(monkeypatch)
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _type(v, "왜 20 인가요?")
    _send(v)
    panel_said = [str(t.value or "") for t in _walk(_panel(v))
                  if isinstance(t, ft.Text)]
    assert "왜 20 인가요?" in panel_said
    assert "10 에 2 를 곱해서입니다." in panel_said


def test_the_panel_can_be_closed(tmp_path):
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    _text_buttons(v)["옆에서 묻는 중 — 판 닫기"].on_click(None)
    assert not _panel(v).visible


def test_changing_the_mode_closes_the_panel(tmp_path):
    """모드를 바꾸면 그 문항이 목록에서 사라질 수 있다 — 판도 닫는다."""
    v = build_quiz_view(quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    assert _panel(v).visible
    for b in _walk(v):
        if isinstance(b, ft.OutlinedButton) and str(b.content) == "오답만":
            b.on_click(None)
            break
    assert not _panel(v).visible


def test_shrinking_the_window_folds_the_panel_back(tmp_path):
    """창을 줄이면 오른쪽 판이 문제를 밀어낸다 — 카드 안으로 되돌린다."""
    class _Page:
        width = 1400

        def update(self):
            pass

    page = _Page()
    v = build_quiz_view(page, quiz_dir=_dir(tmp_path, _q()))
    _reveal(v)
    _open_chat(v)
    assert _panel(v).visible
    page.width = 800
    page.on_resize(None)
    assert not _panel(v).visible
    assert _fields(v), "좁은 창에서는 카드 안에서 물을 수 있어야 합니다"
