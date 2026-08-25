"""Phase 0 정찰 스크립트.

방송대 LMS를 실제 브라우저로 열어, 직접 로그인·탐색하면서
- 로그인/강의목록/플레이어의 셀렉터
- 영상 화면 스크린샷이 검은화면(DRM)인지
- 영상 seek(특정 시각 이동) 방법
을 확인하기 위한 도구다.

실행:
    .venv/Scripts/python.exe recon.py

흐름:
  1) 브라우저가 뜨면 직접 로그인 → 강의 하나 들어가 영상을 재생한다.
  2) 영상이 화면에 보이는 상태에서 이 터미널로 돌아와 Enter.
  3) 스크립트가 화면/영상 스크린샷을 찍어 recon_shots/ 에 저장하고,
     검은화면 여부·video 태그 정보(현재시각/총길이/배속)를 출력한다.
  4) recon_shots/ 의 PNG를 직접 열어 눈으로 확인한다.
  5) 마지막에 Playwright Inspector가 열리면, 거기서 요소를 클릭해
     셀렉터를 뽑아 docs/lms-map.md 에 기록한다.

로그인 세션은 .auth/ 에 저장되어 다음 실행 때 재사용된다.
"""
from __future__ import annotations

import subprocess

from proc_util import run_hidden
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_DIR = Path(__file__).resolve().parent
AUTH_DIR = BASE_DIR / ".auth"
SHOTS_DIR = BASE_DIR / "recon_shots"

# 시작 페이지 후보 (앞에서부터 접속 시도, 다 실패하면 빈 화면 → 직접 주소 입력)
# 1순위 = 사용자의 "나의 학습" 페이지 (로그인 안 됐으면 로그인 화면으로 자동 이동)
START_URL_CANDIDATES = [
    "https://ucampus.knou.ac.kr/ekp/user/study/retrieveUMYStudy.sdo",
    "https://ucampus.knou.ac.kr/",
    "https://www.knou.ac.kr/",
]


