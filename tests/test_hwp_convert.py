"""HWP → PDF — 읽을 수 있는 것과 없는 것을 정직하게 가른다.

HWP 자체는 읽는다(정답표가 그렇다). 그런데 기출 HWP 는 **배포용 문서**라 본문이
`ViewText` 에 잠겨 있어 olefile 로는 안내문 한 줄만 나온다.

실측: 일반 HWP(정답표)는 '다른 이름으로 저장' 으로 153KB PDF 가 나왔고, 배포용
기출은 저장이 거부됐다. 그런데 배포용도 **인쇄는 허용**한다 — PDF 프린터로
인쇄하니 3쪽 1.2MB PDF 가 나왔고 36~60번 문항이 그대로 있었다.

문서의 권한을 뚫지 않는다. 저장이 막히면 저장하지 않고, 인쇄가 막히면 거기서
멈춰 사람에게 알린다.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import hwp_convert as hc  # noqa: E402

NORMAL = ["\x05HwpSummaryInformation", "BodyText/Section0", "DocInfo",
          "FileHeader", "PrvText"]
DISTRIBUTED = NORMAL + ["ViewText/Section0", "Scripts/DefaultJScript"]


# --- 배포용인가 -------------------------------------------------------------
def test_a_distributed_document_is_recognised():
    assert hc.looks_distributed(DISTRIBUTED)
    assert not hc.looks_distributed(NORMAL)
    assert not hc.looks_distributed([]) and not hc.looks_distributed(None)


def test_a_distribute_record_also_counts():
    assert hc.looks_distributed(["DistributeDocData", "BodyText/Section0"])


def test_the_real_files_are_told_apart():
    """실제 파일로 확인 — 정답표는 일반, 기출은 배포용이다."""
    normal = Path("downloads/_기출/정답표/2015/2015. 1학기 기말시험정답표.hwp")
    exam = Path("downloads/_기출/231-자료구조-2학년-3교시-3P.hwp")
    if not normal.exists() or not exam.exists():
        return                                  # 받아 둔 자료가 없으면 건너뛴다
    assert not hc.is_distributed(normal)
    assert hc.is_distributed(exam)


# --- 직접 넣어 주는 PDF ------------------------------------------------------
def test_the_manual_name_says_which_round_it_is():
    assert hc.manual_name("자료구조", 2016, 2) == "자료구조_2016-2.pdf"
    assert hc.manual_name("C프로그래밍", 2014, 1) == "C프로그래밍_2014-1.pdf"


def test_a_manual_pdf_is_found_when_it_is_there(tmp_path):
    d = hc.manual_dir(tmp_path)
    (d / "자료구조_2016-2.pdf").write_bytes(b"%PDF-1.4 ...")
    assert hc.manual_pdf(tmp_path, "자료구조", 2016, 2) is not None
    assert hc.manual_pdf(tmp_path, "자료구조", 2015, 2) is None


def test_an_empty_manual_pdf_does_not_count(tmp_path):
    """0바이트 파일을 쓰면 비전이 빈 시험지를 읽게 된다."""
    d = hc.manual_dir(tmp_path)
    (d / "자료구조_2016-2.pdf").write_bytes(b"")
    assert hc.manual_pdf(tmp_path, "자료구조", 2016, 2) is None


def test_the_manual_folder_is_made_on_demand(tmp_path):
    d = hc.manual_dir(tmp_path)
    assert d.exists() and d.name == hc.MANUAL_DIR


# --- 왜 안 됐는지 사람 말로 --------------------------------------------------
def test_the_note_says_it_printed_a_distributed_file():
    """배포용은 저장이 막혀 인쇄로 돌아간다 — 그 사실을 밝힌다."""
    assert "인쇄" in hc.convert_note({"ok": True, "printed": True})


def test_the_note_tells_what_to_do_when_even_printing_fails():
    got = hc.convert_note({"ok": False, "distributed": True, "why": "거부"})
    assert "배포용" in got and "PDF로 인쇄" in got and hc.MANUAL_DIR in got


def test_the_note_says_when_hangul_is_missing():
    assert "한글이 설치돼" in hc.convert_note({"ok": False, "no_hangul": True})


def test_the_note_is_short_when_it_worked():
    assert hc.convert_note({"ok": True}) == "한글로 PDF 변환했습니다"


# --- 변환 앞단의 판단 --------------------------------------------------------
def test_a_missing_source_stops_early(tmp_path):
    got = hc.hwp_to_pdf(tmp_path / "없음.hwp", tmp_path / "x.pdf")
    assert not got["ok"] and "원본이 없습니다" in got["why"]


def test_a_distributed_file_still_goes_to_hangul(tmp_path, monkeypatch):
    """인쇄는 허용되므로 한글을 불러 본다 — 미리 포기하지 않는다."""
    src = tmp_path / "a.hwp"
    src.write_bytes(b"dummy")
    monkeypatch.setattr(hc, "is_distributed", lambda p: True)
    monkeypatch.setattr(hc, "has_hangul", lambda: True)
    monkeypatch.setattr(hc, "SHELLS", ())          # 실제로 부르지는 않는다
    got = hc.hwp_to_pdf(src, tmp_path / "x.pdf")
    assert got["ok"] is False and got["distributed"] is True


def test_without_hangul_it_says_so(tmp_path, monkeypatch):
    src = tmp_path / "a.hwp"
    src.write_bytes(b"dummy")
    monkeypatch.setattr(hc, "is_distributed", lambda p: False)
    monkeypatch.setattr(hc, "has_hangul", lambda: False)
    got = hc.hwp_to_pdf(src, tmp_path / "x.pdf")
    assert got["no_hangul"] is True


def test_the_script_is_written_with_a_bom():
    """실측: Windows PowerShell 5.1 은 BOM 없는 UTF-8 스크립트를 못 읽는다."""
    import inspect
    src = inspect.getsource(hc.hwp_to_pdf)
    assert 'encoding="utf-8-sig"' in src


def test_the_newer_shell_is_tried_first():
    assert hc.SHELLS[0] == "pwsh"


def test_the_script_tries_saving_then_printing():
    """저장이 빠르고 글자가 또렷하다 — 인쇄는 막혔을 때의 길이다."""
    assert "FileSaveAsPdf" in hc._PS
    assert "PrinterName" in hc._PS and "PrintToFile" in hc._PS
    assert hc._PS.index("FileSaveAsPdf") < hc._PS.index("PrinterName")


def test_a_pdf_printer_is_named():
    assert "Microsoft Print to PDF" in hc.PDF_PRINTERS


# --- 가져오기가 세 갈래를 다 밟는가 ------------------------------------------
def test_the_importer_tries_manual_then_conversion():
    import inspect

    import build_exam_bank as bx
    src = inspect.getsource(bx.build_one)
    assert "manual_pdf" in src              # 1) 직접 넣어 둔 PDF
    assert "hwp_to_pdf" in src              # 2) 한글 변환
    assert "convert_note" in src            # 3) 왜 안 됐는지


def test_a_round_with_only_hwp_is_no_longer_dismissed(tmp_path):
    """예전에는 'PDF 첨부가 없습니다' 로 끝났다 — 이제 길이 있다."""
    import build_exam_bank as bx
    rows = [{"key": (2016, 2), "pdf": None, "hwp": "a.hwp", "manual": None,
             "ans": "t.hwp", "title": "[2016.2학기 기말시험] 기출문제",
             "post": {}}]
    todo, _skip = bx.plan_imports(rows, tmp_path)
    assert [r["key"] for r in todo] == [(2016, 2)]


def test_a_round_with_nothing_at_all_is_skipped(tmp_path):
    import build_exam_bank as bx
    rows = [{"key": (2016, 2), "pdf": None, "hwp": None, "manual": None,
             "ans": "t.hwp", "title": "[2016.2학기 기말시험] 기출문제",
             "post": {}}]
    todo, skip = bx.plan_imports(rows, tmp_path)
    assert todo == [] and any("PDF 도 HWP 도 없습니다" in w for _r, w in skip)
