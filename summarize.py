"""Phase 5 — Gemini 강의 요약 + 타임스탬프 → Obsidian.

MP3(음성) + PDF(강의록)를 google-genai로 업로드해, 개념별 음성 타임스탬프
`🎬 [HH:MM:SS]`가 붙은 구조화 마크다운 요약을 생성하고 볼트에 저장한다.
타임스탬프는 마크다운에서 추출해 사이드카 JSON으로도 남긴다(Phase 6 화면캡처용).

순수 로직(단위테스트 대상):
  - timestamp_to_seconds / seconds_to_timestamp
  - note_filename(subject, seq, name)
  - needs_summary(path)
  - extract_timestamps(markdown)  : [HH:MM:SS]/[MM:SS] + 라벨 추출
  - build_prompt(subject, seq, name)

Gemini/IO(수동 검증):
  - upload_and_wait(client, path) : File API 업로드 후 ACTIVE 대기
  - summarize_lecture(client, ...) : 업로드 → generate_content → 마크다운 텍스트
  - save_summary(md, out_dir, ...) : .md + .timestamps.json 저장

⚠️ GEMINI_API_KEY 는 로그/출력에 절대 노출하지 않는다(config에서만 사용).
"""
from __future__ import annotations

import json
import mimetypes
import os
import re
import time
from pathlib import Path

from download import sanitize

# 쓸 모델 차례 — **앞의 것이 붐비면 다음 것으로 넘어간다.**
#
# ⚠️ 모델은 예고 없이 막힌다. gemini-2.5-flash 는 어느 날 신규 사용자에게
#    404 로 닫혔고('no longer available to new users'), 그래서 API 키를 새로
#    만든 순간 앱 전체가 멈췄다. 하나에 매달리지 않는다.
# ⚠️ 무료 등급은 503(고부하)이 잦다. 최신 모델일수록 더 붐빈다 — 실제로
#    3.6~3.8 은 줄줄이 503 인데 3.5 는 15초 만에 답했다.
MODEL_CHAIN = ("gemini-3.5-flash", "gemini-3-flash-preview",
               "gemini-3.1-flash-lite", "gemini-flash-latest")


def _env_model() -> str:
    """'.env' 의 GEMINI_MODEL — 설정 화면을 거치지 않고도 바꿀 수 있게."""
    try:
        from dotenv import load_dotenv
        load_dotenv(Path(__file__).resolve().parent / ".env", override=False)
    except Exception:  # noqa: BLE001 - .env 가 없어도 기본값으로 돈다
        pass
    return os.environ.get("GEMINI_MODEL", "").strip()


DEFAULT_MODEL = _env_model() or MODEL_CHAIN[0]

# 빈 응답(finish_reason=MAX_TOKENS) 방지용. thinking 이 출력 예산을 잠식해,
# 한도 미설정 시 긴 강의에서 본문이 비어 돌아올 수 있다.
MAX_OUTPUT_TOKENS = 32768   # 출력 예산을 넉넉히(thinking+본문 합산 한도)
THINKING_BUDGET = 8192      # thinking 상한(0=비활성). 본문 예산을 남겨둔다

# 붐빌 때 다음 모델로 넘어가기 전에 쉬는 시간(초). 사람이 화면 앞에서
# 기다리는 자리라 길게 끌지 않는다.
RETRY_WAIT = 1.5
ROUNDS = 2          # 모델 차례를 몇 바퀴 돌지(503 은 몇 초 뒤면 풀린다)

# 확장자 → MIME (google-genai가 한글 경로 헤더 인코딩에 실패하므로
# 파일 객체 업로드 시 명시적으로 넘긴다)
_MIME_FALLBACK = {".mp3": "audio/mpeg", ".pdf": "application/pdf",
                  ".m4a": "audio/mp4", ".wav": "audio/wav",
                  ".mp4": "video/mp4", ".txt": "text/plain"}


def _guess_mime(path) -> str:
    ext = Path(path).suffix.lower()
    if ext in _MIME_FALLBACK:
        return _MIME_FALLBACK[ext]
    mime, _ = mimetypes.guess_type(str(path))
    return mime or "application/octet-stream"

# [H:MM:SS] / [MM:SS] / [HH:MM:SS]
_TS_RE = re.compile(r"\[(\d{1,2}:\d{2}(?::\d{2})?)\]")
# 라벨 정리용(앞쪽 마크다운 마커/리스트 기호 제거)
_LABEL_STRIP = re.compile(r"^[\s#\-*>•·]+|[\s]+$")
# 라벨 어디에 있든 제거할 기호(타임스탬프 이모지 + 볼드 마커)
_LABEL_DROP = re.compile(r"🎬|\*\*")


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def timestamp_to_seconds(ts: str) -> int:
    """'HH:MM:SS' 또는 'MM:SS' → 초. 형식 오류면 0."""
    ts = (ts or "").strip()
    if not ts:
        return 0
    parts = ts.split(":")
    try:
        nums = [int(p) for p in parts]
    except ValueError:
        return 0
    if len(nums) == 3:
        h, m, s = nums
    elif len(nums) == 2:
        h, m, s = 0, nums[0], nums[1]
    else:
        return 0
    return h * 3600 + m * 60 + s


def seconds_to_timestamp(sec: int) -> str:
    """초 → 'HH:MM:SS'."""
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    return f"{h:02d}:{m:02d}:{s:02d}"


