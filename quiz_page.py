"""[quiz_page] 퀴즈 은행 수집 → 복습 HTML 조립/저장 + 캡처 저장 헬퍼.

  - collect_banks(quiz_dir)            : 퀴즈 폴더의 *.json 은행 로드(과목·차시 정렬, 빈 강 제외, 출처·강 표시)
  - build_quiz_page(quiz_dir, title)   : 은행들 → 단일 HTML 문자열
  - write_quiz_page(quiz_dir, out, …)  : HTML 생성 후 파일로 저장
  - persist_questions(cfg, …, questions): 캡처한 문항을 과목·차시 은행에 병합 저장
  - default_quiz_paths(cfg)            : (퀴즈 폴더, 출력 HTML) 기본 경로

순수 조립(collect/build)·병합 저장은 단위테스트. 실제 LMS 캡처 연결은 수동 게이트.
"""
from __future__ import annotations

from pathlib import Path

from quiz_html import render_quiz_html
from quiz_intro import stamp_paths
from quiz_lecture import stamp_origins
from quizbank import bank_path, load_bank, make_bank, merge_questions, save_bank


def drop_suspect(bank) -> dict:
    """검토에서 어긋난 것으로 걸러진 변형 문항을 뺀다.

    물음과 답이 어긋난 문항은 풀수록 잘못 외운다. 파일에는 사유와 함께 남아
    있으니 지워지는 것은 아니다(check_variants.py 참고).
    """
    qs = [q for q in (bank.get("questions") or [])
          if not str(q.get("suspect") or "").strip()]
    if len(qs) == len(bank.get("questions") or []):
        return bank
    return {**bank, "questions": qs}


def collect_banks(quiz_dir) -> list:
    """퀴즈 폴더의 *.json 은행을 로드해 (과목, 차시) 순으로 정렬. 빈 강은 제외."""
    d = Path(quiz_dir)
    if not d.exists():
        return []
    banks = []
    for p in sorted(d.glob("*.json")):
        b = drop_suspect(load_bank(p))
        if b.get("questions"):
            banks.append(b)
    # 과목 안에서 **강의 퀴즈가 먼저, 기출이 나중**. 기출의 seq 는 연도를 눌러
    # 담은 큰 수(20191)라 그냥 섞으면 강의 퀴즈 뒤로 밀리긴 하지만, 뜻을 분명히
    # 해 두는 편이 낫다(나중에 seq 규칙이 바뀌어도 순서가 유지된다).
    banks.sort(key=lambda b: (str(b.get("course", "")),
                              1 if b.get("exam") else 0,
                              int(b.get("seq") or 0)))
    # 문항마다 출처(기록 키)와 강을 붙여 둔다 — 화면도 HTML 도 이 표시를 보고
    # 'N강 모아보기' 를 그린다(파일에는 쓰지 않는다).
    return stamp_paths(stamp_origins(banks), d)


def build_quiz_page(quiz_dir, title: str = "방송대 강의 퀴즈") -> str:
    """퀴즈 폴더 → 단일 자체완결 HTML 문자열(빈 폴더도 안전)."""
    return render_quiz_html(collect_banks(quiz_dir), title=title)


def write_quiz_page(quiz_dir, out_path, title: str = "방송대 강의 퀴즈") -> Path:
    """퀴즈 HTML 을 생성해 out_path 에 UTF-8 로 저장하고 경로 반환."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(build_quiz_page(quiz_dir, title), encoding="utf-8")
    return out


def persist_questions(cfg, course: str, seq, name: str, questions) -> Path | None:
    """캡처한 문항을 과목·차시 은행 JSON 에 병합 저장(빈 입력이면 no-op→None)."""
    if not questions:
        return None
    p = bank_path(cfg, course, seq)
    existing = load_bank(p)
    merged = merge_questions(existing.get("questions", []), questions)
    save_bank(p, make_bank(course, seq, name, merged))
    return p


def default_quiz_paths(cfg) -> tuple[Path, Path]:
    """(퀴즈 은행 폴더, 출력 HTML 경로) 기본값 — 볼트 요약폴더 기준."""
    base = Path(cfg.summary_dir)
    return base / "퀴즈", base / "강의퀴즈.html"
