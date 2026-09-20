"""[hwp_convert] HWP → PDF — 한글이 설치돼 있을 때만.

기출 자료의 절반 이상이 PDF 가 아니라 HWP 다. HWP 자체는 읽을 수 있고(정답표가
그렇다), 한글이 깔려 있으면 PDF 로도 바꿀 수 있다 — **일반 문서라면.**

기출 HWP 는 대부분 **배포용 문서**다. 본문이 `ViewText` 에 잠겨 있어 olefile
로는 '최신 버전의 한글이 필요합니다' 한 줄만 나오고, 한글에 '다른 이름으로
저장' 을 시켜도 **거부당한다**(실측: 일반 HWP 는 153KB PDF 가 나왔고 배포용은
아무것도 안 나왔다).

⚠️ 그래도 길은 있다. 배포용은 편집·저장을 막지만 **인쇄는 허용한다.** 한글에
   PDF 프린터로 인쇄를 시키면 사람이 손으로 하는 것과 똑같은 결과가 나온다
   (실측: 자료구조 2016-2 → 3쪽 1.2MB PDF, 36~60번이 그대로 있다).

   문서의 권한을 뚫지 않는다. 저장이 막혀 있으면 저장하지 않고, 인쇄가 막혀
   있으면 거기서 멈춰 사람에게 알린다.

순수 로직(단위테스트 대상):
  - looks_distributed(스트림이름들) : 배포용 문서인가
  - manual_name(과목, 연도, 학기)   : 직접 넣어 줄 PDF 의 이름
  - convert_note(결과)              : 어떻게 됐는지 사람 말로

IO:
  - is_distributed(path)  : 파일을 열어 배포용인지 본다
  - has_hangul()          : 한글이 설치돼 있는가(COM 등록 여부)
  - hwp_to_pdf(src, out)  : 저장으로, 안 되면 인쇄로 PDF 를 얻는다
  - manual_pdf(work, …)   : 직접 넣어 둔 PDF 찾기
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

MANUAL_DIR = "직접받은PDF"     # 사람이 한글에서 인쇄해 넣어 두는 자리
# 인쇄로 PDF 를 만들 때 쓸 프린터 — 앞의 것부터 찾아 쓴다
PDF_PRINTERS = ("Microsoft Print to PDF", "Hancom PDF")
HWP_COM = "HWPFrame.HwpObject"
# ⚠️ 그림이 많은 시험지는 인쇄 스풀이 오래 걸린다(실측: 180초로는 컴퓨터구조
#    2016-2·2014-2 가 끊겼다). 넉넉히 준다 — 어차피 한 회차에 한 번뿐이다.
CONVERT_TIMEOUT = 600

# ⚠️ 실측: Windows PowerShell 5.1 은 BOM 없는 UTF-8 스크립트를 잘못 읽어 통째로
#    구문 오류가 난다. 파일은 BOM 을 붙여 쓰고, 새 pwsh 를 먼저 불러 본다.
SHELLS = ("pwsh", "powershell")


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def looks_distributed(names) -> bool:
    """스트림 이름만 보고 배포용 문서인지 가린다.

    배포용은 본문을 `ViewText` 에 잠가 두고 `BodyText` 에는 '최신 버전의 한글이
    필요합니다' 안내문만 남긴다.
    """
    got = [str(n) for n in (names or [])]
    return any(n.startswith("ViewText") or "Distribute" in n for n in got)


def manual_name(course, year, term) -> str:
    """직접 넣어 줄 PDF 의 이름 — 회차를 이름만 보고 알 수 있게."""
    from download import sanitize

    return f"{sanitize(str(course or ''))}_{int(year)}-{int(term)}.pdf"


def convert_note(res) -> str:
    """변환 결과 → 사람이 읽을 한 줄."""
    res = res or {}
    if res.get("ok"):
        return ("한글로 인쇄해 PDF 를 만들었습니다(배포용 문서)"
                if res.get("printed") else "한글로 PDF 변환했습니다")
    why = str(res.get("why") or "")
    if res.get("no_hangul"):
        return "한글이 설치돼 있지 않아 HWP 를 PDF 로 바꾸지 못합니다"
    if res.get("distributed"):
        return (f"배포용 문서라 저장도 인쇄도 되지 않습니다({why[:60]}) — "
                f"한글에서 직접 열어 'PDF로 인쇄' 한 뒤 {MANUAL_DIR} 에 "
                f"넣어 주세요")
    return f"HWP 를 PDF 로 바꾸지 못했습니다: {why[:80]}" if why else \
        "HWP 를 PDF 로 바꾸지 못했습니다"


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------
def is_distributed(path) -> bool:
    """파일을 열어 배포용 문서인지 본다(못 열면 False)."""
    try:
        import olefile
    except ImportError:
        return False
    p = Path(path)
    if not p.exists():
        return False
    try:
        ole = olefile.OleFileIO(str(p))
    except Exception:  # noqa: BLE001 - 손상 파일
        return False
    return looks_distributed("/".join(x) for x in ole.listdir())


def kill_hangul() -> int:
    """멈춰 있는 한글을 정리한다 → 정리한 개수.

    ⚠️ 한 회차에서 한글이 멈추면 **다음 회차까지 막힌다**(실측: 컴퓨터구조
       2016-2 가 멈춘 뒤 2014-2 도 연달아 시간 초과였다). 시간 초과 뒤에는
       반드시 치운다.
    """
    try:
        r = subprocess.run(["taskkill", "/F", "/IM", "Hwp.exe", "/T"],
                           capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return 0
    return (r.stdout or "").count("SUCCESS") + (r.stdout or "").count("성공")


def has_hangul() -> bool:
    """한글이 설치돼 있는가 — COM 개체가 등록돼 있으면 있다고 본다."""
    try:
        import winreg
    except ImportError:
        return False
    try:
        winreg.CloseKey(winreg.OpenKey(winreg.HKEY_CLASSES_ROOT, HWP_COM))
        return True
    except OSError:
        return False


# 한글을 불러 PDF 를 얻는다. 저장이 막혀 있으면 인쇄로 돌아간다.
# ⚠️ 배포용 문서는 '다른 이름으로 저장' 을 거부한다. 인쇄는 허용하므로 PDF
#    프린터로 내보낸다 — 사람이 손으로 하는 것과 같은 길이다.
_PS = r"""
param([string]$Src, [string]$Out, [string]$Printers)
$ErrorActionPreference = 'Stop'
function Wait-File($path, $seconds) {
  for ($i = 0; $i -lt ($seconds * 4); $i++) {
    if ((Test-Path $path) -and ((Get-Item $path).Length -gt 0)) { return $true }
    Start-Sleep -Milliseconds 250
  }
  return (Test-Path $path)
}
try {
  $hwp = New-Object -ComObject HWPFrame.HwpObject
  try { $hwp.RegisterModule("FilePathCheckDLL", "FilePathChecker") | Out-Null } catch {}
  if (-not $hwp.Open($Src, "HWP", "forceopen:true")) { throw "열지 못했습니다" }

  # 1) 저장으로 — 빠르고 글자가 또렷하다
  try {
    $hwp.HAction.GetDefault("FileSaveAsPdf", $hwp.HParameterSet.HFileOpenSave.HSet) | Out-Null
    $hwp.HParameterSet.HFileOpenSave.filename = $Out
    $hwp.HParameterSet.HFileOpenSave.Format = "PDF"
    $hwp.HAction.Execute("FileSaveAsPdf", $hwp.HParameterSet.HFileOpenSave.HSet) | Out-Null
  } catch {}
  if (Wait-File $Out 2) { $hwp.Clear(1) | Out-Null; $hwp.Quit() | Out-Null; "OK SAVED"; exit 0 }

  # 2) 배포용은 저장을 거부한다 — 인쇄는 허용하므로 PDF 프린터로
  $have = (Get-Printer -ErrorAction SilentlyContinue | Select-Object -ExpandProperty Name)
  $use = $null
  foreach ($want in ($Printers -split '\|')) {
    if ($have -contains $want) { $use = $want; break }
  }
  if (-not $use) { throw "PDF 프린터가 없습니다" }
  $set = $hwp.HParameterSet.HPrint
  $hwp.HAction.GetDefault("Print", $set.HSet) | Out-Null
  $set.PrinterName = $use
  $set.PrintToFile = $true
  $set.FileName = $Out
  $hwp.HAction.Execute("Print", $set.HSet) | Out-Null
  $hwp.Clear(1) | Out-Null
  $hwp.Quit() | Out-Null
  if (Wait-File $Out 420) { "OK PRINTED" } else { throw "인쇄해도 파일이 생기지 않았습니다" }
} catch {
  "ERR " + $_.Exception.Message
}
"""


def hwp_to_pdf(src, out, timeout: int = CONVERT_TIMEOUT) -> dict:
    """한글에 시켜 PDF 를 얻는다 → {"ok","printed","why","distributed",…}.

    먼저 '다른 이름으로 저장' 을 해 보고, 거부당하면 **인쇄**로 돌아간다.
    배포용 문서는 저장은 막지만 인쇄는 허용한다 — 사람이 손으로 하는 것과
    같은 길이고, 한글이 문서의 권한을 그대로 지킨다.
    """
    s, o = Path(src), Path(out)
    if not s.exists():
        return {"ok": False, "why": "원본이 없습니다"}
    if not has_hangul():
        return {"ok": False, "no_hangul": True, "why": "한글이 없습니다"}
    dist = is_distributed(s)
    o.parent.mkdir(parents=True, exist_ok=True)
    said = ""
    with tempfile.TemporaryDirectory(prefix="knou_hwp_") as tmp:
        ps = Path(tmp) / "conv.ps1"
        ps.write_text(_PS, encoding="utf-8-sig")     # BOM 을 붙여 쓴다
        for shell in SHELLS:
            try:
                r = subprocess.run(
                    [shell, "-NoProfile", "-ExecutionPolicy", "Bypass",
                     "-File", str(ps), "-Src", str(s.resolve()),
                     "-Out", str(o.resolve()),
                     "-Printers", "|".join(PDF_PRINTERS)],
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=timeout)
            except subprocess.TimeoutExpired:
                kill_hangul()      # 멈춘 한글이 다음 회차까지 막지 않게
                return {"ok": False, "distributed": dist,
                        "why": "한글이 이 파일에서 멈춥니다(시간 초과)"}
            except OSError:
                continue                              # 그 셸이 없다
            said = (r.stdout or "").strip()
            if o.exists() and o.stat().st_size > 0:
                return {"ok": True, "path": str(o),
                        "printed": "PRINTED" in said}
    return {"ok": False, "distributed": dist,
            "why": said.replace("ERR ", "") or "PDF 가 만들어지지 않음"}


def manual_pdf(work, course, year, term):
    """사람이 한글에서 인쇄해 넣어 둔 PDF(없으면 None)."""
    p = Path(work) / MANUAL_DIR / manual_name(course, year, term)
    return p if p.exists() and p.stat().st_size > 0 else None


def manual_dir(work) -> Path:
    """직접 넣어 줄 PDF 를 두는 자리(없으면 만든다)."""
    d = Path(work) / MANUAL_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d
