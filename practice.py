"""[practice] 실습 자료 — 강의 후반부의 코딩 실습을 노트에 담기 위해.

오픈소스기반데이터분석은 슬라이드 설명이 끝난 뒤(5강은 26분부터) 강사가
Colab 노트북의 빈칸을 채워 가며 코드를 실행한다. 그런데 요약 모델이 받는
것은 음성과 강의록(PDF)뿐이었고, 강의록에는 실습이 한 줄 소개뿐이라 노트가
슬라이드가 끝나는 곳에서 함께 끝났다(5강: 57분 강의의 26분까지).

그래서 실습이 있는 과목은 두 가지를 더 넘긴다:
  · 실습 노트북 — 강의에서 쓰는 빈칸 실습지(GitHub 공개 저장소). 단계 번호와
    제목, 주어진 코드, 채워야 할 자리(주석만 있는 칸)를 알려 준다.
  · 화면 사진 — 강사가 코드를 쳐 넣는 화면. 음성만으로는 코드를 정확히 옮길
    수 없다. 캡처 단계가 쓰는 1초 간격 프레임에서 골라 쓴다.

순수 로직(단위테스트 대상):
  - source_for(course)              : 이 과목의 실습 자료 설정(없으면 None)
  - raw_urls(course, seq)           : 노트북을 받을 주소들(앞의 것부터)
  - notebook_text(nb)               : 노트북 → 모델에 줄 글(마크다운)
  - pick_screens(samples, cap)      : 뽑은 장면 중 보여 줄 것 고르기
  - frames_stamp / stamp_matches    : 프레임 폴더가 어느 강의 것인가

IO:
  - fetch_notebook(course, seq, dest_dir) : 받아서 내려받기 폴더에 둔다
  - screen_frames(frames_dir, …)          : [(초, 경로)]
  - write_stamp / read_stamp
"""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

# 과목 → 실습 노트북이 있는 공개 저장소(앞의 것부터 찾는다)와 파일 이름.
# 사용자 저장소가 먼저다(알려 준 곳). 그것이 늦게 따라오면 원본(정재화 교수)에서.
PRACTICE_SOURCES = {
    "오픈소스기반데이터분석": {
        "repos": ("slowdive15/Data-Analysis-with-Open-Source",
                  "jaehwachung/Data-Analysis-with-Open-Source"),
        "file": "오픈소스_데이터_분석_{seq}강.ipynb",
    },
}

SCREEN_EVERY = 15        # 몇 초마다 한 장씩 볼지
SCREEN_MAX = 90          # 한 강의에 넘길 화면 수 상한(토큰 예산)
SCREEN_SAME = 4          # 해시가 이만큼도 안 다르면 같은 화면으로 친다
CODE_OUTPUT_CHARS = 600  # 노트북 셀 출력은 이만큼만
STAMP_NAME = "_stamp.json"


def _norm(text) -> str:
    return "".join(str(text or "").split())


def source_for(course):
    """이 과목의 실습 자료 설정 — 없으면 None(대부분의 과목)."""
    want = _norm(course)
    for name, src in PRACTICE_SOURCES.items():
        if _norm(name) == want:
            return src
    return None


def raw_urls(course, seq) -> list:
    """노트북을 받을 주소들 — raw.githubusercontent.com(로그인 없이 받는다)."""
    src = source_for(course)
    if not src:
        return []
    name = urllib.parse.quote(src["file"].format(seq=int(seq)))
    return [f"https://raw.githubusercontent.com/{repo}/HEAD/{name}"
            for repo in src["repos"]]


def notebook_text(nb) -> str:
    """노트북(dict) → 모델에 줄 글. 마크다운 칸은 그대로, 코드 칸은 코드 블록.

    Colab 배지 같은 링크 줄은 뺀다(읽을 것이 없다). 출력이 있는 노트북이면
    글 출력만 짧게 붙인다.
    """
    out = []
    for cell in (nb or {}).get("cells") or []:
        src = "".join(cell.get("source") or "").strip()
        kind = cell.get("cell_type")
        if kind == "markdown":
            if src and not src.startswith("<a href"):
                out.append(src)
        elif kind == "code":
            out.append(f"```python\n{src}\n```" if src else "```python\n```")
            texts = []
            for o in cell.get("outputs") or []:
                t = o.get("text") or (o.get("data") or {}).get("text/plain")
                if t:
                    texts.append("".join(t) if isinstance(t, list) else str(t))
            if texts:
                body = "".join(texts).strip()[:CODE_OUTPUT_CHARS]
                out.append(f"출력:\n```\n{body}\n```")
    return "\n\n".join(out)


