"""정답 없는 문항을 AI 로 풀어 적는다 — 로그인하지 않는다.

harvest_quiz.py --ai-only 와 같다(도구 탭에서 단추 하나로 부르려고 따로 둔다).

실행:
    .venv/Scripts/python.exe fill_answers.py --course 자료구조
"""
from __future__ import annotations

import sys

import harvest_quiz

if __name__ == "__main__":
    raise SystemExit(harvest_quiz.main(["--ai-only"] + sys.argv[1:]))
