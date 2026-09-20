"""변형 문항 다시 풀어 보기 — 물음과 답이 어긋난 것을 걸러낸다.

코드가 있는 변형은 만들 때 **실제로 컴파일해** 정답을 확인했다. 그런데 코드가
없는 개념 문항은 아무 검증도 없었고, 실제로 이런 것이 섞여 있었다.

    원본: 다음 중 문자열의 입출력에 사용되는 함수가 **아닌** 것은? → strings()
    변형: 다음 중 문자를 하나 입력받는 함수로 **가장 적절한** 것은? → gets_s()

변형을 만들며 부정형이 사라졌는데 정답은 '성질이 다른 하나' 그대로였다. 물음과
답이 어긋난 문항은 외울수록 해롭다.

그래서 **정답을 알려주지 않고** 다시 풀게 한다. 검토가 고른 답이 은행에 적힌
답과 다르면 그 문항은 믿을 수 없으므로 표시해 두고 화면에서 뺀다(파일에는
사유와 함께 남는다 — 지우지 않는다).

실행:
    .venv/Scripts/python.exe -u check_variants.py            # 살펴보기만
    .venv/Scripts/python.exe -u check_variants.py --apply    # 걸러내기
    .venv/Scripts/python.exe -u check_variants.py --year 2016
    .venv/Scripts/python.exe -u check_variants.py --recheck  # 뺐던 것도 다시

⚠️ 기출은 검토하지 않는다. 기출의 정답은 학교가 낸 정답표에서 왔고, 그쪽이
   모델보다 훨씬 믿을 만하다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001 - 콘솔이 없어도 돈다
    pass

import quiz_variant as qv

COURSE = "C프로그래밍"
SUSPECT_FIELD = "suspect"


def _log(m):
    print(m, flush=True)


def origin_index(quiz_dir: Path) -> dict:
    """{기출 문항번호: 문항} — 변형이 원본에서 무엇을 바꿨는지 보려고 읽는다."""
    out = {}
    for p in sorted(Path(quiz_dir).glob("*_기출*.json")):
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for q in data.get("questions") or []:
            out[str(q.get("qid"))] = q
    return out


def variant_banks(quiz_dir: Path, year=None) -> list:
    """변형 은행 [(경로, 내용)] — 기출은 건드리지 않는다."""
    out = []
    for p in sorted(Path(quiz_dir).glob("*_변형*.json")):
        if year and f"변형{year}-" not in p.name:
            continue
        try:
            out.append((p, json.loads(p.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            _log(f"   ! 읽지 못함: {p.name}")
    return out


def to_check(bank, recheck: bool = False) -> list:
    """검토할 문항 — 이미 빼 둔 것은 건드리지 않는다(--recheck 면 다시)."""
    return [q for q in (bank.get("questions") or [])
            if recheck or not str(q.get(SUSPECT_FIELD) or "").strip()]


def store_suspects(path, mapping, clear=(), confirm=()) -> int:
    """걸러낸 사유를 은행 JSON 에 써넣는다 → 표시·해제한 문항 수.

    clear 에 적힌 문항은 표시를 **지운다** — 다시 검토해서 문제가 없으면
    화면으로 돌아와야 한다(검토가 흔들려 잘못 뺀 것을 되돌릴 길이 필요하다).

    ⚠️ 임시 파일에 쓴 뒤 바꿔치기한다. 문항이 든 파일이라 도중에 멈춰
    반쪽짜리가 남으면 그 회차를 통째로 잃는다.
    """
    mapping = {str(k): str(v or "").strip() for k, v in (mapping or {}).items()}
    clear = {str(x) for x in (clear or ())}
    confirm = {str(x) for x in (confirm or ())}
    if not mapping and not clear and not confirm:
        return 0
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return 0
    hit = 0
    for q in data.get("questions") or []:
        qid = str(q.get("qid"))
        why = mapping.get(qid)
        if why and q.get(SUSPECT_FIELD) != why:
            q[SUSPECT_FIELD] = why
            hit += 1
        elif qid in clear and q.get(SUSPECT_FIELD):
            q.pop(SUSPECT_FIELD, None)
            hit += 1
        elif qid in confirm and not q.get("verified"):
            # 실행이 정답을 확인해 주었다 — '확인하지 못함' 경고를 뗀다
            q["verified"] = True
            hit += 1
    if not hit:
        return 0
    tmp = p.with_suffix(p.suffix + ".tmp")
    try:
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1),
                       encoding="utf-8")
        os.replace(tmp, p)
    except OSError:
        return 0
    return hit


def run_verdict(q, compiler) -> int:
    """코드를 돌려 보기 하나를 집어낸다 → 보기 번호(못 정하면 0).

    ⚠️ 출력이 비었거나 어느 보기와도 안 맞으면 **0** 이다. 그건 '정답이 틀렸다'
       가 아니라 '실행으로는 못 가린다' 는 뜻이다(코드가 지문일 뿐인 문항,
       'A가 몇 번 출력되는가' 처럼 출력 자체가 답이 아닌 문항).
    """
    if compiler is None:
        return 0
    res = qv.run_c(str(q.get("code") or ""), compiler)
    if not res.get("ok") or not str(res.get("out") or "").strip():
        return 0
    return qv.match_option(res["out"], q.get("options"))


def review_vote(client, q, course, votes: int = 2):
    """같은 문항을 여러 번 다시 풀려 **과반**을 따른다 → (번호, 사유).

    과반이 없으면 (-1, "") — 판단을 보류한다.

    ⚠️ 한 번의 검토는 흔들린다(실측: 같은 문항에 3번·4번·3번). 갈리는 문항을
       한 번의 답으로 빼면 멀쩡한 문항을 잃고, 반대로 정말 어긋난 문항을
       놓치기도 한다.
    """
    counts = {}
    for _ in range(max(1, int(votes))):
        got, why = qv.review_variant(client, q, course)
        if got < 0:
            continue
        counts.setdefault(got, []).append(why)
    total = sum(len(v) for v in counts.values())
    if not total:
        return (-1, "")
    best = max(counts, key=lambda k: len(counts[k]))
    if len(counts[best]) * 2 <= total:
        return (-1, "")             # 과반이 아니면 판단을 보류한다
    return (best, counts[best][0])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="변형 문항 검토")
    ap.add_argument("--course", default=COURSE)
    ap.add_argument("--year", type=int, help="이 연도 변형만")
    ap.add_argument("--limit", type=int, help="이만큼만(시험용)")
    ap.add_argument("--votes", type=int, default=2,
                    help="한 문항을 몇 번 다시 풀릴지(답이 갈리면 그대로 둔다)")
    ap.add_argument("--recheck", action="store_true",
                    help="이미 빼 둔 문항도 다시 검토한다")
    ap.add_argument("--apply", action="store_true",
                    help="어긋난 문항을 은행에 표시해 화면에서 뺀다")
    a = ap.parse_args(argv)

    from google import genai

    from config import load_config

    cfg = load_config()
    quiz_dir = Path(cfg.summary_dir) / "퀴즈"
    banks = variant_banks(quiz_dir, a.year)
    if not banks:
        _log("변형 은행이 없습니다. 먼저 build_variants.py 를 돌리세요.")
        return 1

    client = genai.Client(api_key=cfg.gemini_api_key)
    compiler = qv.find_compiler()
    _log("■ 코드가 있는 문항은 실제로 컴파일해 확인합니다"
         if compiler else
         "■ C 컴파일러가 없어 코드 문항도 모델 검토로만 봅니다"
         " (winget install -e --id BrechtSanders.WinLibs.POSIX.UCRT)")
    origins = origin_index(quiz_dir)
    total = bad = ok_run = 0
    for p, b in banks:
        qs = to_check(b, a.recheck)
        if a.limit:
            qs = qs[:a.limit]
        if not qs:
            continue
        _log(f"── {b.get('name')} — {len(qs)}문항 검토")
        drop, back, sure = {}, [], []
        for q in qs:
            total += 1
            # **실행결과를 묻는** 문항은 돌려서 확인한다. 실행이 보기 하나를
            # 딱 집어내면 그 말이 맞다 — 모델보다 세다.
            ran_no = run_verdict(q, compiler) if qv.needs_run(q) else 0
            if ran_no and ran_no == int(q.get("answer_no") or 0):
                verdict = ""            # 실행이 정답을 확인해 주었다
                ok_run += 1
                sure.append(str(q.get("qid")))
            elif ran_no:
                verdict = (f"실행하면 {ran_no}번이 답입니다"
                           f"({q.get('answer_no')}번으로 되어 있음)")
            else:
                # 부정형이 뒤바뀐 변형은 이미 위험 신호가 하나 있다 — 한 번
                # 더 물어 **과반**으로 가린다(두 번 물어 1:1 로 갈리는 바람에
                # 정작 어긋난 문항이 빠져나갔다).
                flip = qv.negation_flip(origins.get(str(q.get("origin"))), q)
                # 지문일 뿐인 코드는 출력이 없어 대조할 것이 없다 → 다시 풀린다
                got, why = review_vote(client, q, a.course,
                                       a.votes + 1 if flip else a.votes)
                verdict = qv.review_verdict(q, got, why)
                if verdict and flip:
                    verdict = f"원본의 부정형이 사라졌습니다 · {verdict}"
            if verdict:
                drop[str(q.get("qid"))] = verdict
                _log(f"   ✗ {q.get('qid')} {str(q.get('question'))[:38]}")
                _log(f"      {verdict}")
            elif str(q.get(SUSPECT_FIELD) or "").strip():
                back.append(str(q.get("qid")))      # 다시 보니 문제가 없다
                _log(f"   ↩ {q.get('qid')} 되돌림 — 문제가 없습니다")
        bad += len(drop)
        if (drop or back or sure) and a.apply:
            n = store_suspects(p, drop, back, sure)
            _log(f"   고침: {p.name} — {n}문항")

    _log(f"\n■ 검토 {total}문항 · 어긋난 것 {bad}개"
         + (f" · 실행으로 확인한 것 {ok_run}개" if ok_run else ""))
    if bad and not a.apply:
        _log("   --apply 를 붙이면 이 문항들을 화면에서 뺍니다"
             "(파일에는 사유와 함께 남습니다).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
