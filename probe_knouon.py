"""정찰: knouon.knou.ac.kr(바이오통계학) 강의 페이지 구조 파악.

바이오통계학만 전자캠퍼스(ucampus)가 아니라 **knouon** 이라는 다른 시스템에서
돌아간다. '나의 학습'에는 과목이 뜨지만(sbjtId=KNOU2092001) 차시 AJAX 가 빈
목록을 주므로, 지금 파이프라인은 이 과목을 아예 보지 못한다.

여기서 확인할 것:
  1. ucampus 로그인 세션이 knouon 에도 통하는가(다른 서브도메인)
  2. 차시 목록이 DOM 인가 AJAX 인가 — 응답 형태는 무엇인가
  3. 영상·음성(MP3)·강의록 링크가 있는가, 있다면 어떤 형태인가
  4. 이수 상태(진도)를 어디서 읽는가

**읽기 전용**이다. 아무것도 제출하지 않고 화면만 뜬다.
결과는 recon_shots/knouon_*.{json,html,png} 로 저장한다.

실행:
    .venv/Scripts/python.exe probe_knouon.py
"""
from __future__ import annotations

import json
import sys

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from config import load_config
from recon import SHOTS_DIR, launch_context

SUBJECT_URL = (
    "https://knouon.knou.ac.kr/subject/subject.do"
    "?encParams=JTdCJTIyeXJTbXN0ciUyMiUzQSUyMjIwMjYwMiUyMiUyQyUyMnNtc3RyQ2hydEdibmNkJTIyJTNBJTIyU01TVFIlMjIlMkMlMjJzbXN0ckNocnRJZCUyMiUzQSUyMk9SU0NPX2JocGtjY2RkaGVpMmE2NWE1NTklMjIlMkMlMjJvcmdJZCUyMiUzQSUyMk9SRzAwMDAwMDElMjIlMkMlMjJ1c2VyVHljZCUyMiUzQSUyMlNURE5UJTIyJTdE"
    "&addParams=eyJzYmpjdElkIjoiU0JKQ1RfS05PVTIwOTIwMDEifQ%3D%3D"
)

# 페이지가 차시를 어떻게 담고 있는지 넓게 훑는다(셀렉터를 모르므로 구조부터).
_SCAN_JS = """
() => {
  const txt = (el) => (el ? el.textContent.trim().replace(/\\s+/g, ' ') : '');
  // 반복되는 목록처럼 보이는 컨테이너 후보: 자식이 3개 이상인 ul/ol/tbody/div
  const lists = [...document.querySelectorAll('ul, ol, tbody, .list, [class*=list]')]
    .filter(el => el.children.length >= 3)
    .slice(0, 12)
    .map(el => ({
      tag: el.tagName.toLowerCase(),
      cls: el.className || '',
      id: el.id || '',
      children: el.children.length,
      first: txt(el.children[0]).slice(0, 160),
      attrs: [...el.attributes].map(a => a.name + '=' + a.value).slice(0, 8),
    }));
  // 'N강' 이 들어간 요소 — 차시 줄일 가능성이 높다
  const weeks = [...document.querySelectorAll('*')]
    .filter(el => el.children.length === 0 && /\\d+\\s*강/.test(el.textContent || ''))
    .slice(0, 20)
    .map(el => ({
      tag: el.tagName.toLowerCase(), cls: el.className || '',
      text: txt(el).slice(0, 80),
      path: (() => { const p = []; let n = el;
        while (n && n !== document.body && p.length < 5) {
          p.push(n.tagName.toLowerCase() + (n.className ? '.' + String(n.className).split(' ')[0] : ''));
          n = n.parentElement; } return p.reverse().join(' > '); })(),
    }));
  // 재생/다운로드로 보이는 클릭 대상
  const actions = [...document.querySelectorAll('a[href], button, [onclick]')]
    .filter(el => /재생|학습|강의|시청|다운|자료|교안|mp3|pdf|play/i.test(
        (el.textContent || '') + ' ' + (el.getAttribute('onclick') || '') + ' ' + (el.getAttribute('href') || '')))
    .slice(0, 25)
    .map(el => ({
      tag: el.tagName.toLowerCase(), text: txt(el).slice(0, 60),
      href: el.getAttribute('href') || '', onclick: (el.getAttribute('onclick') || '').slice(0, 160),
    }));
  return {
    url: location.href, title: document.title,
    bodyLen: document.body ? document.body.innerHTML.length : 0,
    frames: [...document.querySelectorAll('iframe')].map(f => f.src || f.name || '(익명)'),
    lists, weeks, actions,
  };
}
"""


