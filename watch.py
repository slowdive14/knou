"""Phase 3 — 영상 자동이수 (time-budget + JWPlayer 제어).

순수 로직(단위테스트 대상):
  - remaining_minutes(watched, total)     : 남은 분(음수 방지)
  - wall_clock_seconds(rem_min, speed, buffer): 실제 재생에 필요한 벽시계 초
  - clamp_speed(speed)                     : 허용 배속으로 스냅
  - is_complete(lec) / needs_topup(lec)    : 완료/추가시청 판정

브라우저 제어(수동 검증):
  - open_player(page, lec)                 : fnCntsPopup 으로 플레이어 팝업 오픈
  - play_clip(popup, idx, speed)           : 클립 재생 + 배속
  - watch_lecture(page, lec, cfg)          : 한 차시 전체 클립 자동 시청

진도 메커니즘(docs/lms-map.md §4):
  - seek 비활성 → 실시간(배속) 재생 필수
  - 재생 시 parent.fnPlayerProgCheck → registerUSTStudyRslt.ajax 저장
  - 돌발퀴즈 모달(#quiz_*) 출현 시 정오답 무관 → 제출 후 재개
"""
from __future__ import annotations

import json
import time

from discover import Lecture

# wenplayer 허용 배속(settings.speed 목록) + 안전한 하한 0.5
ALLOWED_SPEEDS = (0.5, 0.8, 1.0, 1.2, 1.4, 1.6, 1.8, 2.0)
DEFAULT_BUFFER = 0.12  # 12% 여유 (버퍼링/광고문구 페이드 등)

# 플레이어 상태를 연속으로 못 읽으면(창이 닫힘·세션 끊김) 완청이 아니라 실패로.
READ_FAIL_LIMIT = 3
# '<video> 가 사라짐'을 완청으로 인정하려면 길이의 이만큼까지는 가 있어야 한다.
NEAR_END_RATIO = 0.90


def remaining_minutes(watched_min: int, total_min: int) -> int:
    """남은 시청 분. 음수 방지(이미 다 본 경우 0)."""
    return max(0, int(total_min) - int(watched_min))


def clamp_speed(speed: float) -> float:
    """요청 배속을 허용 배속으로 스냅(범위 밖은 최소/최대로)."""
    try:
        s = float(speed)
    except (TypeError, ValueError):
        return 1.0
    if s <= ALLOWED_SPEEDS[0]:
        return ALLOWED_SPEEDS[0]
    if s >= ALLOWED_SPEEDS[-1]:
        return ALLOWED_SPEEDS[-1]
    # 가장 가까운 허용값
    return min(ALLOWED_SPEEDS, key=lambda a: abs(a - s))


def wall_clock_seconds(remaining_min: int, speed: float,
                       buffer: float = DEFAULT_BUFFER) -> float:
    """남은 분을 주어진 배속으로 볼 때 필요한 실제(벽시계) 초 + 버퍼."""
    if remaining_min <= 0:
        return 0.0
    s = float(speed)
    if s <= 0:
        s = 1.0
    return remaining_min * 60.0 / s * (1.0 + buffer)


def is_complete(lec: Lecture) -> bool:
    """차시 영상 이수 완료 여부.

    ⚠️ prog_rt(진도율)는 재생과 무관하게 0↔50 으로 흔들리는 게 관측됨(신뢰 불가).
    따라서 서버의 확정 플래그 stdyCmyn(=video_done)만 신뢰한다.
    """
    return bool(lec.video_done)


def needs_topup(lec: Lecture) -> bool:
    """재시청(top-up)이 필요한가 = 아직 완료가 아님."""
    return not is_complete(lec)


# ---------------------------------------------------------------------------
# 브라우저 제어 (수동 검증)
# ---------------------------------------------------------------------------

# ⚠️ 이 iframe들에서 wenplayer/구형 라이브러리가 프로토타입을 오염시켜
# Playwright 의 plain-object 직렬화가 깨진다(객체 반환 시 None). → 반드시
# JSON.stringify 문자열로 반환하고 Python 에서 json.loads 한다.