def normalize_ts_seconds(sec, duration) -> int:
    """Gemini 의 'MM:SS:00' 오형식 타임스탬프를 매체 길이로 교정한다.

    2시간짜리 강의에서 1시간 미만 시점을 "09:21"(9분21초) 대신 "09:21:00"으로
    적으면 timestamp_to_seconds 가 9시간21분(33660초)으로 파싱 → 전체 길이 초과.
    원래 의도는 'h→분, m→초' 한 칸씩 밀린 것이므로 필드를 되돌려 복원한다.

    교정 조건(보수적): 길이를 알고, raw 초가 길이를 60초 넘게 초과하며,
    시프트 결과가 길이 이내일 때만 적용. 그 외엔 그대로(끝자락 근사·정상값 보호).
    """
    sec = int(sec)
    if not duration or sec <= float(duration):
        return sec
    h = sec // 3600
    m = (sec % 3600) // 60
    shifted = h * 60 + m          # 09:21:00 → 9*60+21 = 561
    if sec - float(duration) > 60 and shifted <= float(duration):
        return shifted
    return sec


def normalize_markdown_timestamps(markdown: str, duration) -> str:
    """노트 본문의 [HH:MM:SS]/[MM:SS] 마커를 normalize_ts_seconds 기준으로 교정.

    오형식(예: '[09:21:00]' = 9h21m)을 매체 길이로 판별해 '[00:09:21]'로 치환한다.
    교정이 필요 없는 마커는 그대로 둔다(멱등). duration 이 없으면 원문 반환.
    """
    if not markdown or not duration:
        return markdown

    def _fix(m):
        ts = m.group(1)
        raw = timestamp_to_seconds(ts)
        norm = normalize_ts_seconds(raw, duration)
        if norm == raw:
            return m.group(0)
        return f"[{seconds_to_timestamp(norm)}]"

    return _TS_RE.sub(_fix, markdown)


def note_filename(subject: str, seq: int, name: str) -> str:
    """'{과목} {seq}강 - {차시명}.md' (안전한 파일명)."""
    return f"{sanitize(subject)} {seq}강 - {sanitize(name)}.md"


def needs_summary(path) -> bool:
    """요약 노트가 없거나 비어 있으면 True."""
    p = Path(path)
    try:
        return (not p.exists()) or p.stat().st_size == 0
    except OSError:
        return True


def extract_timestamps(markdown: str) -> list[dict]:
    """마크다운에서 [HH:MM:SS]/[MM:SS]를 찾아 [{timestamp, seconds, label}] 반환.

    같은 초가 여러 번이면 첫 항목만(dedupe). 등장 순서 유지.
    label = 타임스탬프가 있던 줄에서 마커([ts], #, 🎬 등)를 뺀 텍스트.
    """
    out = []
    seen = set()
    for line in (markdown or "").splitlines():
        m = _TS_RE.search(line)
        if not m:
            continue
        ts = m.group(1)
        sec = timestamp_to_seconds(ts)
        if sec in seen:
            continue
        seen.add(sec)
        label = _TS_RE.sub("", line)
        label = _LABEL_DROP.sub("", label)
        label = _LABEL_STRIP.sub("", label)
        label = re.sub(r"\s{2,}", " ", label).strip()
        # 타임스탬프 제거로 남은 잔여 구두점 정리(예: 같은 줄 2개 → "..., ")
        label = label.strip(" ,;")
        # 정규화: HH:MM:SS로 통일
        out.append({"timestamp": seconds_to_timestamp(sec),
                    "seconds": sec, "label": label})
    return out


def practice_rules(duration=None, notebook: bool = False,
                   screens: bool = False) -> str:
    """강의 전체·실습을 빠뜨리지 말라는 요구 — build_prompt 끝에 붙는다.

    오픈소스기반데이터분석은 슬라이드가 끝난 뒤 30분을 코드 실습에 쓰는데,
    노트는 슬라이드가 끝나는 곳에서 함께 끝났다(5강: 57분 중 26분까지).
    음성 길이를 알려 주고 끝까지 다루게 하며, 실습은 개념 카드(쉬운 정의·
    비유…) 대신 단계별 완성 코드로 담게 한다.
    """
    lines = []
    if duration:
        mins = int(round(float(duration) / 60))
        lines.append(
            f"9. 이 강의 음성은 약 **{mins}분**이다. **처음부터 끝까지** 다뤄라 — "
            f"슬라이드 설명이 끝난 뒤에도 강의는 이어진다. 노트의 마지막 `🎬` "
            f"마커는 음성 끝 무렵(약 {max(1, mins - 8)}분 이후)이어야 한다.")
    lines.append(
        "10. 강사가 코드를 직접 작성·실행하는 **실습(시연)**이 있으면 생략하지 말고 "
        "`## 실습` 대주제(여러 묶음이면 `## 실습: …`) 아래 단계별 `###`로 정리하라. "
        "실습 단계에는 2번 항목(쉬운 정의·비유 등) 대신 다음을 담는다:\n"
        "   - 개념과 같은 규칙의 `🎬 [HH:MM:SS]` 마커(그 단계를 시작하는 위치)\n"
        "   - 이 단계에서 하는 일 한두 줄\n"
        "   - 강사가 작성한 **완성 코드**(```python 블록). 보이지도 들리지도 않는 "
        "부분은 지어내지 말고 `# (확인 필요)` 주석으로 남긴다\n"
        "   - 화면이나 음성에 나온 **실행 결과**와 코드에서 눈여겨볼 점\n"
        "   실습 단계도 `## 한눈에 정리`·`## 예습 체크리스트`에 반영하라.\n"
        "   ⚠️ API 인증키·토큰·비밀번호는 화면에 보여도 **옮기지 말고** "
        "`'[발급받은 인증키]'` 로 적어라.")
    if notebook:
        lines.append(
            "11. 첨부한 **실습 노트북**은 강의에서 쓰는 빈칸 실습지다. 실습 단계의 "
            "순서·번호·제목(예: `5-1 CSV 형식 저장`)은 노트북을 따르고, 주석만 "
            "있는 빈칸은 강사가 채운 코드로 완성하라. 노트북에 이미 있는 코드도 "
            "빠뜨리지 말고 함께 적는다.")
    if screens:
        lines.append(
            "12. 첨부한 **화면 사진**에는 `[HH:MM:SS]` 시각이 붙어 있다(음성과 같은 "
            "시간축). 코드와 실행 결과는 **화면을 우선으로** 그대로 옮기고, 화면에서 "
            "잘린 줄 끝만 음성으로 보충하라. 실습 단계의 `🎬` 마커도 화면 시각에 "
            "맞춘다.")
    return "\n".join(lines)


