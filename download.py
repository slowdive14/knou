"""Phase 4 — 강의자료 다운로드 (MP3 음성 + PDF 강의록).

순수 로직(단위테스트 대상):
  - sanitize(name)                  : 파일명 금지문자 치환
  - build_filename(subject,seq,ext) : "{과목}_{seq}강.{ext}"
  - needs_download(path)            : 파일 없음/0바이트면 True
  - build_file_url(sbjt_id,save_nm,real_nm) : 강의자료실 /user_uploading 다운로드 URL
  - match_pdf_post(posts, seq)      : 강의자료실 글목록에서 차시별 강의록 글 찾기

브라우저/네트워크(수동 검증):
  - fetch_data_posts(page, atlc,sbjt,cnts) : 강의자료실 진입 → 글목록 AJAX → list[dict]
  - download_url(ctx, url, dest)           : 인증 세션으로 바이트 다운로드 → 파일 저장
  - download_lecture(ctx, page, lec, subject, posts, dest_dir) : 차시 1개 MP3+PDF

강의자료실 구조(실측 recon_shots/lecturedata_list.json):
  - 게시판: 글마다 bdotNo, 분류(sbjtBdotClcd), 제목, 첨부(apndFileNm:표시명,
    apndFileSaveNm:저장명, 멀티는 ':'로 구분), fileCnt
  - 차시 강의록 = 분류 '강의자료' + 표시명이 'NN-'(0패딩) 또는 'N강'(예: 데이터베이스
    시스템_14강_강의록.pdf) 로 차시 지시. 여러 첨부면 '강의록' 본문 PDF 우선(흑백/체크포인트 후순위)
  - 다운로드 URL: /user_uploading?pathkey=COURSE.DATA&addSavePath={sbjtId}
                  &getfile={저장명}&realFileName={표시명(URL인코딩)}
  - MP3는 lectlist 의 strVidoAudoUrl(Lecture.audio_url)에 절대 URL이 이미 있음
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from urllib.parse import quote

BASE = "https://ucampus.knou.ac.kr"
DATA_LIST_AJAX = "/ekp/user/lectureData/initUCRLectureData.ajax"
MY_STUDY_URL = "https://ucampus.knou.ac.kr/ekp/user/study/retrieveUMYStudy.sdo"

# Windows 파일명 금지문자
_ILLEGAL = re.compile(r'[\\/:*?"<>|]')


# ---------------------------------------------------------------------------
# 순수 로직
# ---------------------------------------------------------------------------
def sanitize(name: str) -> str:
    """파일명에 못 쓰는 문자를 '_'로 치환하고 앞뒤 공백/점을 정리."""
    s = _ILLEGAL.sub("_", name or "")
    # 앞뒤 공백 → 끝 점 제거 → 다시 공백 정리
    return s.strip().strip(".").strip()


def build_filename(subject: str, seq: int, ext: str) -> str:
    """'{과목}_{seq}강.{ext}' 형식의 안전한 파일명."""
    ext = (ext or "").lstrip(".").lower()
    return f"{sanitize(subject)}_{seq}강.{ext}"


def needs_download(path) -> bool:
    """파일이 없거나 0바이트면 True(다운로드 필요)."""
    p = Path(path)
    try:
        return (not p.exists()) or p.stat().st_size == 0
    except OSError:
        return True


def build_file_url(sbjt_id: str, save_nm: str, real_nm: str | None = None,
                   pathkey: str = "COURSE.DATA") -> str:
    """강의자료실 첨부 다운로드 URL(/user_uploading)."""
    url = (f"{BASE}/user_uploading?pathkey={pathkey}"
           f"&addSavePath={sbjt_id}&getfile={save_nm}")
    if real_nm:
        url += "&realFileName=" + quote(real_nm)
    return url


def _ext_of(name: str) -> str:
    name = name or ""
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def _split_files(post: dict):
    """글 1개의 첨부를 [(표시명, 저장명), ...]로 분해(멀티는 ':' 구분)."""
    disp = (post.get("apndFileNm") or "")
    save = (post.get("apndFileSaveNm") or "")
    if not disp or not save:
        return []
    ds = disp.split(":")
    ss = save.split(":")
    return list(zip(ds, ss))


def _seq_in_name(display_nm: str, seq: int) -> bool:
    """첨부 표시명이 해당 차시의 것인지(과목 무관) 판정.

    두 가지 명명 규칙을 모두 인식한다:
      - 'NN-...'  (2자리 0패딩 접두사. 예: 이산수학 '13-정수론.pdf')
      - '..._N강_...' 또는 '...N강...' (예: '데이터베이스시스템_14강_강의록.pdf')
    자릿수 경계를 보호해 seq=4 가 '14강'에, seq=1 이 '11강'에 오매칭되지 않는다.
    """
    if display_nm.startswith(f"{seq:02d}-"):
        return True
    # 앞에 숫자가 붙지 않은 'N강'(0패딩 허용). '_14강','(14강' 등 모두 허용.
    return re.search(rf"(?<!\d)0*{seq}강(?![0-9])", display_nm) is not None


def _pdf_pref_score(display_nm: str) -> int:
    """같은 차시 첨부가 여럿일 때 '강의록' 본문 PDF 를 우선하기 위한 점수."""
    score = 0
    if _ext_of(display_nm) == "pdf":
        score += 4
    if "강의록" in display_nm:
        score += 2
    if "흑백" in display_nm:          # 강의록_흑백 → 후순위
        score -= 1
    if "체크포인트" in display_nm or "체크" in display_nm:
        score -= 2
    return score


def match_pdf_post(posts, seq: int, category: str = "강의자료") -> dict | None:
    """글목록에서 해당 차시의 강의록(본문 PDF) 첨부를 찾는다.

    매칭 규칙: 분류 == category(기본 '강의자료') 이고 표시명이 해당 차시를 가리킴
      (NN- 접두사 또는 'N강' 패턴; _seq_in_name 참고).
    같은 차시 첨부가 여러 개면(강의록/흑백/체크포인트) '강의록' 본문 PDF 를 우선한다.
    반환: {"bdotNo","title","save_nm","display_nm","ext"} 또는 None.
    """
    candidates: list[tuple[int, dict]] = []
    for p in posts or []:
        if (p.get("sbjtBdotClcd") or "") != category:
            continue
        for display_nm, save_nm in _split_files(p):
            if not _seq_in_name(display_nm, seq):
                continue
            candidates.append((_pdf_pref_score(display_nm), {
                "bdotNo": p.get("bdotNo"),
                "title": (p.get("sbjtNotcTitNm") or ""),
                "save_nm": save_nm,
                "display_nm": display_nm,
                "ext": _ext_of(display_nm) or "pdf",
            }))
    if not candidates:
        return None
    # 점수 내림차순(동점이면 원래 등장 순서 유지) → 최상위 1개
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


# ---------------------------------------------------------------------------
# 브라우저/네트워크 (수동 검증)
# ---------------------------------------------------------------------------
_LIST_AJAX_JS = r"""
async (count) => {
  $('#recordCountPerPage').val(String(count));
  $('#pageIndex').val('1');
  const body = $('#frm').serialize();
  const res = await fetch('%s', {
    method: 'POST',
    headers: {'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8'},
    body, credentials: 'include',
  });
  return await res.text();
}
""" % DATA_LIST_AJAX


def fetch_data_posts(page, atlc_no: str, sbjt_id: str, cnts_id: str,
                     count: int = 100, timeout: int = 20000) -> list[dict]:
    """강의자료실에 진입해 글 목록(첨부 메타 포함)을 AJAX로 가져온다.

    page 는 로그인된 상태여야 한다. fnCourseDataPage 가 없으면 나의학습으로 이동 후 시도.
    """
    has = page.evaluate("() => typeof fnCourseDataPage === 'function'")
    if not has:
        page.goto(MY_STUDY_URL, wait_until="domcontentloaded", timeout=timeout)
    try:
        with page.expect_navigation(wait_until="domcontentloaded", timeout=timeout):
            page.evaluate("(a)=>fnCourseDataPage(a.atlc,a.sbjt,a.cnts)",
                          {"atlc": atlc_no, "sbjt": sbjt_id, "cnts": cnts_id})
    except Exception:
        page.wait_for_timeout(2000)
    raw = page.evaluate(_LIST_AJAX_JS, count)
    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return []
    return data.get("list") or []


def download_url(ctx, url: str, dest, timeout: int = 180000) -> dict:
    """persistent context의 인증 세션(쿠키 공유)으로 url을 받아 dest에 저장.

    return: {"ok","status","bytes","path"}
    """
    dest = Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = ctx.request.get(url, timeout=timeout)
    except Exception as e:
        return {"ok": False, "status": 0, "bytes": 0, "path": str(dest),
                "error": str(e)[:120]}
    if not resp.ok:
        return {"ok": False, "status": resp.status, "bytes": 0, "path": str(dest)}
    body = resp.body()
    # HTML 에러 페이지를 파일로 잘못 저장하는 것 방지(아주 작은데 <html 포함)
    if len(body) < 2048 and b"<html" in body[:512].lower():
        return {"ok": False, "status": resp.status, "bytes": len(body),
                "path": str(dest), "error": "html_response"}
    dest.write_bytes(body)
    return {"ok": True, "status": resp.status, "bytes": len(body), "path": str(dest)}


def download_lecture(ctx, page, lec, subject: str, posts=None,
                     dest_dir="downloads", overwrite: bool = False,
                     on_event=None) -> dict:
    """차시 1개의 MP3(음성) + PDF(강의록)를 내려받는다.

    lec     : discover.Lecture (audio_url=strVidoAudoUrl, sbjt_id 사용)
    subject : 과목명(파일명에 사용)
    posts   : 강의자료실 글목록(없으면 fetch_data_posts로 조회). 재사용 권장.
    return  : {"seq","mp3":{...}|None,"pdf":{...}|None,"posts":<list 재사용용>}
    """
    def log(m):
        if on_event:
            try:
                on_event(m)
            except Exception:
                pass

    dest_dir = Path(dest_dir)
    out = {"seq": lec.seq, "mp3": None, "pdf": None}

    # MP3 (URL은 이미 lectlist에 있음)
    if lec.audio_url:
        mp3_path = dest_dir / build_filename(subject, lec.seq, "mp3")
        if not overwrite and not needs_download(mp3_path):
            out["mp3"] = {"ok": True, "skipped": True, "path": str(mp3_path)}
            log(f"MP3 skip(이미 있음): {mp3_path.name}")
        else:
            log(f"MP3 다운로드: {mp3_path.name}")
            out["mp3"] = download_url(ctx, lec.audio_url, mp3_path)
    else:
        log("MP3 URL 없음(audio_url 비어있음)")

    # PDF (강의자료실에서 매칭)
    if posts is None:
        posts = fetch_data_posts(page, lec.atlc_no, lec.sbjt_id,
                                 _cnts_id_of(lec.sbjt_id))
    out["posts"] = posts
    m = match_pdf_post(posts, lec.seq)
    if m:
        pdf_path = dest_dir / build_filename(subject, lec.seq, m["ext"] or "pdf")
        if not overwrite and not needs_download(pdf_path):
            out["pdf"] = {"ok": True, "skipped": True, "path": str(pdf_path)}
            log(f"PDF skip(이미 있음): {pdf_path.name}")
        else:
            url = build_file_url(lec.sbjt_id, m["save_nm"], m["display_nm"])
            log(f"PDF 다운로드: {pdf_path.name} ← {m['display_nm']}")
            out["pdf"] = download_url(ctx, url, pdf_path)
    else:
        log(f"PDF 매칭 글 없음(seq={lec.seq})")

    return out


def _cnts_id_of(sbjt_id: str) -> str:
    """sbjtId(KNOU1545001) → cntsId(KNOU1545). 끝 3자리(과목 일련) 제거 추정."""
    s = sbjt_id or ""
    return s[:-3] if len(s) > 3 else s