# 클립 iframe 내부에서 실제 <video> 배속을 직접 설정하고 재생 (가장 신뢰성 높음).
# wenplayer 의 #currentSpeedTitle UI(speedYn=N으로 숨김)에 의존하지 않는다.
_SET_RATE_PLAY_JS = """
(rate) => {
  const out = [];
  try { const v = document.querySelector('video');
        if (v) { v.playbackRate = rate; v.play && v.play(); out.push('video.rate='+rate); } }
  catch(e){ out.push('vErr:'+String(e).slice(0,40)); }
  try { if (typeof fnPlaySpeed === 'function') { fnPlaySpeed(String(rate)); out.push('fnPlaySpeed'); } }
  catch(e){ out.push('fsErr:'+String(e).slice(0,40)); }
  return JSON.stringify(out);
}
"""

# 배속만 다시 건다(재생버튼/모달을 절대 건드리지 않음 → 위치 0초 재시작 방지).
# ⚠️ 배속 복구에는 반드시 이 함수만 쓸 것. _start_clip 재호출은 모달의 '아니오'를
#    눌러 클립을 처음부터 재시작시키므로 위험.
_SET_RATE_ONLY_JS = """
(rate) => {
  try { const v = document.querySelector('video');
        if (v) { v.playbackRate = rate; if (v.paused) { v.play && v.play(); } return 'ok'; } }
  catch(e){ return 'err:'+String(e).slice(0,40); }
  return 'noVideo';
}
"""

_CLIP_STATE_JS = """
() => {
  try {
    const v = document.querySelector('video');
    const o = {};
    if (v) { o.pos = v.currentTime; o.dur = v.duration; o.rate = v.playbackRate;
             o.paused = v.paused; o.ended = v.ended; }
    else { o.noVideo = true; }
    return JSON.stringify(o);
  } catch(e) { return JSON.stringify({err: String(e).slice(0,60)}); }
}
"""


def _eval_json(frame, js, *args):
    """프로토타입 오염 회피용: JSON 문자열 반환 evaluate → dict/list 로 파싱."""
    try:
        raw = frame.evaluate(js, *args)
    except Exception as e:
        return {"evalErr": str(e)[:60]}
    if raw is None:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return {"raw": raw}


# 플레이어 팝업 URL 식별(fnCntsPopup 이 frmStudy 를 제출하는 대상).
_PLAYER_URL_HINT = "retrieveUSTStudy"


def _player_popups(page):
    """이 컨텍스트에 열려 있는 플레이어 팝업 페이지들(opener 제외)."""
    return [p for p in page.context.pages
            if p is not page and _PLAYER_URL_HINT in (p.url or "")]


def open_player(page, lec: Lecture):
    """fnCntsPopup 으로 플레이어 팝업을 열고 popup Page 를 반환.

    fnCntsPopup 은 **고정 이름('_POPUP_STUDY')** 창을 연다. 직전 팝업이 덜 닫혀 그
    이름이 남아 있으면 window.open 이 새 창 대신 기존 창을 재사용해 'popup' 이벤트가
    안 떠 타임아웃 난다(이수 모드의 watch→exam 연속 호출에서 발생). 대비:
      1) 남아 있는 플레이어 팝업을 먼저 닫는다(이름 해제).
      2) popup 이벤트가 안 떠도, 폼이 그 창으로 제출돼 플레이어가 떠 있으면 그 창 사용.
      3) 그래도 없으면 잠깐 대기 후 한 번 더 시도(이름이 풀린 뒤 새 창이 열리도록).
    """
    args = {"s": lec.enc_sbjt_id, "t": lec.enc_toc_no,
            "atlc": lec.enc_atlc_no, "sbjt": lec.sbjt_id}
    for p in _player_popups(page):           # 남은 플레이어 팝업 정리
        try:
            p.close()
        except Exception:
            pass

    popup = None
    last_err = None
    for attempt in (1, 2):
        try:
            with page.expect_popup(timeout=20000) as pi:
                page.evaluate(
                    "(a) => fnCntsPopup(a.s, a.t, a.atlc, 'Y', 'Y', a.sbjt)", args)
            popup = pi.value
            break
        except Exception as e:               # popup 이벤트 미발생(이름 재사용 등)
            last_err = e
            cand = _player_popups(page)
            if cand:                         # 재사용된 창이 이미 플레이어면 그걸 사용
                popup = cand[-1]
                break
            for p in _player_popups(page):
                try:
                    p.close()
                except Exception:
                    pass
            time.sleep(3)                    # 이름이 풀리도록 대기 후 재시도
    if popup is None:
        raise last_err

    try:
        popup.wait_for_load_state("networkidle", timeout=30000)
    except Exception:
        pass
    time.sleep(4)
    return popup


def _clip_frames(popup):
    return [fr for fr in popup.frames if "ViewPlayer" in (fr.url or "")]


