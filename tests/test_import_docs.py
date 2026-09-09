"""import_docs 단위테스트 — 손에 있는 강의록을 앱 이름으로 들여오기.

차시 번호 추출(순수)·복사 계획(순수)·실제 복사(임시폴더)를 검증한다.
실측 배경: 오픈소스기반데이터분석은 강의자료실 다운로드가 15차시 전부
실패해, 사람이 따로 모아 둔 PDF 폴더를 그대로 써야 했다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from import_docs import (  # noqa: E402
    import_docs,
    parse_seq,
    plan_imports,
    target_name,
)

COURSE = "오픈소스기반데이터분석"
# 사용자가 실제로 건네준 폴더의 파일명 형식
_REAL = "오픈소스 기반 데이터분석-{:02d}({}).pdf"


# --- 차시 번호 읽기 ---------------------------------------------------------
def test_parse_seq_reads_the_real_file_names():
    assert parse_seq(_REAL.format(1, "데이터 분석과 오픈소스")) == 1
    assert parse_seq(_REAL.format(15, "시계열 데이터 분석")) == 15


def test_parse_seq_is_not_fooled_by_a_number_in_the_title():
    """제목 끝의 '1', '2'(전처리 1·2)를 차시로 착각하면 안 된다."""
    assert parse_seq(_REAL.format(7, "데이터 전처리 2")) == 7
    assert parse_seq(_REAL.format(2, "데이터 분석을 위한 파이썬 프로그래밍 1")) == 2


def test_parse_seq_prefers_the_kang_marker():
    assert parse_seq("오픈소스기반데이터분석_13강.pdf") == 13
    assert parse_seq("3강 데이터 분석 1.pdf") == 3


def test_parse_seq_gives_up_rather_than_guessing():
    # 근거가 갈리면 엉뚱한 차시에 넣느니 건너뛴다
    assert parse_seq("데이터 분석 4 - 5장 정리.pdf") is None
    assert parse_seq("강의록.pdf") is None
    assert parse_seq("") is None


def test_parse_seq_rejects_out_of_range():
    assert parse_seq("0강.pdf") is None


def test_target_name_matches_the_apps_rule():
    from download import build_filename
    assert target_name(COURSE, 7, ".pdf") == build_filename(COURSE, 7, "pdf")
    assert target_name(COURSE, 7, "PDF").endswith("_7강.pdf")


# --- 복사 계획 --------------------------------------------------------------
def _names(pairs):
    return [Path(b).name for _a, b in pairs]


def test_plan_maps_every_lecture(tmp_path):
    files = [tmp_path / _REAL.format(n, f"제목{n}") for n in range(1, 16)]
    plan = plan_imports(files, COURSE, tmp_path / "downloads")
    assert len(plan["copy"]) == 15 and plan["skip"] == []
    assert f"{COURSE}_1강.pdf" in _names(plan["copy"])
    assert f"{COURSE}_15강.pdf" in _names(plan["copy"])


def test_plan_keeps_a_doc_we_already_have(tmp_path):
    """애써 받아 둔 강의록을 덮어쓰지 않는다(overwrite 없이는)."""
    dest = tmp_path / "downloads"
    dest.mkdir()
    (dest / f"{COURSE}_3강.pdf").write_bytes(b"%PDF-1.7 already here")
    files = [tmp_path / _REAL.format(n, "제목") for n in (3, 4)]
    plan = plan_imports(files, COURSE, dest)
    assert _names(plan["copy"]) == [f"{COURSE}_4강.pdf"]
    assert any("이미 있음" in why for _f, why in plan["skip"])


def test_plan_overwrites_when_asked(tmp_path):
    dest = tmp_path / "downloads"
    dest.mkdir()
    (dest / f"{COURSE}_3강.pdf").write_bytes(b"%PDF-1.7 old")
    files = [tmp_path / _REAL.format(3, "제목")]
    plan = plan_imports(files, COURSE, dest, overwrite=True)
    assert _names(plan["copy"]) == [f"{COURSE}_3강.pdf"]


def test_plan_replaces_an_empty_file(tmp_path):
    # 0바이트는 '받다 만 것'이므로 들여와야 한다
    dest = tmp_path / "downloads"
    dest.mkdir()
    (dest / f"{COURSE}_3강.pdf").write_bytes(b"")
    plan = plan_imports([tmp_path / _REAL.format(3, "제목")], COURSE, dest)
    assert _names(plan["copy"]) == [f"{COURSE}_3강.pdf"]


def test_plan_skips_unreadable_and_duplicate_names(tmp_path):
    files = [tmp_path / "강의록.pdf",                 # 번호 못 읽음
             tmp_path / _REAL.format(4, "제목"),
             tmp_path / "오픈소스 4강 보충.pdf"]        # 4강이 겹침
    plan = plan_imports(files, COURSE, tmp_path / "d")
    assert len(plan["copy"]) == 1
    assert len(plan["skip"]) == 2


def test_plan_ignores_other_file_types(tmp_path):
    files = [tmp_path / _REAL.format(4, "제목"), tmp_path / "4강 메모.txt",
             tmp_path / "5강.pptx"]
    plan = plan_imports(files, COURSE, tmp_path / "d")
    assert sorted(_names(plan["copy"])) == sorted(
        [f"{COURSE}_4강.pdf", f"{COURSE}_5강.pptx"])


# --- 실제 복사 --------------------------------------------------------------
def _make(src, n, body=b"%PDF-1.7 hello"):
    p = src / _REAL.format(n, f"제목{n}")
    p.write_bytes(body)
    return p


def test_import_copies_and_leaves_the_source_alone(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "downloads"
    src.mkdir()
    origin = _make(src, 7)
    plan = import_docs(src, COURSE, dest)
    out = dest / f"{COURSE}_7강.pdf"
    assert out.read_bytes() == b"%PDF-1.7 hello"
    assert origin.exists()                    # 원본은 그대로 둔다
    assert plan["done"] == [out]


def test_import_dry_run_writes_nothing(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "downloads"
    src.mkdir()
    _make(src, 7)
    plan = import_docs(src, COURSE, dest, dry_run=True)
    assert plan["copy"] and plan["done"] == []
    assert not dest.exists()


def test_import_reports_what_it_did(tmp_path):
    src, dest = tmp_path / "src", tmp_path / "downloads"
    src.mkdir()
    _make(src, 7)
    (src / "읽을수없는이름.pdf").write_bytes(b"%PDF-1.7")
    said: list[str] = []
    import_docs(src, COURSE, dest, on_event=said.append)
    assert any("들여옴" in m and "_7강.pdf" in m for m in said)
    assert any("건너뜀" in m for m in said)


def test_import_needs_a_real_folder(tmp_path):
    import pytest
    with pytest.raises(NotADirectoryError):
        import_docs(tmp_path / "없는폴더", COURSE, tmp_path / "d")


def test_imported_file_stops_the_downloader(tmp_path):
    """들여온 파일이 있으면 다음 실행에서 다운로드 단계가 건너뛴다."""
    from download import needs_download
    src, dest = tmp_path / "src", tmp_path / "downloads"
    src.mkdir()
    _make(src, 7)
    import_docs(src, COURSE, dest)
    assert needs_download(dest / f"{COURSE}_7강.pdf") is False
