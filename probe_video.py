"""Phase 6 정찰: 이산수학 1강 영상 클립 구조 파악 (읽기 전용, 다운로드/제출 없음).

플레이어 팝업을 열어 각 ifrmVODPlayer_dataN(전역변수)에서
fileTitle + 고화질 hlsUrl(신선한 토큰)을 수집하고, 각 m3u8을 ffprobe로
길이 측정 → 합계를 MP3(2491s)와 비교해 "단일 클립 vs 연결" 판정.

실행: .venv/Scripts/python.exe -u probe_video.py
"""
from __future__ import annotations

import base64
import json
import subprocess
import sys
from datetime import datetime, timezone

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from config import load_config
from discover import fetch_lectures, list_courses
from recon import launch_context
from watch import open_player

TARGET_COURSE = "이산수학"
TARGET_SEQ = 1

# 팝업 메인 프레임의 전역 ifrmVODPlayer_dataN 들을 모아 JSON 으로 반환
_COLLECT_JS = """
() => {
  const out = [];
  for (let i = 0; i < 30; i++) {
    const d = window['ifrmVODPlayer_data' + i];
    if (!d) continue;
    let title = '', hls = '', fid = '';
    try { title = d.source[0].fileTitle; } catch(e){}
    try { hls = d.source[0].stream[0].hlsUrl; } catch(e){}
    try { fid = d.lectPldcTocNo || d.source[0].fileId || ''; } catch(e){}
    out.push({idx: i, title: title, fileId: fid, hlsUrl: hls});
  }
  return JSON.stringify(out);
}
"""


def jwt_exp(url: str):
    """m3u8 URL 의 ?token=<JWT> 에서 exp(만료시각) 읽기."""
    try:
        tok = url.split("token=", 1)[1].split("&", 1)[0]
        payload = tok.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        data = json.loads(base64.urlsafe_b64decode(payload))
        exp = data.get("exp")
        if exp:
            return datetime.fromtimestamp(exp, tz=timezone.utc)
    except Exception:
        pass
    return None


def ffprobe_duration(url: str):
    """ffprobe 로 스트림 길이(초) 측정. 실패 시 None."""
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", url],
            capture_output=True, text=True, timeout=120,
        )
        s = (out.stdout or "").strip()
        return float(s) if s else None
    except Exception as e:
        print(f"    ffprobe 오류: {str(e)[:80]}", flush=True)
        return None


def main() -> None:
    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)

        course = next(c for c in list_courses(page) if c.name == TARGET_COURSE)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == TARGET_SEQ)
        print(f"대상: {course.name} {lec.seq}강 '{lec.name}'", flush=True)
        print(f"  MP3(음성) 길이 기준: 2490.97s (~41.5분)\n", flush=True)

        popup = open_player(page, lec)
        raw = popup.evaluate(_COLLECT_JS)
        clips = json.loads(raw) if raw else []
        print(f"플레이어 클립(영상 조각) {len(clips)}개:\n", flush=True)

        total = 0.0
        for c in clips:
            title = c.get("title") or "(제목없음)"
            url = c.get("hlsUrl") or ""
            exp = jwt_exp(url)
            exp_s = exp.astimezone().strftime("%Y-%m-%d %H:%M:%S") if exp else "?"
            print(f"[{c['idx']}] {title}  (toc={c.get('fileId')})", flush=True)
            print(f"     토큰 만료: {exp_s}", flush=True)
            if not url:
                print("     ⚠️ hlsUrl 없음", flush=True)
                continue
            dur = ffprobe_duration(url)
            if dur:
                total += dur
                m, s = divmod(int(dur), 60)
                print(f"     길이: {dur:.1f}s ({m}:{s:02d})", flush=True)
            else:
                print("     길이: 측정 실패", flush=True)
            print("", flush=True)

        tm, ts = divmod(int(total), 60)
        print(f"=== 합계: {total:.1f}s ({tm}:{ts:02d}) ===", flush=True)
        print(f"MP3 길이 2490.97s 와 비교:", flush=True)
        print(f"  · 합계가 MP3와 비슷 → 영상=여러 클립 '연결', MP3=전체 오디오", flush=True)
        print(f"  · 특정 1개 클립이 MP3와 비슷 → MP3=그 클립의 오디오", flush=True)

        try:
            popup.close()
        except Exception:
            pass
        ctx.close()


if __name__ == "__main__":
    main()