def build_prompt(subject: str, seq: int, name: str,
                 has_audio: bool = True, duration=None,
                 notebook: bool = False, screens: bool = False) -> str:
    """Gemini에 보낼 한국어 '예습 학습 노트' 지시문.

    has_audio=False 는 MP3 를 못 구한 과목(LMS 에 음성 링크가 없고 영상에서도
    추출 실패)용이다. 음성이 없는데 '음성을 분석하라'고 시키면 모델이 없는 것을
    지어내고, 있지도 않은 `🎬 [HH:MM:SS]` 마커까지 만들어 낸다(그 마커는 덱 매칭이
    실제 영상 위치로 쓰는 값이라 틀리면 이미지가 엉뚱한 곳에 붙는다) → 지시문에서
    음성·타임스탬프 요구를 통째로 뺀다.

    duration(음성 초)·notebook(실습 노트북 첨부)·screens(화면 사진 첨부)를 주면
    강의를 끝까지, 실습을 빠짐없이 다루라는 요구가 붙는다(practice_rules).
    """
    if not has_audio:
        return _build_prompt_no_audio(subject, seq, name)
    extra = practice_rules(duration, notebook, screens)
    return _base_prompt(subject, seq, name) + "\n" + extra + \
        "\n위 9번 이후 요구를 지키되, 8번(마크다운 본문만 출력)은 그대로 따른다."


def build_theory_prompt(subject: str, seq: int, name: str) -> str:
    """실습을 따로 쓰는 강의의 **이론 부분** 지시문 — 예전 노트와 같은 깊이로.

    한 번에 이론·실습을 다 쓰게 했더니 실습이 늘어난 만큼 이론을 줄여 썼다
    (실측: 2강 이론 13,232자 → 3,860자). 이론은 예전 지시문 그대로 쓰게 하고
    실습은 build_practice_prompt 로 따로 받아 merge_practice 로 붙인다.
    """
    return _base_prompt(subject, seq, name) + "\n" + (
        "9. 이 강의 후반의 **코드 실습(시연)** 은 따로 정리해 이 노트 뒤에 붙인다. "
        "여기서는 슬라이드·설명 부분만 빠짐없이 다루고 `## 실습` 대주제는 쓰지 "
        "마라. 다만 끝의 `## 한눈에 정리`·`## 예습 체크리스트`는 실습까지 포함한 "
        "강의 전체를 기준으로 쓴다.")


