"""[quizbank] 강의 퀴즈 복습용 문제은행 — 데이터 모델 · 병합 · 저장/로드 (순수).

돌발퀴즈/형성평가에서 캡처한 문항을 표준 형식으로 정규화하고, 같은 문항(qid)은
중복 없이 병합해, 과목·차시별 JSON 으로 보관한다. LMS 스캔(Phase 2)·HTML 생성
(Phase 3)·파이프라인 연동(Phase 4)은 별도 모듈에서 이 모델을 사용한다.

문항 표준 형식(canonical):
    {
      "qid": str,            # 안정 식별자(LMS exqsId 등)
      "source": str,         # "형성평가" | "돌발퀴즈" | ""
      "qtype": str,          # 문항 유형(객관식 등, 선택)
      "question": str,       # 문항 본문
      "options": [{"no": int|None, "text": str}, ...],
      "answer_no": int|None, # 정답 보기 번호
      "answer_text": str,    # 정답 텍스트
      "explanation": str,    # 해설
    }

은행(bank) 형식: {"course", "seq", "name", "questions": [문항...]}.
⚠️ 표준 라이브러리만 사용. 비밀값은 절대 담기지 않는다(문항·정답·해설만).
"""
from __future__ import annotations

import json
from pathlib import Path

# 정답/해설이 '비어있다'고 볼 값들(병합 시 이 값으로는 기존을 덮어쓰지 않는다).
_EMPTY = (None, "", [], {})


def normalize_question(raw: dict) -> dict:
    """임의의 스캔/입력 dict → 표준 문항 dict. 이미 표준이면 멱등.

    qid(또는 exqsId/id)는 필수(식별·중복판정 키). 없으면 ValueError.
    별칭: exqsId/id→qid, stem→question. 누락 필드는 기본값으로 채운다.
    """
    raw = raw or {}
    qid = raw.get("qid") or raw.get("exqsId") or raw.get("id")
    if qid in (None, ""):
        raise ValueError("문항 식별자(qid/exqsId)가 필요합니다")

    options = []
    for o in (raw.get("options") or []):
        o = o or {}
        try:
            no = int(o.get("no"))
        except (TypeError, ValueError):
            no = None
        text = o.get("text")
        options.append({"no": no, "text": "" if text is None else str(text)})

    ans_no = raw.get("answer_no")
    try:
        answer_no = int(ans_no) if ans_no not in (None, "") else None
    except (TypeError, ValueError):
        answer_no = None

    return {
        "qid": str(qid),
        "source": str(raw.get("source") or ""),
        "qtype": str(raw.get("qtype") or ""),
        "question": str(raw.get("question") or raw.get("stem") or "").strip(),
        "options": options,
        "answer_no": answer_no,
        "answer_text": str(raw.get("answer_text") or "").strip(),
        "explanation": str(raw.get("explanation") or "").strip(),
    }


def _prefer(new, old):
    """새 값이 비어있지 않으면 새 값, 아니면 기존 값(최신 우선·빈 값은 무시)."""
    return new if new not in _EMPTY else old


def _merge_one(old: dict, new: dict) -> dict:
    """같은 qid 두 문항 병합 — 새 값이 채워졌으면 갱신, 비었으면 기존 유지."""
    return {
        "qid": old["qid"],
        "source": _prefer(new["source"], old["source"]),
        "qtype": _prefer(new["qtype"], old["qtype"]),
        "question": _prefer(new["question"], old["question"]),
        "options": _prefer(new["options"], old["options"]),
        "answer_no": new["answer_no"] if new["answer_no"] is not None
        else old["answer_no"],
        "answer_text": _prefer(new["answer_text"], old["answer_text"]),
        "explanation": _prefer(new["explanation"], old["explanation"]),
    }


def merge_questions(existing, new) -> list:
    """두 문항 목록을 qid 기준으로 병합(등장 순서 보존, 중복 제거).

    기존 → 신규 순으로 훑어, 같은 qid 는 _merge_one 으로 합치고 처음 본 qid 는
    그 순서대로 결과에 추가한다. 신규의 정답/해설이 기존의 빈 칸을 메운다.
    """
    by_id: dict[str, dict] = {}
    order: list[str] = []
    for q in list(existing or []) + list(new or []):
        q = normalize_question(q)
        if q["qid"] in by_id:
            by_id[q["qid"]] = _merge_one(by_id[q["qid"]], q)
        else:
            order.append(q["qid"])
            by_id[q["qid"]] = q
    return [by_id[i] for i in order]


def make_bank(course: str, seq, name: str, questions) -> dict:
    """과목·차시·이름 + 정규화된 문항 목록으로 은행 dict 생성."""
    return {
        "course": course,
        "seq": int(seq),
        "name": name or "",
        "questions": [normalize_question(q) for q in (questions or [])],
    }


def load_bank(path) -> dict:
    """은행 JSON 로드. 없거나 깨졌으면 빈 은행 반환(questions=[])."""
    p = Path(path)
    empty = {"course": "", "seq": 0, "name": "", "questions": []}
    if not p.exists():
        return empty
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty
    if not isinstance(data, dict):
        return empty
    data.setdefault("questions", [])
    return data


def save_bank(path, bank: dict) -> Path:
    """은행을 UTF-8 JSON 으로 저장(한글 보존). 상위 폴더 자동 생성."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(bank, ensure_ascii=False, indent=1),
                 encoding="utf-8")
    return p


def bank_path(cfg, course: str, seq) -> Path:
    """과목·차시별 은행 경로: {볼트 요약폴더}/퀴즈/{과목}_{seq}강.json."""
    from download import sanitize  # 파일명 안전화 재사용(지연 임포트)
    return Path(cfg.summary_dir) / "퀴즈" / f"{sanitize(course)}_{int(seq)}강.json"
