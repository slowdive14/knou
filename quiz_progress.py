"""[quiz_progress] 퀴즈 풀이 기록 — 틀린 것부터 다시 내기 위한 최소 장치.

지금까지 푼 답은 화면 메모리에만 있어서 앱을 끄면 사라졌다. 기출을 **반복해서**
풀려면 무엇을 맞혔고 무엇을 틀렸는지 남아야 하고, 다시 낼 때는 **틀린 것이 먼저**
나와야 한다.

기록은 문항 하나당 이렇게 생겼다:

    {"tries": 3, "correct": 2, "streak": 1,
     "last": "2026-09-21T10:00:00", "last_ok": true}

`streak` 은 연속 정답 수다. 연속으로 맞힐수록 다음에 다시 낼 때까지의 간격이
길어진다(1일 → 3일 → 7일 → 14일 → 30일). 틀리면 0 으로 돌아가 곧바로 다시 나온다.

순수 로직(단위테스트 대상):
  - record_key(bank, qid)        : 기록 키 — 은행이 달라도 안 섞이게
  - mark(rec, ok, now)           : 한 문항을 풀었을 때의 새 기록
  - due_at(rec) / is_due(rec, now): 언제 다시 낼지 / 지금 낼 때인가
  - sort_key(rec, now)           : 출제 순서(틀린 것 → 안 푼 것 → 복습)
  - pick(questions, prog, …)     : 모드에 맞춰 걸러 정렬한 문항
  - bank_stats(questions, prog, …): '25문항 중 18개 맞음 · 오답 4'

IO:
  - load(path) / save(path, prog) : 볼트의 퀴즈 폴더에 JSON 한 장

⚠️ 사람의 학습 기록이라 지워지면 되돌릴 수 없다 — 저장은 임시 파일에 쓴 뒤
   바꿔치기해서, 도중에 멈춰도 이전 기록이 남게 한다.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path

PROGRESS_NAME = "_풀이기록.json"

# 연속 정답 수 → 다음에 다시 낼 때까지의 날짜. 마지막 값을 넘으면 그대로 쓴다.
INTERVALS_DAYS = (1, 3, 7, 14, 30)

# 출제 순서에서 쓰는 묶음(작을수록 먼저 나온다)
GROUP_WRONG = 0     # 틀린 채로 남아 있는 것
GROUP_NEW = 1       # 아직 한 번도 안 푼 것
GROUP_DUE = 2       # 맞혔지만 다시 볼 때가 된 것
GROUP_LATER = 3     # 아직 이른 것

MODES = ("all", "wrong", "due")


def record_key(bank, qid) -> str:
    """기록 키. 회차가 달라도 문항 번호가 겹치므로 은행을 함께 적는다."""
    if isinstance(bank, dict):
        name = f"{bank.get('course', '')}|{bank.get('seq', '')}"
    else:
        name = str(bank or "")
    return f"{name}|{qid}"


def blank() -> dict:
    """아직 한 번도 안 푼 기록."""
    return {"tries": 0, "correct": 0, "streak": 0, "last": "", "last_ok": None}


def _now(now=None) -> datetime:
    return now or datetime.now()


def _parse(ts):
    """ISO 문자열 → datetime. 못 읽으면 None."""
    try:
        return datetime.fromisoformat(str(ts))
    except (TypeError, ValueError):
        return None


def mark(rec, ok: bool, now=None) -> dict:
    """한 문항을 풀었다 → 새 기록(원본은 건드리지 않는다).

    틀리면 `streak` 이 0 으로 돌아가 곧바로 다시 나온다.
    """
    r = dict(rec or blank())
    ok = bool(ok)
    r["tries"] = int(r.get("tries") or 0) + 1
    r["correct"] = int(r.get("correct") or 0) + (1 if ok else 0)
    r["streak"] = (int(r.get("streak") or 0) + 1) if ok else 0
    r["last"] = _now(now).isoformat(timespec="seconds")
    r["last_ok"] = ok
    return r


def interval_days(streak: int) -> int:
    """연속 정답 수 → 다음까지 비워 둘 날짜(0 이면 곧바로 다시)."""
    s = int(streak or 0)
    if s <= 0:
        return 0
    return INTERVALS_DAYS[min(s, len(INTERVALS_DAYS)) - 1]


def due_at(rec):
    """다시 낼 시각. 아직 안 풀었거나 틀린 상태면 None(=지금 바로)."""
    r = rec or {}
    if not int(r.get("tries") or 0):
        return None
    last = _parse(r.get("last"))
    if last is None:
        return None
    days = interval_days(r.get("streak"))
    return None if days <= 0 else last + timedelta(days=days)


def is_due(rec, now=None) -> bool:
    """지금 이 문항을 낼 때인가."""
    at = due_at(rec)
    return True if at is None else _now(now) >= at


def group_of(rec, now=None) -> int:
    """이 문항이 어느 묶음인가(출제 순서용)."""
    r = rec or {}
    if not int(r.get("tries") or 0):
        return GROUP_NEW
    if not r.get("last_ok"):
        return GROUP_WRONG
    return GROUP_DUE if is_due(r, now) else GROUP_LATER


def sort_key(rec, now=None) -> tuple:
    """출제 순서 — 틀린 것 먼저, 그 안에서는 오래 안 본 것부터."""
    r = rec or {}
    last = _parse(r.get("last"))
    return (group_of(r, now), last or datetime.min)


def pick(questions, progress, bank, mode: str = "all", now=None) -> list:
    """모드에 맞춰 문항을 걸러 **출제 순서대로** 돌려준다.

    all   : 전부(틀린 것부터)
    wrong : 틀린 채로 남아 있는 것만
    due   : 지금 볼 때가 된 것(안 푼 것·틀린 것·간격이 찬 것)
    """
    prog = progress or {}
    rows = [(q, prog.get(record_key(bank, q.get("qid"))) or blank())
            for q in (questions or [])]
    if mode == "wrong":
        rows = [(q, r) for q, r in rows if group_of(r, now) == GROUP_WRONG]
    elif mode == "due":
        rows = [(q, r) for q, r in rows if group_of(r, now) != GROUP_LATER]
    rows.sort(key=lambda x: sort_key(x[1], now))
    return [q for q, _ in rows]


def bank_stats(questions, progress, bank, now=None) -> dict:
    """은행 하나의 학습 현황 — 화면 머리말에 쓴다."""
    prog = progress or {}
    total = len(questions or [])
    seen = solved = wrong = due = 0
    for q in questions or []:
        r = prog.get(record_key(bank, q.get("qid"))) or blank()
        if int(r.get("tries") or 0):
            seen += 1
            if r.get("last_ok"):
                solved += 1
            else:
                wrong += 1
        g = group_of(r, now)
        if g != GROUP_LATER:
            due += 1
    return {"total": total, "seen": seen, "solved": solved,
            "wrong": wrong, "due": due}


def stats_text(s) -> str:
    """'25문항 · 맞힘 18 · 오답 4 · 아직 3' — 빈 은행이면 빈 문자열."""
    s = s or {}
    total = int(s.get("total") or 0)
    if not total:
        return ""
    parts = [f"{total}문항", f"맞힘 {int(s.get('solved') or 0)}"]
    if s.get("wrong"):
        parts.append(f"오답 {int(s['wrong'])}")
    left = total - int(s.get("seen") or 0)
    if left:
        parts.append(f"아직 {left}")
    return " · ".join(parts)


# ---------------------------------------------------------------------------
# 저장 (IO)
# ---------------------------------------------------------------------------
def progress_path(quiz_dir) -> Path:
    """기록 파일 경로 — 퀴즈 은행과 같은 폴더에 둔다."""
    return Path(quiz_dir) / PROGRESS_NAME


def load(path) -> dict:
    """기록을 읽는다. 없거나 깨졌으면 빈 기록(학습을 막지 않는다)."""
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save(path, progress) -> Path:
    """기록을 저장한다 — 임시 파일에 쓴 뒤 바꿔치기한다.

    ⚠️ 사람이 쌓은 학습 기록이라 도중에 멈춰 반쪽짜리 파일이 남으면 되돌릴 수
    없다. 먼저 옆에 쓰고 마지막에 이름을 바꿔 그 위험을 없앤다.
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(json.dumps(progress or {}, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    os.replace(tmp, p)
    return p
