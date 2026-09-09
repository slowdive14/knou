"""[resize_embeds] 이미 만든 노트의 이미지 임베드 폭을 한꺼번에 맞춘다.

옵시디언은 `![[그림.jpg|695]]` 처럼 파일명 뒤에 폭(px)을 적으면 그 크기로
보여준다. 원본 해상도 그대로 두면 캡처마다 크기가 들쭉날쭉하고 본문 폭을
넘치기도 한다. 새로 만드는 노트는 capture.embed_text 가 알아서 붙이지만,
그 전에 만들어 둔 노트는 이 도구로 한 번에 맞춘다.

  - plan_resize(paths, width)   : 어떤 노트가 몇 줄 바뀌는지 계획 (순수)
  - resize_notes(dir, width)    : 계획대로 노트를 고쳐 쓴다 (IO)

⚠️ **이미지 파일은 건드리지 않는다.** 노트에 적힌 표시 폭만 바꾼다.
   내용이 바뀌지 않는 노트는 다시 쓰지도 않는다(동기화 소음 방지).
"""
from __future__ import annotations

from pathlib import Path

from capture import EMBED_WIDTH, embed_names, set_embed_width


def plan_resize(texts, width: int = EMBED_WIDTH) -> list[dict]:
    """[(이름, 본문)] → 바뀌는 노트만 [{name, text, new_text, embeds}] (순수).

    embeds 는 그 노트의 임베드 개수다. 이미 그 폭이면 목록에 넣지 않는다.
    """
    out = []
    for name, text in texts:
        new = set_embed_width(text, width)
        if new != text:
            out.append({"name": name, "text": text, "new_text": new,
                        "embeds": len(embed_names(text))})
    return out


def resize_notes(note_dir, width: int = EMBED_WIDTH, dry_run: bool = False,
                 on_event=lambda m: None) -> dict:
    """폴더 안 모든 .md 노트의 임베드 폭을 width 로 맞춘다.

    return: {"changed": [이름…], "embeds": 바뀐 임베드 총수, "scanned": 노트 수}
    """
    d = Path(note_dir)
    if not d.is_dir():
        raise NotADirectoryError(f"노트 폴더가 없습니다: {d}")
    notes = sorted(d.glob("*.md"))
    texts = [(p.name, p.read_text(encoding="utf-8")) for p in notes]
    plan = plan_resize(texts, width)
    by_name = {p.name: p for p in notes}
    total = 0
    for item in plan:
        total += item["embeds"]
        on_event(f"{item['name']} — 임베드 {item['embeds']}개")
        if not dry_run:
            by_name[item["name"]].write_text(item["new_text"], encoding="utf-8")
    return {"changed": [i["name"] for i in plan], "embeds": total,
            "scanned": len(notes)}


def main(argv=None) -> int:
    import argparse
    import sys
    try:    # 윈도우 콘솔 기본 인코딩(CP949)에서 한글 노트 이름이 깨진다
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:  # noqa: BLE001 - 재설정을 못 해도 작업은 해야 한다
        pass

    ap = argparse.ArgumentParser(
        description="예습 노트의 이미지 임베드 폭을 한꺼번에 맞춥니다.")
    ap.add_argument("--dir", default=None,
                    help="노트 폴더(기본: 설정의 예습 노트 폴더)")
    ap.add_argument("--width", type=int, default=EMBED_WIDTH,
                    help=f"표시 폭(px). 0 이면 폭 지정을 뗀다 (기본 {EMBED_WIDTH})")
    ap.add_argument("--dry-run", action="store_true", help="계획만 보여준다")
    a = ap.parse_args(argv)

    note_dir = a.dir
    if note_dir is None:
        from config import load_config
        note_dir = load_config().summary_dir
    res = resize_notes(note_dir, a.width, dry_run=a.dry_run, on_event=print)
    head = "바꿀 노트" if a.dry_run else "바꾼 노트"
    print(f"{head} {len(res['changed'])}개 / 전체 {res['scanned']}개 · "
          f"임베드 {res['embeds']}개 → 폭 {a.width}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