def build_practice_prompt(subject: str, seq: int, name: str, duration=None,
                          notebook: bool = False, screens: bool = False) -> str:
    """강의의 **실습 부분만** 정리하라는 지시문 — 이론 노트 뒤에 붙인다."""
    lines = [
        f"너는 한국방송통신대학교 '{subject}' {seq}강 '{name}'의 학습 도우미다.",
        "첨부한 **강의 음성(MP3)**과 실습 자료를 보고, 강사가 코드를 직접 "
        "작성·실행하는 **실습(시연) 부분만** 한국어 마크다운으로 정리하라. 슬라이드 "
        "이론 설명은 이미 따로 정리되어 있으니 쓰지 마라.",
        "",
        "[대상 독자] 이제 막 CS 를 시작한 **입문자**다. 코드 한 줄 한 줄이 무엇을 "
        "하는지 쉬운 말로 짚어 주고, 막힐 만한 곳은 더 설명하라.",
        "",
        "요구사항:",
        "1. 실습 대주제 하나(제목 `## 실습`, 여러 묶음이면 `## 실습: 주제`)로 시작하고 "
        "단계마다 `###` 소제목을 단다. 맨 위 `#` 제목·`## 한눈에 정리`·"
        "`## 예습 체크리스트`는 쓰지 마라.",
        "2. 각 단계에는 다음을 담는다:",
        "   - 소제목 바로 아래 독립된 한 줄에 `🎬 [HH:MM:SS]` 마커(그 단계를 시작하는 "
        "위치, 음성 기준) 1개",
        "   - 이 단계에서 하는 일 한두 줄",
        "   - 강사가 작성한 **완성 코드**(```python 블록)",
        "   - 화면이나 음성에 나온 **실행 결과**, 코드에서 눈여겨볼 점·헷갈리기 쉬운 점",
        "3. 보이지도 들리지도 않는 부분은 지어내지 말고 `# (확인 필요)` 주석으로 남긴다.",
        "4. ⚠️ API 인증키·토큰·비밀번호는 화면에 보여도 **옮기지 말고** "
        "`'[발급받은 인증키]'` 로 적어라.",
    ]
    if duration:
        mins = int(round(float(duration) / 60))
        lines.append(
            f"5. 실습은 보통 슬라이드 설명이 끝난 뒤부터 강의 끝(약 {mins}분)까지 "
            "이어진다. **끝까지** 다뤄라.")
    if notebook:
        lines.append(
            "6. 첨부한 **실습 노트북**은 강의에서 쓰는 빈칸 실습지다. 단계의 "
            "순서·번호·제목(예: `5-1 CSV 형식 저장`)은 노트북을 따르고, 주석만 있는 "
            "빈칸은 강사가 채운 코드로 완성하라. 노트북에 이미 있는 코드도 함께 적는다.")
    if screens:
        lines.append(
            "7. 첨부한 **화면 사진**에는 `[HH:MM:SS]` 시각이 붙어 있다(음성과 같은 "
            "시간축). 코드와 실행 결과는 **화면을 우선으로** 그대로 옮기고, 잘린 줄 "
            "끝만 음성으로 보충하라. `🎬` 마커도 화면 시각에 맞춘다.")
    lines.append(
        "8. 이 강의에 코드 실습이 없으면 아무것도 쓰지 말고 `없음` 한 단어만 "
        "출력하라. 사족/머리말 없이 **마크다운 본문만** 출력하라(코드펜스로 감싸지 "
        "말 것).")
    return "\n".join(lines)


_FENCE_LINE_RE = re.compile(r"^\s*(```|~~~)")
_TAIL_NAMES = ("한눈에 정리", "예습 체크리스트")


def md_sections(markdown: str) -> list:
    """`## ` 대주제 단위로 나눈다 → [(제목 줄 또는 None, 글)].

    코드 블록 안의 '## 주석' 줄은 대주제가 아니다(실습 코드에 흔하다).
    맨 앞(제목 `#`·머리말)은 제목 None 으로 돌려준다.
    """
    out, head, buf, inside = [], None, [], False
    for line in str(markdown or "").splitlines():
        if _FENCE_LINE_RE.match(line):
            inside = not inside
        elif not inside and line.startswith("## "):
            out.append((head, "\n".join(buf)))
            head, buf = line, []
        buf.append(line)
    out.append((head, "\n".join(buf)))
    return [(h, t) for h, t in out if h is not None or t.strip()]


def _is_tail(head) -> bool:
    return bool(head) and any(n in head for n in _TAIL_NAMES)


def _trim_rule(text: str) -> str:
    """덩어리 끝의 빈 줄과 `---` 구분선을 걷어 낸다(다시 붙일 때 겹치지 않게)."""
    return re.sub(r"(\s*\n-{3,}\s*)+$", "", text.rstrip()).rstrip()


_RULE = "\n\n---\n\n"


def merge_practice(theory: str, practice: str) -> str:
    """이론 노트에 실습 부분을 붙인다 → 이론 본문 · 실습 · 한눈에 정리 순서.

    응답이 어떤 모양으로 오든 대주제 단위로 다시 짠다:
      · 이론 쪽 '## …실습…' 대주제는 뺀다(같은 실습이 두 번 나오지 않게)
      · 실습 쪽의 정리·체크리스트는 뗀다(정리는 이론 쪽 것 하나)
      · 정리·체크리스트는 어디에 있었든 맨 끝으로 보낸다
    실습 쪽에 대주제가 없으면(`없음`) 이론 노트를 그대로 둔다.
    """
    if not str(theory or "").strip():
        return ""
    t_secs = md_sections(theory)
    prac = [_trim_rule(t) for h, t in md_sections(tidy_headings(practice))
            if h is not None and not _is_tail(h)]
    if not prac:
        return str(theory).rstrip() + "\n"
    body = [_trim_rule(t) for h, t in t_secs
            if not _is_tail(h) and not (h and "실습" in h)]
    tail = [_trim_rule(t) for h, t in t_secs if _is_tail(h)]
    parts = [_RULE.join(x for x in body if x.strip()), _RULE.join(prac)]
    if tail:
        parts.append("\n\n".join(tail))
    return _RULE.join(x for x in parts if x.strip()) + "\n"


def reorder_practice(markdown: str) -> str:
    """이미 저장된 노트의 실습 대주제를 정리 앞으로 옮긴다(내용은 그대로)."""
    prac = "\n\n".join(t for h, t in md_sections(markdown)
                         if h and "실습" in h and not _is_tail(h))
    return merge_practice(markdown, prac) if prac else markdown


