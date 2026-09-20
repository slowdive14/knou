"""읽기 전용: 형성평가 문항의 **지문이 어디에 있는지** 살핀다. 아무것도 제출하지 않음.

실측 불편: '위 문장의 출력 결과는?' 같은 문항을 담아 왔는데 그 '위 문장' 이
없다. 지금 스캐너(quiz_capture)는 form 안의 문제글과 보기만 읽는다 — 지문이
form 밖에 있는지, 안에 있는데 셀렉터가 못 집는지, 아니면 그림인지를 봐야 한다.

  .venv/Scripts/python.exe -u probe_exam_intro.py --course C프로그래밍 --seq 5

⚠️ 학번·비밀번호가 새지 않게 **입력칸(input)·스크립트는 훑지 않는다.**
   태그·클래스·글자·그림 주소(쿼리 뺀)만 찍는다. 입력칸 중에서는 문항 번호
   (exqsId)만 읽는다 — 같은 form 에 학번이 든 칸이 섞여 있다.
"""
from __future__ import annotations

import argparse
import json
import sys
import time

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

# 문항 상자의 뼈대를 훑는다. input·script 는 값이 들어 있어 아예 건드리지 않는다.
_SCAN_JS = r"""
() => {
  const SKIP = {INPUT:1, SCRIPT:1, STYLE:1, TEXTAREA:1, SELECT:1, BUTTON:1};
  const norm = s => (s || '').replace(/\s+/g, ' ').trim();
  const out = {boxes: 0, forms: [], boxHead: []};
  const box = document.querySelector('.exam-content-box');
  out.boxes = document.querySelectorAll('.exam-content-box').length;
  if (!box) return JSON.stringify(out);

  const node = (el, d) => {
    const kids = [];
    for (const c of el.children) { if (!SKIP[c.tagName]) kids.push(c); }
    const rec = {d: d, tag: el.tagName.toLowerCase(),
                 cls: norm(el.className && el.className.baseVal === undefined
                           ? el.className : ''),
                 kids: kids.length};
    if (el.tagName === 'IMG') {
      const src = el.getAttribute('src') || '';
      // 물음표 뒤(쿼리)는 토큰이 실릴 수 있어 떼고 찍는다
      rec.img = src.slice(0, 5) === 'data:' ? '(data URI)' : src.split('?')[0];
      rec.q = src.indexOf('?') >= 0;
      rec.abs = (el.currentSrc || '').split('?')[0];
      rec.w = el.naturalWidth; rec.h = el.naturalHeight;
      rec.alt = norm(el.getAttribute('alt'));
    }
    if (!kids.length) { rec.txt = norm(el.textContent).slice(0, 160); }
    return {rec: rec, kids: kids};
  };

  const walk = (el, d, acc) => {
    const n = node(el, d);
    acc.push(n.rec);
    if (d >= 6) return;
    for (const c of n.kids) { walk(c, d + 1, acc); }
  };

  // form 밖, 상자 머리에 지문이 있을 수도 있다
  for (const c of box.children) {
    if (c.tagName === 'FORM' || SKIP[c.tagName]) continue;
    const acc = [];
    walk(c, 0, acc);
    out.boxHead.push(acc);
  }

  box.querySelectorAll("form[id^='frm_'], form[name^='frm_']").forEach(f => {
    const idEl = f.querySelector('input[name="exqsId"]');
    const acc = [];
    for (const c of f.children) { if (!SKIP[c.tagName]) walk(c, 0, acc); }
    out.forms.push({exqsId: idEl ? idEl.value : '', nodes: acc});
  });
  return JSON.stringify(out);
}
"""


def show(nodes, limit=80):
    for r in nodes[:limit]:
        pad = "  " * int(r.get("d") or 0)
        bits = [f"{pad}<{r.get('tag')}>"]
        if r.get("cls"):
            bits.append(f".{r['cls']}")
        if r.get("img"):
            bits.append(f"  그림={r['img']!r} 크기={r.get('w')}x{r.get('h')} "
                        f"쿼리있음={r.get('q')}")
            if r.get("abs"):
                bits.append(chr(10) + f"{pad}    실제주소={r['abs']}")
        if r.get("txt"):
            bits.append(f"  {r['txt']!r}")
        print("".join(bits), flush=True)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="형성평가 지문 자리 살피기(읽기 전용)")
    ap.add_argument("--course", default="C프로그래밍")
    ap.add_argument("--seq", type=int, default=5)
    ap.add_argument("--qid", help="이 문항의 뼈대만 자세히 본다")
    a = ap.parse_args(argv)

    cfg = load_config()
    with sync_playwright() as p:
        ctx = launch_context(p)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        ensure_logged_in(page, cfg)
        course = next(c for c in list_courses(page) if c.name == a.course)
        lec = next(l for l in fetch_lectures(page, course) if l.seq == a.seq)
        print(f"대상: {course.name} {lec.seq}강", flush=True)

        popup = open_player(page, lec)
        fr = wait_for_exam_frame(popup)
        if fr is None:
            print("연습문제 프레임을 못 찾음", flush=True)
            return 1
        time.sleep(1.5)
        res = json.loads(fr.evaluate(_SCAN_JS))
        print(f"상자 {res['boxes']}개 · 문항 {len(res['forms'])}개", flush=True)
        for i, head in enumerate(res.get("boxHead") or []):
            print(f"\n■ 상자 머리 {i}", flush=True)
            show(head, 40)
        for f in res["forms"]:
            if a.qid and str(f["exqsId"]) != str(a.qid):
                continue
            print(f"\n■ 문항 exqsId={f['exqsId']}", flush=True)
            show(f["nodes"], 200)
        popup.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
