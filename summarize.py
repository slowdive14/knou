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
    """Gemini에 보낼 한국어 요약 지시문."""
    return f"""너는 한국방송통신대학교 '{subject}' {seq}강 '{name}'의 학습 도우미다.
첨부한 **강의 음성(MP3)**과 **강의록(PDF)**을 함께 분석해, 예습/복습용 **한국어 마크다운 요약 노트**를 작성하라.

요구사항:
1. 구조: `# {subject} {seq}강 - {name}` 제목으로 시작하고, 강의 흐름에 따라 `##` 대주제, `###` 핵심 개념으로 나눈다.
2. 각 핵심 개념마다:
   - **정의/핵심 설명**을 간결히
   - 왜 중요한지 / 시험·응용 포인트
   - 그 개념이 **음성에서 설명되기 시작하는 위치**를 `🎬 [HH:MM:SS]` 형식으로 표기(음성 기준).
   - 가능하면 강의록 **추정 페이지**를 `(교재 p.N)`로 덧붙인다.
3. 타임스탬프는 **음성 기준 근사치**이며 정확하지 않아도 된다. 단 형식은 반드시 `[HH:MM:SS]`(시:분:초)로 통일하라.
4. 수식/기호는 가능하면 KaTeX 인라인(`$...$`)으로. 표·목록을 적절히 사용.
5. 마지막에 `## 핵심 요약` 으로 3~6개 bullet 정리.
6. 사족/머리말 없이 **마크다운 본문만** 출력하라(코드펜스로 감싸지 말 것)."""


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


def save_summary(markdown: str, out_dir, subject, seq, name) -> dict:
    """요약 .md + 타임스탬프 사이드카 .timestamps.json 저장. 경로 dict 반환."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    md_path = out_dir / note_filename(subject, seq, name)
    md_path.write_text(markdown, encoding="utf-8")

    ts = extract_timestamps(markdown)
    ts_path = md_path.with_suffix(".timestamps.json")
    ts_path.write_text(json.dumps(
        {"subject": subject, "seq": seq, "name": name, "timestamps": ts},
        ensure_ascii=False, indent=1), encoding="utf-8")
    return {"md": str(md_path), "timestamps": str(ts_path), "ts_count": len(ts)}
