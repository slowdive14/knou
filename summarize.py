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
import re
import time
from pathlib import Path

from download import sanitize

DEFAULT_MODEL = "gemini-2.5-flash"

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


def build_prompt(subject: str, seq: int, name: str) -> str:
    """Gemini에 보낼 한국어 '예습 학습 노트' 지시문."""
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
7. 사족/머리말 없이 **마크다운 본문만** 출력하라(코드펜스로 감싸지 말 것)."""


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


def summarize_lecture(client, subject, seq, name, mp3_path=None, pdf_path=None,
                      model=DEFAULT_MODEL, on_event=None):
    """MP3+PDF 업로드 → Gemini 요약(마크다운 텍스트) 반환."""
    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    contents = []
    if pdf_path and Path(pdf_path).exists():
        contents.append(upload_and_wait(client, pdf_path, on_event=on_event))
    if mp3_path and Path(mp3_path).exists():
        contents.append(upload_and_wait(client, mp3_path, on_event=on_event))
    contents.append(build_prompt(subject, seq, name))

    log(f"요약 생성 중(model={model})…")
    resp = client.models.generate_content(model=model, contents=contents)
    text = (getattr(resp, "text", None) or "").strip()
    # 혹시 코드펜스로 감싸면 벗겨낸다
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    return text


def save_summary(markdown: str, out_dir, subject, seq, name, duration=None) -> dict:
    """요약 .md + 타임스탬프 사이드카 .timestamps.json 저장. 경로 dict 반환.

    duration(매체 길이, 초)을 주면 Gemini 의 'MM:SS:00' 오형식 마커를 미리 교정해
    저장한다(노트 본문·timestamps.json 모두 올바른 시각으로 통일).
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    markdown = normalize_markdown_timestamps(markdown, duration)
    md_path = out_dir / note_filename(subject, seq, name)
    md_path.write_text(markdown, encoding="utf-8")

    ts = extract_timestamps(markdown)
    ts_path = md_path.with_suffix(".timestamps.json")
    ts_path.write_text(json.dumps(
        {"subject": subject, "seq": seq, "name": name, "timestamps": ts},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"md": str(md_path), "timestamps": str(ts_path), "ts_count": len(ts)}