# 재생기록 모달은 두 종류이며 '예/아니오'의 의미가 정반대다(실측 확인):
#   모달1 "이어서 시청하시겠습니까?"  (부분 시청)
#       예  = wp_elearning_seek  (마지막 위치로 이어보기)
#       아니오 = wp_elearning_play (처음부터)
#   모달2 "처음부터 다시 시청하시겠습니까?" (이미 완청 = 위치가 끝까지 도달)
#       예  = wp_elearning_play  (처음부터 ← 절대 누르면 안 됨, 0초 재시작)
#       아니오 = wp_elearning_stop (취소)
# ⚠️ 버튼 id는 '위치'가 아니라 '동작' 기준이므로, 위치(예/아니오)로 누르면 안 되고
#    반드시 id 로 판별해야 한다. 재생버튼 클릭 후 2~3초 늦게 렌더되므로 폴링한다.
RESUME_SEEK_ID = "wp_elearning_seek"   # 마지막 위치로 이어보기
RESUME_PLAY_ID = "wp_elearning_play"   # 처음부터 (재시작) — 자동이수에선 회피
RESUME_STOP_ID = "wp_elearning_stop"   # 취소(완청 모달)

# 어떤 모달인지 id 존재/가시성으로 판별.
_MODAL_DETECT_JS = """
() => {
  const vis = e => !!(e && e.offsetParent !== null);
  const seek = vis(document.getElementById('wp_elearning_seek'));
  const stop = vis(document.getElementById('wp_elearning_stop'));
  if (seek) return JSON.stringify({type: 'partial'});   // 모달1: 이어보기 가능
  if (stop) return JSON.stringify({type: 'complete'});   // 모달2: 이미 완청
  return JSON.stringify({type: 'none'});
}
"""

_MODAL_CLICK_JS = """
(id) => {
  const e = document.getElementById(id);
  if (e && e.offsetParent !== null) { e.click(); return true; }
  return false;
}
"""


def _handle_resume_modal(popup, frame_index, timeout=8.0):
    """재생기록 모달을 종류에 맞게 처리한다.

    return:
      'partial'  : 모달1 → 이어보기(seek) 클릭함 (재생 계속)
      'complete' : 모달2 → 이미 완청 → 취소(stop) 클릭함 (이 클립은 건너뛰면 됨)
      'none'     : 모달 없음 (신규 클립 등)
    ⚠️ 어느 경우에도 wp_elearning_play(처음부터)는 누르지 않는다.
    """
    deadline = time.time() + timeout
    while time.time() < deadline:
        frames = _clip_frames(popup)
        if frame_index < len(frames):
            fr = frames[frame_index]
            info = _eval_json(fr, _MODAL_DETECT_JS) or {}
            typ = info.get("type")
            if typ == "partial":
                _modal_click(fr, RESUME_SEEK_ID)
                return "partial"
            if typ == "complete":
                _modal_click(fr, RESUME_STOP_ID)
                return "complete"
        time.sleep(0.5)
    return "none"


def _modal_click(frame, btn_id):
    """모달 버튼을 id로 클릭(JS 우선, Playwright 폴백)."""
    try:
        if frame.evaluate(_MODAL_CLICK_JS, btn_id):
            return True
    except Exception:
        pass
    try:
        loc = frame.locator("#" + btn_id).first
        if loc.count():
            loc.click(timeout=1000)
            return True
    except Exception:
        pass
    return False


def _start_clip(popup, frame_index, speed):
    """index 번째 클립을 재생하고 배속 설정. 재생기록 모달은 종류에 맞게 처리.

    재생 시작 시 iframe 이 재로드돼 frame 핸들이 바뀔 수 있으므로
    매 호출마다 popup.frames 에서 새로 가져온다.

    return: 'playing'(재생 시작) / 'already_complete'(이미 완청 → 건너뜀) / 'no_clip'
    """
    frames = _clip_frames(popup)
    if frame_index >= len(frames):
        return "no_clip"
    fr = frames[frame_index]
    for sel in (".jw-display-icon-container", ".jw-icon-display", "video"):
        try:
            fr.locator(sel).first.click(timeout=3000)
            break
        except Exception:
            continue
    # 재생기록 모달 처리(있으면) — 렌더까지 최대 8초 폴링
    modal = _handle_resume_modal(popup, frame_index)
    if modal == "complete":
        return "already_complete"   # 이 클립은 이미 끝까지 봄 → 재생 불필요
    time.sleep(1.0)
    # 프레임 재취득 후 배속/재생
    frames = _clip_frames(popup)
    if frame_index < len(frames):
        try:
            frames[frame_index].evaluate(_SET_RATE_PLAY_JS, speed)
        except Exception:
            pass
    return "playing"