def _base_prompt(subject: str, seq: int, name: str) -> str:
    return f"""너는 한국방송통신대학교 '{subject}' {seq}강 '{name}'의 학습 도우미다.
첨부한 **강의 음성(MP3)**과 **강의록(PDF)**을 함께 분석해, 학습자가 이 노트만 읽어도
**강의 전체 내용을 효율적으로 예습**할 수 있는 **한국어 마크다운 학습 노트**를 작성하라.

[대상 독자] 이제 막 CS(컴퓨터과학)를 시작한 **입문자**다. 어려운 용어·개념이 나오면
**중학교 3학년도 이해할 수 있게** 쉬운 말로 풀어 설명하고, 이해를 돕는 직관·비유·배경지식을
필요할 때 짧게 덧붙여라(군더더기는 금지). 목표는 '짧은 요약'이 아니라 '빠진 곳 없는 효율적 예습'이다.

요구사항:
1. 구조: `# {subject} {seq}강 - {name}` 제목으로 시작하고, 강의 흐름 순서대로 `##` 대주제,
   `###` 핵심 개념으로 나눈다. 강의에서 다룬 **중요한 내용·예시·결론을 빠짐없이** 포괄하라.
2. 각 `###` 핵심 개념마다 아래를 담되, 초보자가 막힐 부분은 과감히 더 설명하라:
   - **쉬운 정의**: 한 문장으로 핵심을 먼저 말하고, 이어서 입문자 눈높이로 풀어 설명.
   - **왜 필요한가 / 어디에 쓰나**: 동기와 응용을 한두 줄로.
   - **직관·비유·예시**: 이해를 돕는 비유나 구체 예시(필요할 때만).
   - **헷갈리기 쉬운 점**: 있으면 짧게 짚어준다.
   - 처음 나오는 전문용어는 `한국어(영문/약자)` 형태로 쓰고 뜻을 한 줄로 풀어준다.
3. 각 `###` 핵심 개념에는, 그 개념을 **음성에서 설명하기 시작하는 위치**를 가리키는 마커
   `🎬 [HH:MM:SS]`(음성 기준)를 **개념 제목 바로 아래의 독립된 한 줄**에 정확히 1개 넣어라
   (`###` 제목 줄과 같은 줄에 쓰지 말 것). 가능하면 강의록 **추정 페이지**를 `(교재 p.N)`로 덧붙인다.
4. 타임스탬프는 음성 기준 근사치여도 되나 형식은 반드시 `[HH:MM:SS]`(시:분:초)로 통일하라.
5. 수식·기호는 KaTeX 인라인(`$...$`), 절차·알고리즘은 번호 목록, 비교는 표를 적절히 활용.
6. 끝에 `## 한눈에 정리`로 이 강의의 핵심을 5~8개 bullet로 복습용 정리하고,
   이어서 `## 예습 체크리스트`로 "강의를 보면 이걸 설명할 수 있어야 한다" 식 점검 질문 3~5개를 둔다.
7. 따옴표 사용을 절제하라. 일반 용어·개념어(예: 시스템 장애, 트랜잭션, 데이터베이스)에는
   작은따옴표('')를 두르지 말고 그냥 쓴다. 강조가 필요하면 **굵게**로 표시하고,
   작은따옴표는 꼭 필요한 경우(코드·명령어 식별자, 글자 그대로의 인용)에만 제한적으로 쓴다.
8. 사족/머리말 없이 **마크다운 본문만** 출력하라(코드펜스로 감싸지 말 것)."""


def _build_prompt_no_audio(subject: str, seq: int, name: str) -> str:
    """강의록(PDF)만 있을 때의 지시문 — 음성·타임스탬프 요구를 뺀 판본."""
    return f"""너는 한국방송통신대학교 '{subject}' {seq}강 '{name}'의 학습 도우미다.
첨부한 **강의록(PDF)**을 분석해, 학습자가 이 노트만 읽어도 **강의 내용을 효율적으로
예습**할 수 있는 **한국어 마크다운 학습 노트**를 작성하라.

⚠️ 이 강의는 **강의 음성이 제공되지 않아 강의록만** 첨부되어 있다. 강의록에 없는
내용을 지어내지 말고, 강사가 말했을 법한 내용을 상상해 쓰지 마라. 시간 위치를
가리키는 마커(`🎬 [HH:MM:SS]`)도 **절대 넣지 마라**(근거가 없다).

[대상 독자] 이제 막 CS(컴퓨터과학)를 시작한 **입문자**다. 어려운 용어·개념이 나오면
**중학교 3학년도 이해할 수 있게** 쉬운 말로 풀어 설명하고, 이해를 돕는 직관·비유·배경지식을
필요할 때 짧게 덧붙여라(군더더기는 금지). 목표는 '짧은 요약'이 아니라 '빠진 곳 없는 효율적 예습'이다.

요구사항:
1. 구조: `# {subject} {seq}강 - {name}` 제목으로 시작하고, 강의록 순서대로 `##` 대주제,
   `###` 핵심 개념으로 나눈다. 강의록이 다룬 **중요한 내용·예시·결론을 빠짐없이** 포괄하라.
2. 각 `###` 핵심 개념마다 아래를 담되, 초보자가 막힐 부분은 과감히 더 설명하라:
   - **쉬운 정의**: 한 문장으로 핵심을 먼저 말하고, 이어서 입문자 눈높이로 풀어 설명.
   - **왜 필요한가 / 어디에 쓰나**: 동기와 응용을 한두 줄로.
   - **직관·비유·예시**: 이해를 돕는 비유나 구체 예시(필요할 때만).
   - **헷갈리기 쉬운 점**: 있으면 짧게 짚어준다.
   - 처음 나오는 전문용어는 `한국어(영문/약자)` 형태로 쓰고 뜻을 한 줄로 풀어준다.
3. 각 `###` 핵심 개념 제목 바로 아래 독립된 한 줄에 강의록 페이지를 `(교재 p.N)` 로 적어라
   (페이지를 특정할 수 없으면 그 줄을 생략한다). 시간 마커는 넣지 않는다.
4. 강의록이 슬라이드라 설명이 짧으면, 슬라이드에 적힌 항목을 **풀어서** 설명하되
   근거 없는 사실·수치·인용은 만들지 마라.
5. 수식·기호는 KaTeX 인라인(`$...$`), 절차·알고리즘은 번호 목록, 비교는 표를 적절히 활용.
6. 끝에 `## 한눈에 정리`로 이 강의의 핵심을 5~8개 bullet로 복습용 정리하고,
   이어서 `## 예습 체크리스트`로 "강의를 보면 이걸 설명할 수 있어야 한다" 식 점검 질문 3~5개를 둔다.
7. 따옴표 사용을 절제하라. 강조가 필요하면 **굵게**로 표시한다.
8. 사족/머리말 없이 **마크다운 본문만** 출력하라(코드펜스로 감싸지 말 것)."""


