"""Phase 5 수동 검증: 이산수학 1강 MP3+PDF → Gemini 요약 → Obsidian 노트.

이미 받아둔 downloads/이산수학_1강.mp3 + .pdf 를 google-genai로 업로드해
구조화 마크다운 요약(개념별 🎬 [HH:MM:SS])을 생성하고, 볼트의 요약 폴더에
.md + .timestamps.json 으로 저장한 뒤 결과를 검증 출력한다.

⚠️ GEMINI_API_KEY 는 절대 출력하지 않는다. 실행:
   .venv/Scripts/python.exe -u summarize_one.py
"""
from __future__ import annotations

import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass

from google import genai

from config import load_config
from summarize import DEFAULT_MODEL, needs_summary, note_filename, summarize_lecture, save_summary

TARGET_SUBJECT = "이산수학"
TARGET_SEQ = 1
TARGET_NAME = "이산수학의 개요"


def main() -> None:
    cfg = load_config()
    mp3 = cfg.downloads_dir / "이산수학_1강.mp3"
    pdf = cfg.downloads_dir / "이산수학_1강.pdf"
    out_dir = cfg.summary_dir

    print(f"대상: {TARGET_SUBJECT} {TARGET_SEQ}강 '{TARGET_NAME}'", flush=True)
    print(f"  MP3: {mp3} ({mp3.stat().st_size if mp3.exists() else 0} bytes)", flush=True)
    print(f"  PDF: {pdf} ({pdf.stat().st_size if pdf.exists() else 0} bytes)", flush=True)
    print(f"  저장 폴더: {out_dir}", flush=True)
    print(f"  모델: {DEFAULT_MODEL}", flush=True)

    if not mp3.exists() or not pdf.exists():
        print("❌ MP3/PDF 가 없습니다. 먼저 download_one.py 를 실행하세요.", flush=True)
        return

    note_path = out_dir / note_filename(TARGET_SUBJECT, TARGET_SEQ, TARGET_NAME)
    if not needs_summary(note_path):
        print(f"\n⏭  이미 요약 노트가 있습니다: {note_path}", flush=True)
        print("   (다시 만들려면 해당 .md 파일을 지우고 재실행)", flush=True)
        return

    client = genai.Client(api_key=cfg.gemini_api_key)

    print("\n▶ 요약 생성 시작…", flush=True)
    md = summarize_lecture(
        client, TARGET_SUBJECT, TARGET_SEQ, TARGET_NAME,
        mp3_path=mp3, pdf_path=pdf,
        on_event=lambda m: print("  ·", m, flush=True),
    )

    print("\n=== 요약 미리보기(앞부분) ===", flush=True)
    print("\n".join(md.splitlines()[:25]), flush=True)
    print("  …(이하 생략)", flush=True)

    res = save_summary(md, out_dir, TARGET_SUBJECT, TARGET_SEQ, TARGET_NAME)

    print("\n=== 저장 결과 ===", flush=True)
    print(f"  노트     : {res['md']}", flush=True)
    print(f"  타임스탬프: {res['timestamps']} ({res['ts_count']}개)", flush=True)

    print("\n=== 검증 ===", flush=True)
    md_path = Path(res["md"])
    ts_path = Path(res["timestamps"])
    md_ok = md_path.exists() and md_path.stat().st_size > 0
    ts_ok = ts_path.exists() and ts_path.stat().st_size > 0
    print(f"  노트     : {'✅' if md_ok else '❌'} {md_path.name} "
          f"({md_path.stat().st_size if md_path.exists() else 0} bytes)", flush=True)
    print(f"  타임스탬프: {'✅' if ts_ok else '❌'} {ts_path.name} "
          f"({res['ts_count']}개 추출)", flush=True)
    if res["ts_count"] == 0:
        print("  ⚠️ 타임스탬프가 0개입니다 — 프롬프트/모델 출력 형식을 확인하세요.", flush=True)


if __name__ == "__main__":
    main()