def _clip_state(popup, frame_index):
    frames = _clip_frames(popup)
    if frame_index >= len(frames):
        return {"gone": True}
    state = _eval_json(frames[frame_index], _CLIP_STATE_JS)
    return state if state is not None else {"none": True}


# 프레임에 '실제 재생 가능한 클립'이 들어있는지 판정.
# ViewPlayer iframe 슬롯은 빈 것도 있어(차시마다 영상 1~3개로 다름) <video> 유무로 거른다.
_HAS_VIDEO_JS = """
() => {
  try {
    const v = document.querySelector('video');
    if (!v) return JSON.stringify({has: false});
    const src = v.currentSrc || v.src || '';
    const dur = isFinite(v.duration) ? v.duration : null;
    return JSON.stringify({has: !!(src || dur), src: src.slice(0,60), dur: dur});
  } catch(e) { return JSON.stringify({has: false, err: String(e).slice(0,40)}); }
}
"""


def clip_inventory(popup):
    """각 ViewPlayer 프레임을 조사해 '실제 영상이 든 클립' 인덱스 목록 반환.

    return: list[dict] = [{"index": i, "has": bool, "dur": float|None, "src": str}, ...]
    (차시마다 영상 개수가 1~3개로 달라 빈 슬롯을 걸러내기 위함)
    """
    inv = []
    for i, fr in enumerate(_clip_frames(popup)):
        st = _eval_json(fr, _HAS_VIDEO_JS) or {}
        inv.append({"index": i, "has": bool(st.get("has")),
                    "dur": st.get("dur"), "src": st.get("src", "")})
    return inv


def active_clip_indices(popup):
    """실제 영상이 든 클립의 인덱스만 반환."""
    return [c["index"] for c in clip_inventory(popup) if c["has"]]


def _reapply_speed(popup, frame_index, speed):
    """재생 중 배속이 떨어졌을 때 위치 변경 없이 배속만 다시 설정.

    ⚠️ 절대 _start_clip 을 재호출하지 말 것(모달 '아니오'로 0초 재시작됨).
    """
    frames = _clip_frames(popup)
    if frame_index >= len(frames):
        return False
    try:
        frames[frame_index].evaluate(_SET_RATE_ONLY_JS, speed)
        return True
    except Exception:
        return False


def _dismiss_quiz(popup, on_quiz=None):
    """돌발퀴즈 모달(#quiz_*)이 떠 있으면 보기 하나 골라 확인(정오답 무관)하고 닫는다.

    실제 구조(recon player_frame0.html):
      - 모달 안 form 의 `.answerCh`(보기 라디오) 선택 → `.confirmAnswer`('확인') 클릭.
      - exqsTc=2·exqsDc=3/4 의 첫 클릭은 정답검사만(오답이면 alert) 하고 등록 안 함
        → 한 번 더 클릭하면 정오답 무관하게 registerUSTStudyExamRslt.ajax 로 등록.
      - 등록되면 `.quizClose`('학습계속하기')로 모달을 닫아 영상이 재개된다.
    alert 은 watch_lecture 에서 등록한 popup 'dialog' 핸들러가 자동 수락한다.
    on_quiz(popup) 가 주어지면 등록 직후(정답·해설 노출 상태)에 호출한다(복습 캡처용,
    예외 격리 — 캡처 실패가 시청을 막지 않게 한다).
    """
    try:
        modal = popup.locator("[id^='quiz_']:visible").first
        if modal.count() == 0:
            return False
    except Exception:
        return False

    # (1) 보기 1개 선택 — 커스텀 라벨로 라디오가 가려진 경우 force/label 로 보강.
    try:
        radio = modal.locator(".answerCh").first
        if radio.count() > 0:
            try:
                radio.check(force=True, timeout=1500)
            except Exception:
                modal.locator(".lists label").first.click(timeout=1500)
    except Exception:
        pass

    # (2) 확인 클릭 — 1차=정답검사, 2차=정오답 무관 등록. 등록되면 버튼이 숨겨진다.
    for _ in range(2):
        try:
            btn = modal.locator(".confirmAnswer:visible").first
            if btn.count() == 0:
                break
            btn.click(timeout=1500)
            time.sleep(1.2)
        except Exception:
            break

    # (2-1) 복습 캡처(정답·해설이 드러난 상태). 실패해도 무시.
    if on_quiz is not None:
        try:
            on_quiz(popup)
        except Exception:
            pass

    # (3) 학습계속하기로 모달 닫기 → 영상 재개(닫힘 후 watch 루프가 배속 재적용·play).
    try:
        modal.locator(".quizClose").first.click(timeout=1500)
    except Exception:
        pass
    return True


