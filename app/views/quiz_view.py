"""[quiz_view] 강의 퀴즈 — 앱 안에서 푸는 복습 화면.

생성 HTML(quiz_html)과 같은 내용을 Flet 컨트롤로 직접 그린다 → 브라우저를 따로
띄우지 않고 앱 창에서 바로 푼다. 보기를 고르면 정답/오답 색이 붙고, [정답 보기]를
눌러야 정답·해설이 열린다(다시 풀어보기 가치 보존).

  - 강의 고르기(드롭다운) · 진행률 · 현재 강/전체 초기화
  - 'N강 모아보기' — 회차가 달라도 그 강의 문항을 한 자리에 모은다
  - 풀이 기록은 앱이 켜져 있는 동안 유지(HTML 페이지는 브라우저에 저장)

데이터는 quiz_page.collect_banks(볼트/퀴즈) 를 그대로 쓴다(로그인·네트워크 없음).
"""
from __future__ import annotations

import threading

import flet as ft

import quiz_explain as qe
import quiz_intro as qi
import quiz_lecture as ql
import quiz_progress as qp
from quiz_page import collect_banks, default_quiz_paths
from quizbank import correct_nos, is_correct
from ui_async import make_updater

MINT = "#00a37a"
MINT_BG = "#e3f6ef"
ROSE = "#c8452f"
ROSE_BG = "#fbe9e5"
MUTE = "#8b9198"

# 해설이 길면 문제·코드가 화면 밖으로 밀려 스크롤을 오르내리게 된다. 그래서
# 긴 해설은 **자기 상자 안에서만** 굴리고, 문제와 코드는 제자리에 남긴다.
EXPLAIN_SCROLL_CHARS = 350     # 이보다 길면 상자에 가둔다
EXPLAIN_BOX_HEIGHT = 320       # 상자 높이(px)

# 지문 그림 폭(px) — 예습 노트에 넣는 그림과 같은 폭으로 맞춘다.
INTRO_IMAGE_WIDTH = 695


def explanation_scrolls(text) -> bool:
    """이 해설은 자기 상자 안에서 굴려야 하는가.

    짧은 해설(형성평가는 중앙값이 136자다)까지 상자에 가두면 빈 여백만
    생긴다 — 긴 것만 가둔다.
    """
    return len(str(text or "").strip()) > EXPLAIN_SCROLL_CHARS


# ---------------------------------------------------------------------------
# 순수 조각 (오프라인 테스트 가능)
# ---------------------------------------------------------------------------
def bank_title(bank: dict) -> str:
    """드롭다운 표시문구.

    강의 퀴즈: 'C프로그래밍 · 1강 · C 언어의 개요'
    기출:      'C프로그래밍 · 📄 기출 · 2019학년도 1학기 기말시험'
    모아보기:  'C프로그래밍 · 🎯 3강 모아보기 · 입.출력 함수와 연산자(1)'

    기출은 차시가 없으므로 'N강' 을 붙이면 엉뚱한 번호가 나온다(seq 는 정렬용
    으로 20191 같은 값을 쓴다) — `exam` 이 있으면 그쪽 표기를 따른다.
    """
    course = bank.get("course") or ""
    if bank.get("lecture_pick"):
        n = ql.lecture_label(bank.get("lecture_pick"))
        head = " · ".join(p for p in (f"🎯 {n} 모아보기", bank.get("name") or "")
                          if p)
    elif bank.get("exam"):
        head = " · ".join(p for p in ("📄 기출", bank.get("name") or "") if p)
    else:
        parts = [str(bank.get("seq", "")) + "강", bank.get("name") or ""]
        head = " · ".join(p for p in parts if p)
    return f"{course} · {head}" if course else head


def bank_index(banks, course: str | None, seq=None) -> int:
    """과목·차시로 은행 위치 찾기(못 찾으면 0)."""
    if course is None and seq is None:
        return 0
    for i, b in enumerate(banks or []):
        if (course is None or b.get("course") == course) and \
                (seq is None or int(b.get("seq") or 0) == int(seq)):
            return i
    return 0


