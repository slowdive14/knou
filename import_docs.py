"""[import_docs] 손에 있는 강의록 파일을 앱이 찾는 이름으로 들여온다.

강의자료실 다운로드는 이따금 통째로 실패한다(실측: 오픈소스기반데이터분석은
15차시 전부 못 받았다). 그럴 때 사람이 직접 모아 둔 PDF 폴더를 그대로 쓰려면
파일명이 앱 규칙과 맞아야 한다:

    오픈소스 기반 데이터분석-07(데이터 전처리 2).pdf
        → downloads/오픈소스기반데이터분석_7강.pdf

  - parse_seq(name)                  : 파일명 → 차시 번호|None (순수)
  - plan_imports(files, course, …)   : 무엇을 어디로 옮길지 계획 (순수)
  - import_docs(src_dir, course, …)  : 계획대로 복사(IO)

복사만 하며 원본은 그대로 둔다. 이미 있는 파일은 overwrite 를 켜지 않는 한
건드리지 않는다 — 애써 받아 둔 강의록을 덮어쓰지 않기 위해서다.
`download.needs_download` 가 크기 0 이 아닌 파일을 '이미 있음'으로 보므로,
한 번 들여오면 이후 실행에서 다운로드 단계가 저절로 건너뛴다.
"""
from __future__ import annotations

import re
import shutil
from pathlib import Path

# 강의록으로 인정하는 확장자 — status_page.DOC_EXTS 와 같은 목록
DOC_EXTS = ("pdf", "pptx", "ppt", "hwpx", "hwp", "zip")

# 'N강'이 있으면 그게 가장 확실한 근거다("…_7강.pdf", "7강 데이터 전처리")
_SEQ_KANG = re.compile(r"(\d{1,2})\s*강")
# 다음은 '제목-07(…)' 처럼 구분기호 뒤에 붙은 번호("…분석-07(데이터 전처리 2)")
_SEQ_DASH = re.compile(r"[-_\s](\d{1,2})\s*[(\[.]")
# 마지막 수단: 이름 어딘가의 두 자리 이하 숫자 하나(여러 개면 포기한다)
_SEQ_ANY = re.compile(r"\d{1,2}")


def parse_seq(name) -> int | None:
    """파일명에서 차시 번호를 뽑는다(못 뽑으면 None).

    확장자와 경로는 떼고 본다. 숫자가 여럿이면 근거가 뚜렷한 것부터 고르고,
    끝내 하나로 좁혀지지 않으면 **찍지 않고 None** 을 돌려준다 — 엉뚱한 차시에
    남의 강의록이 들어가는 편이 못 들여오는 것보다 나쁘다.
    """
    stem = Path(str(name or "")).stem
    for pattern in (_SEQ_KANG, _SEQ_DASH):
        found = pattern.findall(stem)
        if len(set(found)) == 1:
            return _valid(found[0])
    found = _SEQ_ANY.findall(stem)
    if len(set(found)) == 1:
        return _valid(found[0])
    return None


def _valid(text) -> int | None:
    """1~99 사이면 정수로, 아니면 None(0강은 없다)."""
    try:
        n = int(text)
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 99 else None


def target_name(course: str, seq: int, ext: str) -> str:
    """앱이 찾는 강의록 파일명 — download.build_filename 과 같은 규칙."""
    from download import build_filename
    return build_filename(course, int(seq), (ext or "pdf").lstrip(".").lower())


def plan_imports(files, course: str, dest_dir, overwrite: bool = False) -> dict:
    """복사 계획을 세운다(파일을 건드리지 않는다).

    return: {"copy": [(원본, 대상), …],
             "skip": [(원본, 사유), …],   # 이미 있음·번호 못 읽음·중복
             "seqs": {차시: 원본}}
    """
    dest = Path(dest_dir)
    by_seq: dict[int, Path] = {}
    skip: list[tuple[Path, str]] = []
    for f in sorted(Path(p) for p in files):
        if f.suffix.lstrip(".").lower() not in DOC_EXTS:
            continue
        seq = parse_seq(f.name)
        if seq is None:
            skip.append((f, "차시 번호를 읽지 못함"))
            continue
        if seq in by_seq:
            skip.append((f, f"{seq}강이 겹침 — 먼저 찾은 것을 쓴다"))
            continue
        by_seq[seq] = f

    copy: list[tuple[Path, Path]] = []
    for seq in sorted(by_seq):
        src = by_seq[seq]
        out = dest / target_name(course, seq, src.suffix)
        if out.exists() and out.stat().st_size > 0 and not overwrite:
            skip.append((src, f"이미 있음 — {out.name}"))
            continue
        copy.append((src, out))
    return {"copy": copy, "skip": skip, "seqs": by_seq}


def import_docs(src_dir, course: str, dest_dir, overwrite: bool = False,
                dry_run: bool = False, on_event=lambda m: None) -> dict:
    """src_dir 의 강의록을 course 의 차시 이름으로 dest_dir 에 복사한다.

    return: plan_imports 의 계획에 "done"(실제로 복사한 대상 목록)을 더한 dict.
    """
    src = Path(src_dir)
    if not src.is_dir():
        raise NotADirectoryError(f"강의록 폴더가 없습니다: {src}")
    plan = plan_imports(src.iterdir(), course, dest_dir, overwrite)
    done: list[Path] = []
    if not dry_run:
        Path(dest_dir).mkdir(parents=True, exist_ok=True)
        for s, out in plan["copy"]:
            shutil.copy2(s, out)
            done.append(out)
            on_event(f"들여옴: {out.name} ← {s.name}")
    for s, why in plan["skip"]:
        on_event(f"건너뜀: {s.name} — {why}")
    plan["done"] = done
    return plan


def main(argv=None) -> int:
    import argparse
    import sys
    try:    # 윈도우 콘솔 기본 인코딩(CP949)에서 한글 파일명이 깨진다
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - 재설정을 못 해도 복사는 해야 한다
        pass
    ap = argparse.ArgumentParser(
        description="손에 있는 강의록 폴더를 앱이 찾는 이름으로 들여옵니다.")
    ap.add_argument("src", help="강의록이 담긴 폴더")
    ap.add_argument("course", help="과목명(LMS 표기 그대로)")
    ap.add_argument("--dest", default=None, help="받은 파일 폴더(기본: 설정값)")
    ap.add_argument("--overwrite", action="store_true",
                    help="이미 있는 강의록도 덮어쓴다")
    ap.add_argument("--dry-run", action="store_true", help="계획만 보여준다")
    a = ap.parse_args(argv)

    dest = a.dest
    if dest is None:
        from config import load_config
        dest = load_config().downloads_dir
    plan = import_docs(a.src, a.course, dest, overwrite=a.overwrite,
                       dry_run=a.dry_run, on_event=print)
    head = "복사 예정" if a.dry_run else "복사함"
    print(f"{head} {len(plan['copy'])}개 · 건너뜀 {len(plan['skip'])}개 "
          f"→ {dest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