def pick_screens(samples, cap: int = SCREEN_MAX, same: int = SCREEN_SAME,
                 hamming=None) -> list:
    """일정 간격으로 뽑은 [(초, 해시)] → 보여 줄 장면의 초 목록.

    바로 앞에 고른 장면과 거의 같으면(강사가 말만 하고 화면은 그대로)
    건너뛴다. 그래도 cap 을 넘으면 고르게 솎는다.
    """
    dist = hamming or (lambda a, b: bin(a ^ b).count("1"))
    picked = []
    last = None
    for sec, h in samples or []:
        if last is not None and dist(h, last) <= same:
            continue
        picked.append(sec)
        last = h
    if len(picked) > cap:
        step = len(picked) / cap
        picked = [picked[int(i * step)] for i in range(cap)]
    return picked


def frames_stamp(course, seq) -> dict:
    """프레임 폴더 꼬리표 — frames_5 는 과목이 달라도 같은 이름이다."""
    return {"course": _norm(course), "seq": int(seq)}


def stamp_matches(stamp, course, seq) -> bool:
    want = frames_stamp(course, seq)
    return bool(stamp) and stamp.get("course") == want["course"] \
        and stamp.get("seq") == want["seq"]


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def notebook_path(dest_dir, course, seq) -> Path:
    from download import build_filename
    return Path(dest_dir) / build_filename(course, seq, "ipynb")


def fetch_notebook(course, seq, dest_dir, timeout: float = 20.0,
                   opener=None):
    """실습 노트북을 받아 둔다 → 경로(이 과목에 실습 자료가 없거나 못 받으면 None).

    한 번 받은 것은 다시 받지 않는다. 공개 저장소에서 읽기만 한다.
    """
    urls = raw_urls(course, seq)
    if not urls:
        return None
    out = notebook_path(dest_dir, course, seq)
    if out.exists() and out.stat().st_size > 0:
        return out
    get = opener or (lambda u: urllib.request.urlopen(u, timeout=timeout).read())
    for url in urls:
        try:
            data = get(url)
            json.loads(data.decode("utf-8"))          # 노트북이 맞는지
        except Exception:  # noqa: BLE001 - 다음 저장소에서 찾는다
            continue
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(data)
        return out
    return None


def load_notebook_text(path) -> str:
    try:
        return notebook_text(json.loads(Path(path).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return ""


def read_stamp(frames_dir):
    try:
        return json.loads((Path(frames_dir) / STAMP_NAME).read_text(
            encoding="utf-8"))
    except (OSError, ValueError):
        return None


def clear_stamp(frames_dir) -> None:
    """화면을 새로 뽑기 전에 꼬리표를 뗀다 — 도중에 멈추면 '이 강의 것' 이라는
    꼬리표가 다른 강의의 반쪽 화면에 붙어 남는다."""
    try:
        (Path(frames_dir) / STAMP_NAME).unlink()
    except OSError:
        pass


def write_stamp(frames_dir, course, seq) -> None:
    p = Path(frames_dir) / STAMP_NAME
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(frames_stamp(course, seq), ensure_ascii=False),
                 encoding="utf-8")


def screen_frames(frames_dir, every: int = SCREEN_EVERY,
                  cap: int = SCREEN_MAX) -> list:
    """프레임 폴더(f_000001.jpg = 0초) → 보여 줄 화면 [(초, 경로)].

    every 초마다 한 장만 해시를 잰다(3천 장을 다 잴 까닭이 없다).
    """
    from deck_match import dhash, hamming

    frames = sorted(Path(frames_dir).glob("f_*.jpg"))
    if not frames:
        return []
    step = max(1, int(every))
    samples = [(sec, dhash(frames[sec])) for sec in range(0, len(frames), step)]
    return [(sec, frames[sec])
            for sec in pick_screens(samples, cap, hamming=hamming)]