# ---------------------------------------------------------------------------
# 한 차시 전체 자동 시청 (watch_lecture)
# ---------------------------------------------------------------------------

# 일시정지/저장 트리거: wenplayer 의 fnPlayStop() 호출 → state=stop 으로
# registerUSTStudyRslt.ajax 가 즉시 발사돼 마지막 위치(vidoLocSec)가 서버에 저장됨.
_PLAY_STOP_JS = "() => { if (typeof fnPlayStop === 'function') { fnPlayStop(); return true; } return false; }"


def _trigger_save(popup, settle: float = 4.0):
    """모든 ViewPlayer 프레임에서 fnPlayStop()을 호출해 진도 저장을 강제한다.

    재생 중 300초 하트비트 외에, 클립을 끝낸 직후/차시 종료 시 마지막 위치를
    확실히 서버에 적립시키기 위함. (저장 XHR이 날아갈 시간 settle 만큼 대기)
    """
    fired = 0
    for fr in _clip_frames(popup):
        try:
            if fr.evaluate(_PLAY_STOP_JS):
                fired += 1
        except Exception:
            pass
    if fired:
        time.sleep(settle)
    return fired


def _play_until_end(popup, frame_index, speed, budget_s, poll=15,
                    on_progress=None, on_quiz=None):
    """클립이 끝(ended)까지 재생되도록 감시한다. 진행은 '위치(pos)' 기준.

    - ended 플래그 또는 pos≈dur 도달 시 True 반환(완청).
    - 배속이 떨어지면 위치 유지한 채 배속만 재설정(_reapply_speed, 재시작 금지).
    - 위치가 정체(일시정지/퀴즈모달 등)하면 퀴즈 처리 + 배속 재설정으로 재개.
    - budget_s(벽시계 예산) 초과 시 False(timeout) 반환.

    on_progress(state_dict) 콜백이 있으면 매 폴링마다 호출.
    on_quiz(popup) 콜백은 돌발퀴즈를 처리할 때 _dismiss_quiz 가 호출(복습 캡처용).
    """
    deadline = time.time() + budget_s
    last_pos = None
    seen_dur = None     # 한 번이라도 관측한 유효한 길이(메타데이터)
    max_pos = 0.0       # 도달한 최대 위치
    stalls = 0
    gone_count = 0      # 재생 후 <video> 사라짐 연속 횟수
    err_count = 0       # 플레이어 상태를 아예 못 읽은 연속 횟수(창이 닫힘 등)
    while time.time() < deadline:
        _dismiss_quiz(popup, on_quiz=on_quiz)
        st = _clip_state(popup, frame_index)
        if on_progress:
            try:
                on_progress(st)
            except Exception:
                pass

        # 상태를 **못 읽은** 것(evalErr)은 '영상이 끝났다'와 전혀 다르다.
        # 실측 사고: 플레이어 창이 죽어 evalErr 이 연속으로 나자 아래 (3)번
        # 규칙이 dur=None 을 '재생 후 언로드'로 오인해 7초만 보고도 완청으로
        # 판정했다(컴퓨터구조 10강 · 67분 영상). 읽기 실패는 완청 근거가 아니다.
        if st.get("evalErr"):
            err_count += 1
            if err_count >= READ_FAIL_LIMIT:
                return False        # 창이 닫혔거나 세션이 죽음 → 완청 아님
            time.sleep(poll)
            continue
        err_count = 0

        pos = st.get("pos")
        dur = st.get("dur")
        if isinstance(dur, (int, float)) and dur > 0:
            seen_dur = dur
        if isinstance(pos, (int, float)):
            max_pos = max(max_pos, pos)

        # (1) 명시적 종료 플래그
        if st.get("ended"):
            return True
        # (2) 위치가 끝에 도달(ended 플래그가 안 서는 플레이어 대비)
        if seen_dur and max_pos >= seen_dur - 1.0:
            return True
        # (3) 재생 후 <video> 가 사라짐/리셋(pos=0·dur=None) → 짧은 클립이 끝나면
        #     ended 없이 프레임이 언로드되는 경우가 있어 완청으로 간주.
        #     단발 버퍼링 오탐 방지를 위해 2회 연속 확인.
        #     ⚠️ 길이를 알고 있다면 **끝 근처까지 갔을 때만** 인정한다 —
        #     67분짜리를 7초 보고 언로드된 것을 완청이라 하면 안 된다.
        gone = st.get("gone") or st.get("none") or dur is None
        if gone and seen_dur and max_pos < seen_dur * NEAR_END_RATIO:
            gone = False
        if gone and max_pos > 1.0:
            gone_count += 1
            if gone_count >= 2:
                return True
        else:
            gone_count = 0

        # 배속 하락 → 위치 유지한 채 배속만 복구
        rate = st.get("rate")
        try:
            if rate is not None and float(rate) < float(speed) - 0.1:
                _reapply_speed(popup, frame_index, speed)
        except (TypeError, ValueError):
            pass

        # 위치 정체 감지(일시정지/모달로 멈춤) → 퀴즈 처리 후 배속 재설정으로 재개
        if isinstance(pos, (int, float)) and last_pos is not None and pos <= last_pos + 0.1:
            stalls += 1
            if stalls >= 2:
                _dismiss_quiz(popup, on_quiz=on_quiz)
                _reapply_speed(popup, frame_index, speed)
                stalls = 0
        else:
            stalls = 0
        if isinstance(pos, (int, float)):
            last_pos = pos

        time.sleep(poll)
    return False