# ---------------------------------------------------------------------------
# Gemini / IO (수동 검증)
# ---------------------------------------------------------------------------
def upload_and_wait(client, path, timeout: float = 300.0, poll: float = 3.0,
                    on_event=None):
    """File API로 업로드 후 state가 ACTIVE 될 때까지 대기. File 반환."""
    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    # 한글 파일명이 X-Goog-Upload-File-Name 헤더(ASCII 전용)에 들어가면
    # httpx가 인코딩 실패 → 파일 객체 + 명시적 mime_type로 업로드한다.
    mime = _guess_mime(path)
    with open(path, "rb") as fh:
        f = client.files.upload(file=fh, config={"mime_type": mime})
    name = getattr(f, "name", None)
    log(f"업로드: {Path(path).name} → {name}")
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = str(getattr(f, "state", "") or "")
        if "ACTIVE" in state.upper():
            return f
        if "FAILED" in state.upper():
            raise RuntimeError(f"파일 처리 실패: {Path(path).name} state={state}")
        time.sleep(poll)
        f = client.files.get(name=name)
    raise TimeoutError(f"파일 ACTIVE 대기 시간초과: {Path(path).name}")


def _strip_code_fence(text: str) -> str:
    """응답이 ```...``` 코드펜스로 감싸여 오면 벗겨낸다."""
    text = (text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return text


def _resp_text(resp) -> str:
    """resp.text 가 비면 candidates parts 에서 직접 텍스트를 긁어모은다."""
    try:
        t = getattr(resp, "text", None)
    except Exception:
        t = None
    if not t:
        try:
            parts = resp.candidates[0].content.parts or []
            t = "".join(getattr(p, "text", "") or "" for p in parts)
        except Exception:
            t = None
    return _strip_code_fence(t or "")


def busy_error(exc) -> bool:
    """이 오류는 **잠깐 붐빈 것**인가(다음 모델로 넘어가 볼 만한가).

    503(고부하)·429(호출 한도)·404(그 모델이 닫힘)가 여기 해당한다. 무료
    등급에서는 이 셋이 대부분이라, 여기서 포기하면 앱이 그냥 멈춘 것처럼
    보인다.
    """
    s = str(exc or "")
    return any(k in s for k in ("503", "429", "404", "UNAVAILABLE",
                                "RESOURCE_EXHAUSTED", "NOT_FOUND"))


def model_chain(model=None) -> list:
    """시도할 모델 차례 — 고른 것을 맨 앞에 두고 나머지를 뒤에 붙인다."""
    first = str(model or DEFAULT_MODEL).strip()
    out = [first] if first else []
    for m in MODEL_CHAIN:
        if m not in out:
            out.append(m)
    return out


def generate(client, contents, config=None, model=None, on_event=None,
             wait: float = RETRY_WAIT, rounds: int = ROUNDS, exclude=()):
    """모델을 불러 응답을 받는다 — 붐비면 다음 모델로 넘어간다.

    ⚠️ 한 모델에 매달리지 않는 것이 요점이다. 무료 등급에서 503 은 흔한
       일이고, 그때마다 '설명을 만들지 못했습니다' 를 보여 주면 쓸 수가 없다.

    ⚠️ 모델 차례를 **여러 바퀴** 돈다. 한 바퀴만 돌면 다 같이 붐비는 순간에
       그냥 포기하게 되는데, 503 은 몇 초 뒤면 풀리는 일이 많다. 바퀴를
       돌 때마다 조금 더 오래 기다린다.

    모두 실패하면 마지막 오류를 그대로 올린다(부르는 쪽이 이미 감싸고 있다).
    exclude 에 든 모델은 건너뛴다(다 빠지면 원래 차례를 쓴다).
    """
    chain = ([m for m in model_chain(model) if m not in set(exclude or ())]
             or model_chain(model))
    plan = [(r, m) for r in range(max(1, int(rounds))) for m in chain]
    last = None
    for i, (r, name) in enumerate(plan):
        try:
            return client.models.generate_content(
                model=name, contents=contents, config=config)
        except Exception as e:  # noqa: BLE001 - 다음 모델로 넘어가 본다
            last = e
            if not busy_error(e) or i == len(plan) - 1:
                raise
            nxt = plan[i + 1][1]
            if on_event:
                on_event(f"   {name} 이 붐빕니다 → {nxt} 로 바꿔 봅니다")
            if wait:
                time.sleep(float(wait) * (r + 1))
    raise last if last else RuntimeError("부를 모델이 없습니다")


def _finish_reason(resp) -> str:
    try:
        return str(resp.candidates[0].finish_reason)
    except Exception:
        return "?"


def _block_reason(resp):
    try:
        br = resp.prompt_feedback.block_reason
        return str(br) if br else None
    except Exception:
        return None


def summarize_lecture(client, subject, seq, name, mp3_path=None, pdf_path=None,
                      model=DEFAULT_MODEL, on_event=None, duration=None,
                      notebook_text: str = "", screens=None,
                      split_practice: bool = False):
    """MP3+PDF 업로드 → Gemini 요약(마크다운 텍스트) 반환.

    gemini-2.5-flash 의 빈 응답(thinking 이 출력 예산 잠식)을 막기 위해
    max_output_tokens 와 thinking 상한을 명시하고, 그래도 비면 finish_reason 을
    남긴 뒤 thinking 을 꺼서 1회 재시도한다.

    실습이 있는 강의는 notebook_text(빈칸 실습지를 글로 바꾼 것)와
    screens([(초, 그림 경로)] — 강사가 코드를 쳐 넣는 화면)를 함께 넘긴다.
    duration(음성 초)을 주면 끝까지 다루라고 지시한다.

    split_practice=True 면 **두 번에 나눠** 쓴다 — 이론은 예전 지시문 그대로,
    실습은 실습 자료와 함께 따로 쓰고 merge_practice 로 붙인다. 한 번에 다
    쓰게 하면 실습이 늘어난 만큼 이론을 줄여 썼다(실측: 2강 이론 13,232자 →
    3,860자).
    """
    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    files = []
    if pdf_path and Path(pdf_path).exists():
        files.append(upload_and_wait(client, pdf_path, on_event=on_event))
    has_audio = bool(mp3_path and Path(mp3_path).exists())
    if has_audio:
        files.append(upload_and_wait(client, mp3_path, on_event=on_event))
    else:
        # 음성 없이 '음성을 분석하라'고 시키면 없는 내용·타임스탬프를 지어낸다
        log("강의 음성 없음 → 강의록(PDF)만으로 요약(타임스탬프 마커 생략)")

    from google.genai import types

    # 실습 자료 — 음성이 있을 때만 쓴다(화면 시각은 음성 시간축이다)
    extra = []
    nb = str(notebook_text or "").strip() if has_audio else ""
    if nb:
        extra.append("[실습 노트북 — 강의에서 쓰는 빈칸 실습지]\n\n" + nb)
    shown = 0
    for sec, path in (screens or []) if has_audio else []:
        try:
            data = Path(path).read_bytes()
        except OSError:
            continue
        extra.append(f"[{seconds_to_timestamp(int(sec))}] 화면")
        extra.append(types.Part.from_bytes(data=data, mime_type="image/jpeg"))
        shown += 1
    if nb or shown:
        log(f"실습 자료 첨부: 노트북 {'있음' if nb else '없음'} · 화면 {shown}장")

    def write(contents, label="", exclude=(), wait=RETRY_WAIT, rounds=ROUNDS):
        def _generate(thinking_budget: int):
            config = types.GenerateContentConfig(
                max_output_tokens=MAX_OUTPUT_TOKENS,
                thinking_config=types.ThinkingConfig(
                    thinking_budget=thinking_budget))
            # 모델이 붐비면 다음 모델로 넘어간다 — 한 강의 요약에 몇 분이 걸리는데
            # 503 하나로 처음부터 다시 돌리게 할 수는 없다.
            return generate(client, contents, config=config, model=model,
                            on_event=log, wait=wait, rounds=rounds,
                            exclude=exclude)

        log(f"{label}요약 생성 중(model={model}, max_tokens={MAX_OUTPUT_TOKENS}, "
            f"thinking={THINKING_BUDGET})…")
        resp = _generate(THINKING_BUDGET)
        text = _resp_text(resp)
        if not text:
            br = _block_reason(resp)
            log(f"⚠️ 빈 응답(finish_reason={_finish_reason(resp)}"
                f"{', block=' + br if br else ''}) → thinking 끄고 1회 재시도")
            resp = _generate(0)  # thinking 비활성 → 출력 예산 전부 본문에
            text = _resp_text(resp)
            if not text:
                log(f"⚠️ 재시도도 빈 응답(finish_reason={_finish_reason(resp)})")
        return text

    split = bool(split_practice and has_audio)
    if split:
        theory_contents = files + [build_theory_prompt(subject, seq, name)]
        practice_contents = files + extra + [build_practice_prompt(
            subject, seq, name, duration=duration, notebook=bool(nb),
            screens=bool(shown))]

        def compose(**kw):
            theory = write(theory_contents, "[이론] ", **kw)
            if not theory:
                return ""
            practice = write(practice_contents, "[실습] ", **kw)
            if not practice:
                log("⚠️ 실습 부분을 받지 못해 이론 부분만 씁니다")
            return merge_practice(theory, practice)
    else:
        contents = files + extra + [build_prompt(
            subject, seq, name, has_audio=has_audio,
            duration=duration if has_audio else None,
            notebook=bool(nb), screens=bool(shown))]

        def compose(**kw):
            return write(contents, **kw)

    text = compose()

    # 덜 쓴 노트 — 붐빌 때 가벼운 모델이 받으면 긴 강의를 앞부분만 얕게 쓴다
    # (실측: 2강 69분을 flash-lite 가 35분까지 3천 자로). 가벼운 모델을 빼고
    # 조금 기다렸다가 한 번 더 쓰게 하고, 더 많이 다룬 쪽을 고른다.
    cov = note_coverage(text, duration if has_audio else None)
    if text and cov is not None and cov < COVER_MIN:
        log(f"⚠️ 노트가 음성의 {cov:.0%}까지만 다룹니다 → 가벼운 모델을 빼고 "
            "다시 씁니다")
        try:
            again = compose(exclude=light_models(model), wait=RETRY_SLOW_WAIT,
                            rounds=ROUNDS + 1)
        except Exception as e:  # noqa: BLE001 - 첫 노트라도 남긴다
            log(f"   다시 쓰지 못했습니다: {str(e)[:80]}")
            again = ""
        cov2 = note_coverage(again, duration)
        if again and (cov2 or 0) > cov:
            log(f"   다시 쓴 노트가 {cov2:.0%}까지 다룹니다 — 이쪽을 씁니다")
            text = again
    return text


COVER_MIN = 0.6         # 마지막 🎬 이 음성의 이 비율보다 앞이면 덜 쓴 노트
RETRY_SLOW_WAIT = 20.0  # 덜 쓴 노트를 다시 쓸 때 모델 사이에 기다리는 시간(초)


def light_models(model=None) -> list:
    """긴 노트를 맡기기엔 가벼운 모델들(이름에 'lite')."""
    return [m for m in model_chain(model) if "lite" in m]


def note_coverage(markdown, duration):
    """노트가 음성의 어디까지 다루나 — 마지막 🎬 마커 ÷ 음성 길이(모르면 None)."""
    try:
        total = float(duration)
    except (TypeError, ValueError):
        return None
    if total <= 0:
        return None
    secs = [timestamp_to_seconds(t) for t in _TS_RE.findall(str(markdown or ""))]
    return (max(secs) / total) if secs else 0.0


SECRET_PLACEHOLDER = "[발급받은 인증키]"
# 이름이 key·token·secret·password 류인 변수나 인자에 긴 문자열이 들어간 자리.
# 실습 화면에는 강사가 발급받은 실제 인증키가 그대로 보인다(실측: 5강 공공데이터
# 포털 serviceKey) — 노트로 옮겨 적으면 남의 키를 퍼뜨리게 된다.
_SECRET_RE = re.compile(
    r"""(?ix)
    (\b[\w.\[\]'"]*?(?:api_?key|service_?key|secret|token|passw(?:or)?d|pwd)
       [\w\]'"]*\s*[:=]\s*)          # 이름과 = 또는 :
    (['"])([^'"\s]{12,})\2           # 따옴표 안의 긴 값
    """)


_DOUBLE_HEAD_RE = re.compile(r"^(#{1,6})[ \t]+#{1,6}[ \t]+", re.M)


def tidy_headings(markdown: str) -> str:
    """'## ## 실습' 처럼 제목 기호가 겹친 줄을 바로잡는다.

    지시문에 `## 실습` 이라고 적어 두었더니 모델이 그 글자를 그대로 제목에
    붙여 썼다(실측: 2강 '## ## 실습: 데이터 분석을 위한 파이썬 1').
    """
    return _DOUBLE_HEAD_RE.sub(r"\1 ", str(markdown or ""))


def mask_secrets(markdown: str) -> str:
    """노트 속 인증키·토큰 값을 가린다 — 이미 가린 자리는 그대로 둔다."""
    def _sub(m):
        if m.group(3).startswith("["):
            return m.group(0)
        return f"{m.group(1)}{m.group(2)}{SECRET_PLACEHOLDER}{m.group(2)}"
    return _SECRET_RE.sub(_sub, str(markdown or ""))


def save_summary(markdown: str, out_dir, subject, seq, name, duration=None) -> dict:
    """요약 .md + 타임스탬프 사이드카 .timestamps.json 저장. 경로 dict 반환.

    duration(매체 길이, 초)을 주면 Gemini 의 'MM:SS:00' 오형식 마커를 미리 교정해
    저장한다(노트 본문·timestamps.json 모두 올바른 시각으로 통일).
    화면에서 옮겨 온 인증키·토큰 값은 가리고(mask_secrets), 겹친 제목 기호는
    바로잡는다(tidy_headings).
    """
    from note_embed import write_note
    if not str(markdown or "").strip():
        # 빈 응답으로 멀쩡한 노트를 덮으면 되돌릴 수 없다
        raise ValueError("빈 노트는 저장하지 않습니다")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = tidy_headings(mask_secrets(
        normalize_markdown_timestamps(markdown, duration)))
    md_path = out_dir / note_filename(subject, seq, name)
    # write_note 가 이미지 임베드 폭을 맞춰 준다 — Gemini 응답에 임베드가
    # 섞여 들어와도 폭이 빠지지 않게 하는 것이 여기 있는 이유다.
    markdown = write_note(md_path, markdown)

    ts = extract_timestamps(markdown)
    ts_path = md_path.with_suffix(".timestamps.json")
    ts_path.write_text(json.dumps(
        {"subject": subject, "seq": seq, "name": name, "timestamps": ts},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"md": str(md_path), "timestamps": str(ts_path), "ts_count": len(ts)}
