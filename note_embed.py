"""[note_embed] 예습 노트의 이미지 임베드 규약 한 곳.

옵시디언은 `![[그림.jpg|695]]` 처럼 파일명 뒤에 폭(px)을 적으면 그 크기로
보여준다. 폭을 안 적으면 원본 해상도 그대로 나와 캡처마다 크기가 들쭉날쭉하고
본문 폭을 넘친다. **이미지 파일은 건드리지 않고** 표시 크기만 정한다.

  - embed_text(fn)              : 파일명 → `![[fn|695]]`
  - embed_name(line)            : 임베드 한 줄 → 파일명(폭 제외)
  - embed_names(markdown)       : 노트의 임베드 파일명 집합
  - set_embed_width(md, width)  : 노트의 모든 임베드 폭을 맞춘다
  - write_note(path, markdown)  : **노트 저장의 관문** — 폭을 맞춘 뒤 쓴다

노트를 만드는 길은 여럿이다(Gemini 요약 저장 · 캡처 반영 · 덱 매칭 반영 ·
타임스탬프 교정). 임베드를 만드는 곳마다 폭을 챙기면 새 경로가 생길 때 빠지기
쉬우므로, **저장이라는 하나의 길목**에서 보장한다.

이 모듈은 아무 프로젝트 모듈도 import 하지 않는다 — summarize 와 capture 가
둘 다 여기서 가져다 쓰기 때문이다(capture → summarize 방향이 이미 있어서,
반대로 두면 순환이 된다).
"""
from __future__ import annotations

import re
from pathlib import Path

# 옵시디언 임베드 폭(px) — 노트에 넣는 모든 이미지에 이 폭을 붙인다.
EMBED_WIDTH = 695

# 임베드에서 **파일명만** 뽑는다 — 폭 지정(`|695`)은 떼어 낸다.
# ⚠️ 이걸 안 떼면 capture.orphan_captures 가 참조 중인 캡처를 '아무도 안 쓴다'고
#    판단해 **지워 버린다**. 임베드 파일명이 필요한 곳은 반드시 이걸 쓴다.
_EMBED_NAME_RE = re.compile(r"!\[\[([^\]|]+?)\s*(?:\|[^\]]*)?\]\]")


def embed_text(filename: str, width: int = EMBED_WIDTH) -> str:
    """파일명 → 노트에 넣을 임베드 한 줄. width 가 0 이하면 폭을 붙이지 않는다."""
    fn = str(filename or "")
    return f"![[{fn}|{int(width)}]]" if width and int(width) > 0 else f"![[{fn}]]"


def embed_name(line: str) -> str | None:
    """임베드 한 줄 → 파일명(폭 지정 제외). 임베드가 아니면 None."""
    m = _EMBED_NAME_RE.search(str(line or ""))
    return m.group(1).strip() if m else None


def embed_names(markdown: str) -> set[str]:
    """노트에 임베드된 파일명 집합(폭 지정 제외)."""
    return {n.strip() for n in _EMBED_NAME_RE.findall(str(markdown or ""))}


def set_embed_width(markdown: str, width: int = EMBED_WIDTH) -> str:
    """노트의 모든 이미지 임베드 폭을 width 로 맞춘다(파일명은 그대로).

    폭이 없던 것에는 붙이고, 다른 폭이 붙어 있으면 바꾼다. width 가 0 이하면
    폭 지정을 모두 뗀다. 이미 그 폭이면 글자 하나 바뀌지 않는다(멱등).
    """
    return _EMBED_NAME_RE.sub(
        lambda m: embed_text(m.group(1).strip(), width), str(markdown or ""))


def write_note(path, markdown: str, width: int = EMBED_WIDTH) -> str:
    """예습 노트를 저장한다 — **임베드 폭을 맞춘 뒤에** 쓴다.

    노트를 쓰는 곳은 모두 이 함수를 거친다. 그래야 어느 경로로 만들어졌든
    (Gemini 응답에 임베드가 섞여 있어도) 폭이 빠지지 않는다.
    return: 실제로 저장한 본문(호출부가 이어서 쓸 수 있게).
    """
    text = set_embed_width(markdown, width)
    Path(path).write_text(text, encoding="utf-8")
    return text