def lecture_chip(q) -> list:
    """문항 머리에 붙는 '3강' 표지 — 아직 안 가린 문항에는 붙이지 않는다."""
    lab = ql.lecture_label(ql.lecture_no(q))
    if not lab:
        return []
    return [ft.Container(
        content=ft.Text(lab, size=11, weight=ft.FontWeight.BOLD, color=MINT),
        bgcolor=MINT_BG, padding=ft.Padding(9, 2, 9, 2), border_radius=99)]


def progress_text(answered: int, total: int) -> str:
    return f"{int(answered)} / {int(total)}"


def option_tone(sel, no, answer_no, answer_nos=None) -> str:
    """보기 하나의 색: correct|wrong|selected|plain.

    ⚠️ 정답을 **모르는** 문항(정답표에 대조표에도 없는 표기가 있던 자리)은
       무엇을 골라도 오답이 아니다 — 빨간색으로 칠하면 틀렸다고 오해한다.
    ⚠️ 중복정답이면 그중 아무거나 골라도 맞다.
    """
    if sel is None or str(sel) != str(no):
        return "plain"
    nos = correct_nos({"answer_no": answer_no, "answer_nos": answer_nos})
    if not nos:
        return "selected"           # 정답을 모른다 — 채점하지 않는다
    try:
        return "correct" if int(sel) in nos else "wrong"
    except (TypeError, ValueError):
        return "selected"


def answer_text(q: dict) -> str:
    """정답 줄 문구 — 번호와 보기글이 있으면 함께.

    중복정답이면 번호를 모두 적는다. '정답: 1번' 만 보이면 4를 고르고 맞힌
    사람이 자기가 틀린 줄 안다.
    """
    nos = correct_nos(q)
    txt = q.get("answer_text")
    if not nos:
        return f"정답: {txt}" if txt else "정답 정보 없음"
    opts = {int(o.get("no") or 0): str(o.get("text") or "")
            for o in (q.get("options") or [])}
    if len(nos) == 1:
        return f"정답: {nos[0]}. {opts.get(nos[0]) or txt or ''}".strip()
    body = " · ".join(f"{n}. {opts.get(n, '')}".strip() for n in nos)
    return f"정답(중복정답): {body}"