def brightness_of_png(path: Path) -> float | None:
    """PNG의 평균 밝기(0~255)를 대략 계산. 검은화면(DRM) 판별용.

    PyMuPDF(fitz)로 픽셀을 읽어 평균을 낸다. 실패하면 None.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return None
    try:
        pix = fitz.Pixmap(str(path))
        data = pix.samples  # bytes (채널 인터리브)
        if not data:
            return None
        # 너무 크면 샘플링
        step = max(1, len(data) // 60000)
        sampled = data[::step]
        return sum(sampled) / len(sampled)
    except Exception:
        return None


_READY = {0: "0(HAVE_NOTHING)", 1: "1(메타데이터만)", 2: "2", 3: "3", 4: "4(재생가능)"}
_NET = {0: "0(EMPTY)", 1: "1(IDLE)", 2: "2(LOADING)", 3: "3(NO_SOURCE!)"}
_ERR = {
    1: "1 ABORTED(중단됨)",
    2: "2 NETWORK(네트워크오류)",
    3: "3 DECODE(디코딩실패)",
    4: "4 SRC_NOT_SUPPORTED(코덱/소스 미지원!)",
}


_PROBE_JS = """
() => {
  const out = {videos: [], jw: null};
  try {
    const vids = [...document.querySelectorAll('video')];
    for (let i = 0; i < vids.length; i++) {
      const v = vids[i];
      let seekable = '';
      try {
        if (v.seekable && v.seekable.length)
          seekable = Math.round(v.seekable.start(0)) + '~' + Math.round(v.seekable.end(v.seekable.length-1));
      } catch (e) {}
      out.videos.push({
        index: i,
        currentTime: Math.round(v.currentTime),
        duration: Number.isFinite(v.duration) ? Math.round(v.duration) : null,
        playbackRate: v.playbackRate,
        paused: v.paused,
        readyState: v.readyState,
        networkState: v.networkState,
        errorCode: v.error ? v.error.code : null,
        errorMsg: v.error ? (v.error.message || '') : '',
        src: (v.currentSrc || v.src || '').slice(0, 160),
        seekable,
      });
    }
    if (typeof jwplayer !== 'undefined') {
      try {
        const p = jwplayer();
        let pl = null;
        try { pl = p.getPlaylist ? p.getPlaylist() : null; } catch (e) {}
        out.jw = {
          state: p.getState ? p.getState() : null,
          position: p.getPosition ? Math.round(p.getPosition()) : null,
          duration: (p.getDuration && Number.isFinite(p.getDuration())) ? Math.round(p.getDuration()) : null,
          rate: p.getPlaybackRate ? p.getPlaybackRate() : null,
          playlistIndex: p.getPlaylistIndex ? p.getPlaylistIndex() : null,
          playlistLen: pl ? pl.length : null,
        };
      } catch (e) { out.jw = {error: String(e)}; }
    }
  } catch (e) { out.error = String(e); }
  return out;
}
"""


def report_videos(page) -> None:
    """페이지(및 모든 iframe) 안의 <video>/JWPlayer 상태를 출력."""
    import time as _t
    frames = [page.main_frame] + [f for f in page.frames if f != page.main_frame]
    found_any = False
    for fr in frames:
        res = None
        for _try in range(3):  # 스트림 리로드로 컨텍스트가 잠깐 죽을 수 있어 재시도
            try:
                res = fr.evaluate(_PROBE_JS)
            except Exception:
                res = None
            if res and (res.get("videos") or res.get("jw")):
                break
            _t.sleep(0.6)
        if not res:
            continue
        label = "main" if fr == page.main_frame else f"iframe:{fr.url[:60]}"
        vids = res.get("videos") or []
        jw = res.get("jw")
        if not vids and not jw:
            continue
        found_any = True
        print(f"  ── 프레임 [{label}]")
        for v in vids:
            print(f"     <video #{v['index']}> 재생위치 {v['currentTime']}s / 길이 {v['duration']}s, "
                  f"배속 {v['playbackRate']}, paused={v['paused']}")
            print(f"        readyState={_READY.get(v['readyState'], v['readyState'])}, "
                  f"networkState={_NET.get(v['networkState'], v['networkState'])}, "
                  f"seekable={v['seekable'] or '없음'}")
            if v["errorCode"]:
                print(f"        ❌ video.error = {_ERR.get(v['errorCode'], v['errorCode'])}  {v['errorMsg']}")
            if v["src"]:
                print(f"        src: {v['src']}")
        if jw:
            if jw.get("error"):
                print(f"     JWPlayer 조회 오류: {jw['error']}")
            else:
                print(f"     🎬 JWPlayer state={jw.get('state')}, "
                      f"position={jw.get('position')}s / duration={jw.get('duration')}s, "
                      f"rate={jw.get('rate')}, 클립 {jw.get('playlistIndex')}/{jw.get('playlistLen')}")

    if not found_any:
        print("  ⚠️ <video>/JWPlayer 를 어느 프레임에서도 못 찾음.")
        print("     → 프레임 목록:")
        for fr in page.frames:
            print(f"       - {fr.url[:90]}")
        return

    print("\n  [해석 가이드]")
    print("   - JWPlayer state=playing & position 증가 → ✅ 재생 중. seek=jwplayer().seek(초)")
    print("   - <video> paused=False & 재생위치 증가 → ✅ 재생 OK, seek=video.currentTime")
    print("   - duration=None & NaN → 메타데이터 아직(버퍼링) 또는 멀티클립 초기화 전")
    print("   - errorCode=4 → 코덱/DRM 문제 (지금은 .ts 다운로드 중이라 가능성 낮음)")


def ensure_chromium(p) -> None:
    """크로미움이 없으면 자동 설치한다."""
    exe = Path(p.chromium.executable_path)
    if exe.exists():
        return
    print(f"⚙️  Chromium이 없습니다 ({exe}). 설치를 시작합니다...")
    run_hidden(
        [sys.executable, "-m", "playwright", "install", "chromium"],
        check=True,
    )
    print("✅ Chromium 설치 완료.")


def clean_profile_locks(auth_dir: Path) -> None:
    """이전 실행이 남긴 프로필 잠금파일을 제거한다.

    잠금이 남아 있으면 새 Chrome이 '이미 사용 중'으로 보고 즉시 종료된다.
    """
    for name in ("SingletonLock", "SingletonCookie", "SingletonSocket", "lockfile"):
        f = auth_dir / name
        try:
            if f.is_symlink() or f.exists():
                f.unlink()
                print(f"  (잠금파일 정리: {name})")
        except Exception:
            pass


def launch_context(p):
    """진짜 Chrome/Edge를 우선 사용한다 (동영상 코덱 포함).

    내장 Chromium은 H.264/AAC 코덱이 없어 강의 영상이 재생 안 됨.
    chrome → msedge → 내장 Chromium 순으로 시도.
    """
    common = dict(
        user_data_dir=str(AUTH_DIR),
        headless=False,
        args=[
            "--start-maximized",
            # 사이트가 '자동화 브라우저'를 감지해 영상 재생을 막는 것 방지
            "--disable-blink-features=AutomationControlled",
            # 자동 재생 허용
            "--autoplay-policy=no-user-gesture-required",
        ],
        no_viewport=True,
        # 참고: chromium_sandbox=True 로 켜면 이 시스템에선 크롬이 뜨자마자 종료됨 →
        #       기본값(False) 사용. 상단 '--no-sandbox' 경고 띠는 무해하니 무시.
    )
    clean_profile_locks(AUTH_DIR)
    last_err = None
    for channel in ("chrome", "msedge", None):
        try:
            kwargs = dict(common)
            if channel:
                kwargs["channel"] = channel
            else:
                ensure_chromium(p)  # 내장으로 떨어질 때만 설치 확인
            ctx = p.chromium.launch_persistent_context(**kwargs)
            label = channel or "내장 Chromium(코덱 없음 — 영상 재생 안 될 수 있음)"
            print(f"🌐 브라우저: {label}")
            return ctx
        except Exception as e:
            last_err = e
            name = channel or "내장 Chromium"
            print(f"  ({name} 실행 실패 — 다음 후보 시도)")
    print("\n❌ 모든 브라우저 실행 실패:")
    print(f"   {last_err}")
    print("\n해결: Chrome 또는 Edge가 설치돼 있는지 확인하세요.")
    raise last_err


def pick_lms_page(ctx, default_page):
    """열린 탭들 중 방송대(knou) 페이지를 고른다. 없으면 마지막 탭."""
    pages = [pg for pg in ctx.pages if not pg.is_closed()]
    for pg in pages:
        if "knou" in pg.url.lower():
            return pg
    return pages[-1] if pages else default_page


def inspect_page(page, idx: int) -> None:
    """한 탭을 검사: URL/제목/스크린샷(밝기)/<video> 진단/iframe 목록 출력."""
    print("\n" + "─" * 60)
    print(f"▼ 탭 #{idx}")
    try:
        print(f"  URL  : {page.url}")
    except Exception:
        print("  URL  : (읽기 실패)")
    try:
        print(f"  제목 : {page.title()}")
    except Exception:
        pass

    # about:blank 팝업이면 한 번 더 로드를 기다려본다(JS가 늦게 채울 수 있음)
    if page.url in ("about:blank", "") :
        print("  (about:blank — JS가 내용을 채울 때까지 잠시 대기)")
        try:
            page.wait_for_load_state("networkidle", timeout=4000)
        except Exception:
            pass
        try:
            print(f"  URL(재확인): {page.url}")
        except Exception:
            pass

    # 전체 스크린샷 + 밝기
    full = SHOTS_DIR / f"tab{idx}_full.png"
    try:
        page.screenshot(path=str(full))
        b = brightness_of_png(full)
        if b is not None:
            verdict = "⚠️ 거의 검은화면(DRM 의심)" if b < 18 else "✅ 내용 보임"
            print(f"  [전체 스크린샷] {full.name}  평균밝기 {b:.1f}/255 → {verdict}")
        else:
            print(f"  [전체 스크린샷] {full.name}")
    except Exception as e:
        print(f"  [전체 스크린샷 실패] {e}")

    # video 영역 스크린샷 — 모든 프레임을 뒤져 <video>를 찾아 캡처
    vshot_done = False
    for fr in [page.main_frame] + [f for f in page.frames if f != page.main_frame]:
        if vshot_done:
            break
        try:
            vid = fr.locator("video").first
            if vid.count() > 0:
                vshot = SHOTS_DIR / f"tab{idx}_video.png"
                vid.screenshot(path=str(vshot))
                vb = brightness_of_png(vshot)
                if vb is not None:
                    verdict = "⚠️ 검은화면(DRM → Phase6은 PDF 슬라이드)" if vb < 18 else "✅ 영상 화면 캡처 가능!"
                    print(f"  [영상 스크린샷] {vshot.name}  평균밝기 {vb:.1f}/255 → {verdict}")
                vshot_done = True
        except Exception:
            continue

    # video 태그/iframe 진단
    report_videos(page)


def main() -> None:
    SHOTS_DIR.mkdir(exist_ok=True)
    AUTH_DIR.mkdir(exist_ok=True)

    print(f"실행 파이썬: {sys.executable}")
    if ".venv" not in sys.executable.replace("\\", "/"):
        print("⚠️  venv가 아닌 파이썬으로 실행 중일 수 있습니다.")
        print("   권장: .venv\\Scripts\\python.exe recon.py")

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 팝업/새 탭이 열릴 때마다 URL을 기록 (영상 플레이어가 팝업으로 뜨는 경우 추적용)
        popup_log: list[str] = []
        media_urls: list[str] = []  # 영상/음성/매니페스트 네트워크 요청 캡처
        _MEDIA_HINTS = (".mp4", ".m3u8", ".ts", ".m4s", ".mpd", ".mp3", ".webm",
                        "/media", "video", "stream", "play")

        def _on_request(req):
            try:
                u = req.url
                rtype = req.resource_type  # media / xhr / fetch ...
            except Exception:
                return
            low = u.lower()
            if rtype == "media" or any(h in low for h in _MEDIA_HINTS):
                line = f"  📡 [{rtype}] {u[:200]}"
                if line not in media_urls:
                    media_urls.append(line)

        def _on_page(pg):
            def _log(_=None):
                try:
                    msg = f"  🆕 새 탭/팝업: {pg.url}"
                except Exception:
                    msg = "  🆕 새 탭/팝업 (URL 읽기 실패)"
                popup_log.append(msg)
                print(msg)
            _log()
            try:
                pg.on("framenavigated", lambda fr: _log() if fr == pg.main_frame else None)
            except Exception:
                pass
            try:
                pg.on("request", _on_request)
            except Exception:
                pass

        try:
            ctx.on("page", _on_page)
            page.on("request", _on_request)
        except Exception:
            pass

        # 후보 주소 차례로 시도, 다 안 되면 빈 화면
        opened = None
        for url in START_URL_CANDIDATES:
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=15000)
                opened = url
                break
            except Exception:
                print(f"  (접속 실패: {url} — 다음 후보 시도)")
        if not opened:
            page.goto("about:blank")
            print("\n⚠️ 기본 주소 접속에 실패했습니다.")
            print("   → 열린 크롬 창의 주소창에 '평소 강의 보던 방송대 사이트 주소'를")
            print("     직접 입력해서 들어가세요. (그 주소를 저에게도 알려주면 다음부터 자동으로 엽니다)")

        print("=" * 60)
        print(" 정찰 시작")
        print("=" * 60)
        print("1) 브라우저에서 로그인하고, 강의 하나에 들어가 '강의보기'로 영상을 재생하세요.")
        print("2) 플레이어 팝업이 뜨면 '자동으로' 감지해서 진단합니다. (최대 120초 대기)")
        print("   팝업을 닫지 말고, 영상이 로딩되는 동안 그대로 두세요.")
        print("   ※ 팝업이 안 떠도 됩니다 — 영상이 있는 탭을 찾는 즉시 진단합니다.")
        print("-" * 60)
        print("⏳ 플레이어(영상) 탭을 기다리는 중...")

        import time

        def _has_video(pg) -> bool:
            # 영상은 중첩 iframe 안에 있으므로 모든 프레임을 검사한다
            for fr in pg.frames:
                try:
                    if fr.evaluate("() => !!document.querySelector('video')"):
                        return True
                except Exception:
                    continue
            return False

        player = None
        deadline = time.time() + 120
        while time.time() < deadline:
            for pg in list(ctx.pages):
                if pg.is_closed():
                    continue
                if _has_video(pg):
                    player = pg
                    break
            if player:
                break
            time.sleep(1.5)

        if player:
            print(f"✅ 영상 탭 감지: {player.url}")
            try:
                player.bring_to_front()
            except Exception:
                pass
            # 영상이 닫히기 전에 곧바로, 그리고 몇 초 간격으로 3번 진단(메타데이터 채워지는지 관찰)
            for shot in range(1, 4):
                if player.is_closed():
                    print("  ⚠️ 영상 탭이 닫혔습니다. 마지막 캡처까지만 사용합니다.")
                    break
                print(f"\n===== 영상 탭 진단 {shot}/3 =====")
                inspect_page(player, f"player{shot}")
                if shot < 3:
                    time.sleep(4)
        else:
            print("⚠️ 120초 안에 영상이 있는 탭을 못 찾았습니다.")
            print("   지금 열린 모든 탭을 대신 검사합니다.")

        # 열린 모든 탭(팝업 포함)도 한 번씩 검사
        pages = [pg for pg in ctx.pages if not pg.is_closed()]
        print("\n" + "-" * 60)
        print(f"열린 탭 수: {len(pages)}")
        if popup_log:
            print("그동안 열린 팝업/새 탭 기록:")
            for line in popup_log:
                print(line)
        for i, pg in enumerate(pages, 1):
            inspect_page(pg, i)

        # 캡처된 영상/음성 네트워크 요청
        print("\n" + "-" * 60)
        print("📡 캡처된 미디어 관련 네트워크 요청:")
        if media_urls:
            for line in media_urls[:40]:
                print(line)
        else:
            print("  (없음 — 영상 소스 요청이 아예 발생하지 않았을 수 있음)")

        # 이후 Inspector 등은 방송대(knou) 탭 기준
        page = pick_lms_page(ctx, page)

        print("\n" + "=" * 60)
        print(" recon_shots/ 폴더의 PNG를 직접 열어 검은화면인지 확인하세요.")
        print(" 이제 Playwright Inspector가 열립니다.")
        print("  - Inspector의 'Pick locator'로 로그인폼/강의목록/배속버튼/")
        print("    다운로드 링크를 클릭하면 셀렉터가 나옵니다.")
        print("  - 그 값들을 docs/lms-map.md 에 적으세요.")
        print("  - 다 끝나면 Inspector의 Resume(▶) 또는 창을 닫으면 종료됩니다.")
        print("=" * 60)
        try:
            page.pause()  # Playwright Inspector 열림
        except Exception:
            input("Inspector를 못 열었어요. 탐색이 끝나면 Enter ▶ ")

        ctx.close()
        print("정찰 종료. 세션은 .auth/ 에 저장됨.")


if __name__ == "__main__":
    main()