def main() -> int:
    cfg = load_config()
    SHOTS_DIR.mkdir(parents=True, exist_ok=True)
    calls: list[dict] = []

    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # 오가는 XHR 을 전부 적어 둔다 — 차시가 AJAX 로 온다면 여기 잡힌다
        def on_resp(resp):
            try:
                rt = resp.request.resource_type
                if rt not in ("xhr", "fetch"):
                    return
                rec = {"url": resp.url, "status": resp.status,
                       "method": resp.request.method}
                ct = (resp.headers or {}).get("content-type", "")
                if "json" in ct.lower():
                    try:
                        rec["json"] = resp.json()
                    except Exception:
                        rec["text"] = (resp.text() or "")[:2000]
                calls.append(rec)
            except Exception:
                pass

        page.on("response", on_resp)

        print("1) ucampus 로그인 확보…", flush=True)
        ensure_logged_in(page, cfg)
        print("   로그인 OK", flush=True)

        print("2) knouon 과목 페이지로 이동…", flush=True)
        page.goto(SUBJECT_URL, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(3000)

        info = page.evaluate(_SCAN_JS)
        print(f"   URL   : {info['url']}", flush=True)
        print(f"   제목  : {info['title']}", flush=True)
        print(f"   본문  : {info['bodyLen']} 글자 · iframe {len(info['frames'])}개",
              flush=True)
        for f in info["frames"]:
            print(f"     iframe: {f}", flush=True)
        print(f"   'N강' 후보 {len(info['weeks'])}개:", flush=True)
        for w in info["weeks"][:8]:
            print(f"     {w['text']}   ← {w['path']}", flush=True)
        print(f"   동작 후보 {len(info['actions'])}개:", flush=True)
        for a in info["actions"][:12]:
            print(f"     [{a['tag']}] {a['text']} | {a['href'][:60]} "
                  f"{a['onclick'][:60]}", flush=True)
        print(f"   XHR {len(calls)}건:", flush=True)
        for c in calls[:15]:
            print(f"     {c['status']} {c['method']} {c['url'][:110]}", flush=True)

        # 3) 대시보드에 박힌 moveClassRoom 으로 실제 강의실 진입.
        #    URL 의 encParams(학기 컨텍스트)는 페이지가 들고 있으므로, 직접
        #    조립하지 않고 페이지의 함수를 그대로 부른다(학기가 바뀌어도 따라감).
        print("\n3) 강의실 진입(moveClassRoom)…", flush=True)
        calls.clear()
        try:
            page.evaluate("() => moveClassRoom('SBJCT_KNOU2092001')")
            page.wait_for_load_state("networkidle", timeout=60000)
            page.wait_for_timeout(3000)
        except Exception as e:  # noqa: BLE001
            print(f"   진입 실패: {str(e)[:150]}", flush=True)

        room = page.evaluate(_SCAN_JS)
        print(f"   URL   : {room['url'][:120]}", flush=True)
        print(f"   제목  : {room['title']}", flush=True)
        print(f"   본문  : {room['bodyLen']} 글자 · iframe {len(room['frames'])}개",
              flush=True)
        for f in room["frames"]:
            print(f"     iframe: {f[:110]}", flush=True)
        print(f"   목록 후보 {len(room['lists'])}개:", flush=True)
        for li in room["lists"][:8]:
            print(f"     <{li['tag']} class={li['cls'][:40]}> 자식 {li['children']}"
                  f" | {li['first'][:90]}", flush=True)
        print(f"   'N강' 후보 {len(room['weeks'])}개:", flush=True)
        for w in room["weeks"][:14]:
            print(f"     {w['text'][:70]}   ← {w['path'][:80]}", flush=True)
        print(f"   동작 후보 {len(room['actions'])}개:", flush=True)
        for a in room["actions"][:18]:
            print(f"     [{a['tag']}] {a['text'][:45]} | {a['href'][:50]} "
                  f"{a['onclick'][:70]}", flush=True)
        print(f"   XHR {len(calls)}건:", flush=True)
        for c in calls[:20]:
            print(f"     {c['status']} {c['method']} {c['url'][:110]}", flush=True)

        (SHOTS_DIR / "knouon_room.json").write_text(
            json.dumps(room, ensure_ascii=False, indent=1), encoding="utf-8")
        (SHOTS_DIR / "knouon_room.html").write_text(
            page.content(), encoding="utf-8")
        (SHOTS_DIR / "knouon_room_xhr.json").write_text(
            json.dumps(calls, ensure_ascii=False, indent=1), encoding="utf-8")
        page.screenshot(path=str(SHOTS_DIR / "knouon_room.png"), full_page=True)

        (SHOTS_DIR / "knouon_scan.json").write_text(
            json.dumps(info, ensure_ascii=False, indent=1), encoding="utf-8")
        (SHOTS_DIR / "knouon_xhr.json").write_text(
            json.dumps(calls, ensure_ascii=False, indent=1), encoding="utf-8")
        (SHOTS_DIR / "knouon_subject.html").write_text(
            page.content(), encoding="utf-8")
        page.screenshot(path=str(SHOTS_DIR / "knouon_subject.png"),
                        full_page=True)
        print(f"\n저장: {SHOTS_DIR}", flush=True)
        print("창을 열어 둡니다 — 확인 후 Enter 를 누르면 닫습니다.", flush=True)
        try:
            input()
        except Exception:
            page.wait_for_timeout(20000)
        ctx.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