def watch_lecture(page, lec: Lecture, cfg=None, speed=None, poll=15,
                  max_wait_factor=1.5, on_progress=None, on_quiz=None):
    """한 차시의 모든 활성 클립을 끝까지 자동 시청해 영상 이수를 완료시킨다.

    동작:
      1) open_player 로 플레이어 팝업을 연다.
      2) clip_inventory 로 실제 영상이 든 클립만 추린다(차시당 1~3개).
      3) 각 클립을 _start_clip(2배속) → _play_until_end 로 끝까지 본다.
         - 이미 완청(모달2)인 클립은 'already_complete'로 건너뛴다.
      4) 클립마다, 그리고 차시 종료 시 _trigger_save 로 진도를 확정 저장한다.
      5) 팝업을 닫는다(finally).

    배속은 speed > cfg.playback_speed > 2.0 순으로 결정해 clamp_speed 로 스냅.

    return: {"seq", "speed", "clips": [{"clip","status","dur"?}...]}
      status ∈ {"already_complete","ended","timeout","no_clip","no_video"}
    """
    sp = clamp_speed(speed if speed is not None
                     else getattr(cfg, "playback_speed", 2.0))
    popup = open_player(page, lec)
    # 돌발퀴즈가 띄우는 네이티브 alert/confirm(오답 안내·선택요구 등)을 자동 수락해
    # 흐름이 멈추지 않게 한다(핸들러는 팝업당 한 번만 등록).
    try:
        popup.on("dialog", lambda d: d.accept())
    except Exception:
        pass
    results = []
    try:
        inv = clip_inventory(popup)
        actives = [c for c in inv if c["has"]]
        if not actives:
            return {"seq": lec.seq, "speed": sp, "clips": [],
                    "note": "no_active_clip"}

        for c in actives:
            idx = c["index"]
            dur = c.get("dur") or 0
            status = _start_clip(popup, idx, sp)
            if status == "already_complete":
                results.append({"clip": idx, "status": "already_complete"})
                continue
            if status != "playing":
                results.append({"clip": idx, "status": status})
                continue
            # 벽시계 예산 = 길이/배속 + 버퍼 → 여유배수 + 고정 여유 60초
            budget = wall_clock_seconds(dur / 60.0, sp) * max_wait_factor + 60.0
            ended = _play_until_end(popup, idx, sp, budget, poll, on_progress,
                                    on_quiz=on_quiz)
            # 이 클립의 마지막 위치를 즉시 저장
            _trigger_save(popup)
            results.append({"clip": idx,
                            "status": "ended" if ended else "timeout",
                            "dur": dur})
        # 차시 종료 — 한 번 더 확정 저장
        _trigger_save(popup)
    finally:
        try:
            popup.close()
        except Exception:
            pass
    return {"seq": lec.seq, "speed": sp, "clips": results}