# ---------------------------------------------------------------------------
# 화면 (Flet — 수동 스모크)
# ---------------------------------------------------------------------------
def build_quiz_view(page=None, quiz_dir=None, initial=None) -> ft.Control:
    """퀴즈 화면. initial=(과목, 차시) 를 주면 그 강의부터 연다."""
    if quiz_dir is None:
        try:
            from config import load_config
            quiz_dir = default_quiz_paths(load_config())[0]
        except Exception:  # noqa: BLE001 - 설정 전이면 빈 화면으로
            quiz_dir = None

    banks = collect_banks(quiz_dir) if quiz_dir else []
    # 풀이 기록은 **파일에 남긴다** — 예전에는 화면 메모리에만 있어서 앱을 끄면
    # 무엇을 틀렸는지 사라졌고, 그래서 '틀린 것부터 다시' 가 불가능했다.
    prog_path = qp.progress_path(quiz_dir) if quiz_dir else None
    st = {"idx": bank_index(banks, *(initial or (None, None))),
          "answers": {}, "revealed": set(),
          "prog": qp.load(prog_path) if prog_path else {},
          "mode": "all", "order": [], "busy": None,
          "lec": 0, "virtual": {}}

    title = ft.Text("강의 퀴즈", size=26, weight=ft.FontWeight.BOLD)
    sub = ft.Text("", size=13, color=MUTE)
    prog = ft.Text("0 / 0", size=22, weight=ft.FontWeight.BOLD,
                   font_family="Consolas")
    bar = ft.ProgressBar(value=0, height=4, color=MINT,
                         bgcolor=ft.Colors.with_opacity(.08, ft.Colors.ON_SURFACE))
    cards = ft.Column(spacing=12, expand=True, scroll=ft.ScrollMode.AUTO)
    picker = ft.Dropdown(label="강의", width=400, options=[])
    # 회차를 가로질러 '3강 문제만' 모아 보는 손잡이. 방금 들은 강의의 기출을
    # 곧바로 풀어보려면 회차별 은행을 25문항씩 훑어야 했다.
    lec_pick = ft.Dropdown(label="강 모아보기", width=150, options=[],
                           tooltip="기출·변형·강의 퀴즈에서 그 강의 문항만 모읍니다")

    # 해설 생성은 워커 스레드에서 돈다. 거기서 page.update() 를 직접 부르면
    # 패치가 큐에만 쌓여 화면이 안 바뀐다(ui_async 설명 참고).
    _upd = make_updater(page)

    def _safe_update():
        _upd()

    def _explain(q):
        """[설명 보기] — 처음 한 번만 만들고, 만든 것은 은행에 저장한다.

        API 호출이 몇 초 걸리므로 **워커 스레드**에서 돌린다. 화면 갱신은
        루프를 깨우는 통로로 보낸다(ui_async 설명 참고).
        """
        qid = q.get("qid")
        if st["busy"] or qe.has_explanation(q):
            return
        st["busy"] = qid
        _render_cards()

        def work():
            text = ""
            try:
                from google import genai

                from config import load_config
                cfg = load_config()
                client = genai.Client(api_key=cfg.gemini_api_key)
                text = qe.make_explanation(client, q,
                                           q.get("course") or _cur_bank().get(
                                               "course") or "")
            except Exception:  # noqa: BLE001 - 설명이 없다고 퀴즈를 막지 않는다
                text = ""
            if text:
                q["explanation"] = text          # 지금 화면에 곧바로
                if quiz_dir:
                    # 모아보기 중이면 지금 은행은 가상이다 — 해설은 **문항이
                    # 원래 있던 은행 파일**에 써야 다음에도 남아 있다.
                    qe.store_explanation(quiz_dir, ql.origin_bank(q, _cur_bank()),
                                         qid, text)
            else:
                q["explanation"] = "설명을 만들지 못했습니다. 잠시 뒤 다시 눌러 주세요."
            st["busy"] = None
            _render_cards()

        threading.Thread(target=work, daemon=True).start()

    def _save_progress():
        """기록을 파일에 남긴다 — 실패해도 풀이를 막지 않는다."""
        if prog_path is None:
            return
        try:
            qp.save(prog_path, st["prog"])
        except Exception:  # noqa: BLE001 - 볼트가 잠깐 안 보일 수 있다
            pass

    def _real_bank() -> dict:
        """드롭다운에서 고른 진짜 은행(모아보기 중에도 과목은 여기서 읽는다)."""
        return banks[st["idx"]] if 0 <= st["idx"] < len(banks) else {}

    def _cur_bank() -> dict:
        """지금 화면에 올라온 은행 — 모아보기 중이면 그 가상 은행."""
        return st["virtual"] if st["lec"] else _real_bank()

    def _all_questions() -> list:
        return _cur_bank().get("questions") or []

    def _questions() -> list:
        """지금 화면에 낼 문항 — 모드로 거르고 **틀린 것부터** 정렬한다."""
        return st["order"]

    def _reorder():
        st["order"] = qp.pick(_all_questions(), st["prog"], _cur_bank(),
                              st["mode"])

    def _refresh_progress():
        qs = _questions()
        done = sum(1 for q in qs if st["answers"].get(q.get("qid")) is not None)
        prog.value = progress_text(done, len(qs))
        bar.value = (done / len(qs)) if qs else 0
        _safe_update()

    def _option_button(q: dict, o: dict) -> ft.Control:
        qid = q.get("qid")
        no = o.get("no")
        tone = option_tone(st["answers"].get(qid), no, q.get("answer_no"),
                           q.get("answer_nos"))
        border, bg = {
            "correct": (MINT, MINT_BG),
            "wrong": (ROSE, ROSE_BG),
            "selected": (MINT, MINT_BG),
        }.get(tone, (ft.Colors.with_opacity(.14, ft.Colors.ON_SURFACE), None))
        badge_bg = {"correct": MINT, "wrong": ROSE}.get(tone)

        def choose(_):
            if st["answers"].get(qid) is not None:
                return                      # 이미 고른 문항은 기록을 덮지 않는다
            st["answers"][qid] = no
            if correct_nos(q):              # 정답을 모르는 문항은 채점하지 않는다
                key = qp.key_for(_cur_bank(), q)
                st["prog"][key] = qp.mark(st["prog"].get(key),
                                          is_correct(q, no))
                _save_progress()
            _render_cards()
            _refresh_progress()

        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Text(str(no), size=11,
                                        weight=ft.FontWeight.BOLD,
                                        color="#ffffff" if badge_bg else None),
                        width=24, height=24, border_radius=99,
                        alignment=ft.Alignment.CENTER,
                        bgcolor=badge_bg or ft.Colors.with_opacity(
                            .08, ft.Colors.ON_SURFACE)),
                    ft.Text(str(o.get("text") or ""), size=14, expand=True),
                ],
                spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            on_click=choose, ink=True,
            padding=ft.Padding(13, 11, 13, 11), border_radius=10, bgcolor=bg,
            border=ft.Border.all(1.4, border),
        )

    def _card(num: int, q: dict) -> ft.Control:
        qid = q.get("qid")
        opened = qid in st["revealed"]

        def toggle(_):
            if opened:
                st["revealed"].discard(qid)
            else:
                st["revealed"].add(qid)
            _render_cards()

        # 모아보기 중에는 이 문항이 어느 회차에서 왔는지도 알려준다
        # ('2019 기출' 인지 '형성평가' 인지에 따라 무게가 다르다).
        head = [ft.Text(f"Q{num:02d}", size=13, weight=ft.FontWeight.BOLD,
                        color=MINT, font_family="Consolas", expand=True)]
        head += lecture_chip(q)
        if st["lec"] and q.get("bank_name"):
            head.append(ft.Text(str(q.get("bank_name")), size=11, color=MUTE))
        head.append(ft.Text(str(q.get("source") or ""), size=11, color=MUTE))
        items = [ft.Row(head, spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER)]
        # ⚠️ 여러 문항이 함께 쓰는 지문과 코드를 **반드시** 보여준다. 이게 없으면
        # '다음 프로그램의 실행결과는?' 같은 문항을 아예 풀 수 없다.
        # 형성평가 지문은 코드가 **그림**인 경우가 있다 — 글자로 옮기면 한 글자만
        # 어긋나도 정답이 달라지므로 화면에 있던 그림 그대로 건다.
        img = qi.intro_file(q, quiz_dir)
        if img is not None:
            items.append(ft.Container(
                # ⚠️ Flet 0.85 에는 ImageFit 이 없다 — BoxFit 이다.
                content=ft.Image(src=str(img), width=INTRO_IMAGE_WIDTH,
                                 fit=ft.BoxFit.CONTAIN),
                bgcolor="#ffffff", padding=8, border_radius=8,
                border=ft.Border.all(1, ft.Colors.with_opacity(
                    .10, ft.Colors.ON_SURFACE))))
        intro = str(q.get("intro") or "").strip()
        if intro:
            items.append(ft.Container(
                content=ft.Text(intro, size=13, color=MUTE, selectable=True),
                bgcolor=ft.Colors.with_opacity(.04, ft.Colors.ON_SURFACE),
                padding=12, border_radius=8))
        items.append(ft.Text(str(q.get("question") or ""), size=15,
                             weight=ft.FontWeight.BOLD))
        code = str(q.get("code") or "").strip()
        if code:
            items.append(ft.Container(
                content=ft.Text(code, size=13, font_family="Consolas",
                                selectable=True),
                bgcolor=ft.Colors.with_opacity(.06, ft.Colors.ON_SURFACE),
                padding=12, border_radius=8,
                border=ft.Border.all(1, ft.Colors.with_opacity(
                    .10, ft.Colors.ON_SURFACE))))
        # 코드가 있는데 실행으로 확인하지 못한 변형은 그 사실을 알린다
        if code and q.get("source") == "기출변형" and not q.get("verified"):
            items.append(ft.Text("⚠️ 실행으로 확인하지 못한 문제입니다", size=11,
                                 color=ROSE))
        items += [_option_button(q, o) for o in (q.get("options") or [])]
        items.append(ft.TextButton(
            "정답 숨기기" if opened else "정답 보기",
            icon=ft.Icons.VISIBILITY_OFF if opened else ft.Icons.VISIBILITY,
            on_click=toggle, style=ft.ButtonStyle(color=MINT)))
        if opened:
            box = [ft.Text(answer_text(q), size=13,
                           weight=ft.FontWeight.BOLD, color=MINT)]
            expl = str(q.get("explanation") or "").strip()
            if expl and explanation_scrolls(expl):
                # 긴 해설은 상자 안에서만 굴린다 — 위의 문제·코드가 밀려나지
                # 않아 읽으면서 바로 대조할 수 있다.
                box.append(ft.Container(
                    content=ft.Column(
                        [ft.Text(expl, size=13, selectable=True)],
                        scroll=ft.ScrollMode.AUTO, tight=True, spacing=0),
                    height=EXPLAIN_BOX_HEIGHT))
            elif expl:
                box.append(ft.Text(expl, size=13, selectable=True))
            elif st["busy"] == qid:
                box.append(ft.Row([ft.ProgressRing(width=15, height=15,
                                                   stroke_width=2),
                                   ft.Text("설명을 만드는 중…", size=12,
                                           color=MUTE)], spacing=8))
            elif not correct_nos(q):
                box.append(ft.Text("정답을 몰라 설명을 만들 수 없습니다.",
                                   size=12, color=MUTE))
            else:
                # 해설은 **한 번만** 만든다 — 만들고 나면 은행에 남아 다음부터는
                # 곧바로 뜬다(같은 문항마다 API 를 부르면 느리고 돈이 든다).
                box.append(ft.TextButton(
                    "왜 이게 정답인지 설명 보기", icon=ft.Icons.AUTO_AWESOME,
                    on_click=lambda _e, qq=q: _explain(qq),
                    style=ft.ButtonStyle(color=MINT)))
            items.append(ft.Container(
                content=ft.Column(box, spacing=8, tight=True),
                bgcolor=MINT_BG, padding=14, border_radius=10,
                border=ft.Border(left=ft.BorderSide(3, MINT))))

        return ft.Container(
            content=ft.Column(items, spacing=9, tight=True),
            padding=18, border_radius=12,
            bgcolor=ft.Colors.with_opacity(.03, ft.Colors.ON_SURFACE),
            border=ft.Border.all(1, ft.Colors.with_opacity(.08,
                                                           ft.Colors.ON_SURFACE)))

    def _render_cards():
        cards.controls.clear()
        qs = _questions()
        if not banks:
            cards.controls.append(ft.Text(
                "저장된 문제가 없습니다. 이수를 실행하면 돌발퀴즈·형성평가 문항이 모입니다.",
                color=MUTE))
        elif not qs:
            msg = {
                "wrong": "틀린 문항이 없습니다. 잘하고 계십니다.",
                "due": "지금 복습할 문항이 없습니다. 나중에 다시 오세요.",
            }.get(st["mode"], "이 강의에 저장된 문제가 없습니다.")
            cards.controls.append(ft.Text(msg, color=MUTE))
        for i, q in enumerate(qs, start=1):
            cards.controls.append(_card(i, q))
        _safe_update()

    def _lec_options() -> list:
        """이 과목에서 **문항이 실제로 있는** 강만 드롭다운에 올린다."""
        nums = ql.lecture_numbers(banks, _real_bank().get("course"))
        return ([ft.DropdownOption(key="0", text="전체")] +
                [ft.DropdownOption(key=str(n), text=ql.lecture_label(n))
                 for n in nums])

    def _apply():
        """고른 은행(또는 N강 모아보기)을 화면에 올린다."""
        st["answers"].clear()
        st["revealed"].clear()
        if st["lec"]:
            st["virtual"] = ql.gather(banks, _real_bank().get("course"),
                                      st["lec"])
        b = _cur_bank()
        _reorder()
        s = qp.stats_text(qp.bank_stats(_all_questions(), st["prog"], b))
        sub.value = (f"{bank_title(b)} · {s}" if b else "저장된 문제가 없습니다")
        picker.value = str(st["idx"])
        lec_pick.value = str(st["lec"])
        _render_cards()
        _refresh_progress()

    def _load_bank(idx: int):
        st["idx"] = max(0, min(int(idx), max(0, len(banks) - 1)))
        # 은행을 직접 고르면 모아보기는 풀린다 — 고른 은행이 안 보이면 이상하다.
        st["lec"] = 0
        lec_pick.options = _lec_options()
        _apply()

    def on_pick(_=None):
        # 드롭다운이 고른 값은 옵션의 key(문자열 인덱스). 이벤트 인자에 기대지 않고
        # 컨트롤에서 직접 읽는다.
        try:
            _load_bank(int(picker.value))
        except (TypeError, ValueError):
            pass

    def on_lecture(_=None):
        """'3강' 을 고르면 회차를 가리지 않고 그 강의 문항을 모두 모은다."""
        try:
            st["lec"] = int(lec_pick.value or 0)
        except (TypeError, ValueError):
            st["lec"] = 0
        _apply()

    def on_reset_lec(_):
        """이 회차를 처음부터 — 화면뿐 아니라 **쌓인 기록도** 지운다."""
        b = _cur_bank()
        for q in _all_questions():
            qid = q.get("qid")
            st["answers"].pop(qid, None)
            st["revealed"].discard(qid)
            st["prog"].pop(qp.key_for(b, q), None)
        _save_progress()
        _apply()

    def on_reset_all(_):
        """전부 처음부터 — 모든 회차의 기록을 지운다."""
        st["answers"].clear()
        st["revealed"].clear()
        st["prog"].clear()
        _save_progress()
        _apply()

    def on_save_html(_):
        try:
            from config import load_config
            from quiz_page import write_quiz_page
            cfg = load_config()
            qd, out = default_quiz_paths(cfg)
            p = write_quiz_page(qd, out)
            sub.value = f"HTML 저장: {p.name} ({p.parent})"
        except Exception as ex:  # noqa: BLE001
            sub.value = f"HTML 저장 실패: {str(ex)[:120]}"
        _safe_update()

    picker.options = [ft.DropdownOption(key=str(i), text=bank_title(b))
                      for i, b in enumerate(banks)]
    # ⚠️ Flet 0.85 의 Dropdown 은 on_change 가 아니라 **on_select** 다.
    # (없는 속성에 붙이면 조용히 무시되어 강의를 바꿔도 문제가 안 바뀐다)
    picker.on_select = on_pick
    lec_pick.on_select = on_lecture

    def on_mode(mode: str):
        def _h(_=None):
            st["mode"] = mode
            st["answers"].clear()
            st["revealed"].clear()
            _reorder()
            for m, b in mode_btns.items():      # 고른 것만 채운 버튼으로
                b.style = ft.ButtonStyle(
                    bgcolor=MINT if m == mode else None,
                    color="#ffffff" if m == mode else None)
            _render_cards()
            _refresh_progress()
        return _h

    # 반복 학습의 핵심 — '오답만' 을 눌러 틀린 것만 다시 푼다.
    mode_btns = {
        "all": ft.OutlinedButton("전체", tooltip="틀린 것부터 차례로"),
        "wrong": ft.OutlinedButton("오답만", tooltip="아직 못 맞힌 문항만"),
        "due": ft.OutlinedButton("복습할 것",
                                 tooltip="안 푼 것 · 틀린 것 · 다시 볼 때가 된 것"),
    }
    for m, b in mode_btns.items():
        b.on_click = on_mode(m)
    mode_btns["all"].style = ft.ButtonStyle(bgcolor=MINT, color="#ffffff")

    tools = ft.Row(
        [
            *mode_btns.values(),
            ft.Container(width=8),
            ft.OutlinedButton("현재 강 초기화", icon=ft.Icons.RESTART_ALT,
                              on_click=on_reset_lec),
            ft.OutlinedButton("전체 초기화", icon=ft.Icons.REFRESH,
                              on_click=on_reset_all),
            ft.TextButton("HTML로 저장", icon=ft.Icons.SAVE_ALT,
                          on_click=on_save_html),
        ],
        spacing=10, wrap=True,
    )

    _load_bank(st["idx"])
    return ft.Column(
        [
            title, sub,
            ft.Row([picker, lec_pick,
                    ft.Column([ft.Text("푼 문제", size=11, color=MUTE), prog],
                              spacing=0)],
                   vertical_alignment=ft.CrossAxisAlignment.END, spacing=14,
                   wrap=True),
            bar, tools, ft.Divider(height=1), cards,
        ],
        spacing=10, expand=True,
    )
