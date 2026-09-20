"""읽기 전용: 형성평가 지문 그림을 실제로 내려받을 수 있는지 확인한다.

지문은 form 안 `.exam-print` 의 `<img>` 다(실측: 842x498, /user_uploading?…).
안 보이는 문항(exam-body-hidden)도 있어 화면 촬영 대신 **주소를 읽어 브라우저
쿠키 그대로 요청**하는 방법을 확인한다.

  .venv/Scripts/python.exe -u probe_intro_fetch.py --course C프로그래밍 --seq 5

⚠️ 아무것도 제출하지 않는다. 주소의 쿼리는 찍지 않는다(토큰이 실릴 수 있다).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 콘솔이 없어도 돈다
    pass

from playwright.sync_api import sync_playwright

from auth import ensure_logged_in
from config import load_config
from discover import fetch_lectures, list_courses
from exercise import wait_for_exam_frame
from recon import launch_context
from watch import open_player

# 문항마다 지문 글과 지문 그림 주소를 읽는다(입력칸은 건드리지 않는다).
_INTRO_JS = r"""
() => {
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = [];
  document.querySelectorAll(".exam-content-box form").forEach(f => {
    const idEl = f.querySelector('input[name="exqsId"]');
    const print = f.querySelector('.exam-print');
    const sent = print ? print.querySelector('.exam-sentence') : null;
    const img = print ? print.querySelector('img') : null;
    out.push({
      exqsId: idEl ? idEl.value : '',
      hasPrint: !!print,
      text: norm(sent ? sent.textContent : ''),
      src: img ? img.src : '',
      w: img ? img.naturalWidth : 0, h: img ? img.naturalHeight : 0,
    });
  });
  return JSON.stringify(out);
}
"""


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="지문 그림 내려받기 확인(읽기 전용)")
    ap.add_argument("--course", default="C프로그래밍")
    ap.add_argument("--seq", type=int, default=5)
    ap.add_argument("--out", default="")
    a = ap.parse_args(argv)

    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        course = next(c for c in list_courses(page) if c.name == a.course)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == a.seq)
        popup = open_player(page, lec)
        fr = wait_for_exam_frame(popup)
        if fr is None:
            print("연습문제 프레임 없음", flush=True)
            return 1
        time.sleep(1.5)
        rows = json.loads(fr.evaluate(_INTRO_JS))
        out_dir = Path(a.out) if a.out else None
        for r in rows:
            print(f"exqsId={r['exqsId']} 지문칸={r['hasPrint']} "
                  f"글={r['text'][:40]!r} 그림={bool(r['src'])} "
                  f"{r['w']}x{r['h']}", flush=True)
            if not r["src"]:
                continue
            try:
                resp = popup.request.get(r["src"])
                body = resp.body()
                print(f"   내려받기 {resp.status} "
                      f"{resp.headers.get('content-type')} {len(body)}바이트",
                      flush=True)
                if out_dir:
                    out_dir.mkdir(parents=True, exist_ok=True)
                    f = out_dir / f"{a.course}_{a.seq}강_{r['exqsId']}.png"
                    f.write_bytes(body)
                    print(f"   저장 {f}", flush=True)
            except Exception as ex:  # noqa: BLE001
                print(f"   내려받기 실패: {str(ex)[:100]}", flush=True)
        popup.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
