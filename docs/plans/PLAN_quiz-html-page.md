# Implementation Plan: 강의 퀴즈 복습 HTML 페이지 (돌발퀴즈 · 형성평가)

**Status**: 🔄 In Progress
**Started**: 2026-06-16
**Last Updated**: 2026-06-16
**Estimated Completion**: (미정)

---

**⚠️ CRITICAL INSTRUCTIONS**: 각 Phase 완료 후:
1. ✅ 완료한 task 체크박스 체크
2. 🧪 Quality Gate 검증 명령 실행
3. ⚠️ Quality Gate 항목 **전부** 통과 확인
4. 📅 위 "Last Updated" 갱신
5. 📝 Notes 섹션에 배운 점 기록
6. ➡️ 그 다음에만 다음 Phase 진행

⛔ **Quality Gate를 건너뛰거나 실패 상태로 다음 단계로 가지 말 것**

---

## 📋 Overview

### Feature Description
강의별 **돌발퀴즈**(영상 중 팝업)와 **형성평가(연습문제)** 문제를 캡처해, 나중에 **다시 풀어볼 수 있는 단일 HTML 페이지**로 만든다. 좌측 강의 목록 · 문제 카드 · 보기 선택 · "정답 보기"(정답+해설) · 진행률 · 강의 이동 · 초기화를 갖춘, 더블클릭으로 열리는 자체완결 파일.

데이터 출처는 LMS에서 실제로 출제된 문제다. 정답(`exqsCansCn`)·해설(`exqsExplCn`)은 답을 **제출한 후에만** 드러나므로, 형성평가 풀이(`_stage_exam`)·돌발퀴즈 처리(`watch._dismiss_quiz`) 흐름에 **캡처를 얹어** 모은다.

### Success Criteria
- [ ] 강의별 돌발퀴즈·형성평가 문제(문항·보기·정답·해설·출처)가 JSON으로 저장된다
- [ ] 모든 강의를 한 파일로 묶은 **자체완결 HTML**이 생성되고 브라우저에서 바로 열린다
- [ ] HTML에서 보기를 고르면 정오답이 표시되고, "정답 보기"로 정답+해설이 공개된다
- [ ] 강의 이동 · 진행률 · (현재/전체) 초기화가 동작한다(재풀이 상태는 localStorage)
- [ ] 비밀값·개인 데이터가 git에 올라가지 않는다(.gitignore)
- [ ] 전체 테스트 통과(기존 305 + 신규)

### User Impact
이수 자동화의 부산물로 **개인 복습용 문제은행**이 쌓이고, 시험 전 한 페이지에서 강의별로 다시 풀어볼 수 있다. 별도 입력·서버 없이 파일 하나로 끝난다.

---

## 🏗️ Architecture Decisions

| Decision | Rationale | Trade-offs |
|----------|-----------|------------|
| 데이터 출처 = LMS 실제 출제 문항(캡처) | 사용자가 원한 "그 강의의 돌발퀴즈/형성평가" 그대로 | 이수를 돌려야 데이터가 쌓임(미이수 강의는 비어있음) |
| 캡처를 `_stage_exam`/`_dismiss_quiz`에 얹음 | 정답·해설은 **제출 후**에만 드러남 → 풀이 시점이 유일한 캡처 기회 | 풀이/시청 흐름에 부수효과 추가(격리·예외안전 필요) |
| 저장 = 볼트 내 `퀴즈/{과목}_{seq}강.json` | 노트 옆, 과목·차시별 독립 파일 → 병합·재생성 쉬움 | 볼트 경로 의존(없으면 프로젝트 하위 fallback) |
| 출력 = **단일 자체완결 HTML**(CSS·JS 인라인) | 비개발자가 더블클릭만으로 열기, 서버·빌드 불필요 | 큰 강의 수면 파일이 커짐(허용 범위) |
| 정답/해설은 **기본 숨김**, JS·data-속성으로만 공개 | 첨부 이미지의 "정답 보기" 흐름, 재풀이 가치 보존 | 평문 노출 금지 → 렌더 시 이스케이프·인코딩 주의 |
| 힌트 **생략**(정답 보기만) | KNOU 문항엔 힌트 데이터가 없음(사용자 결정) | 이미지의 "힌트 보기" 버튼은 미구현 |
| 순수 로직(데이터모델·HTML 렌더)과 IO(스캔·앱연동) 분리 | 기존 프로젝트 철학(순수=단위테스트, LMS/IO=수동게이트) | 캡처 정확도는 라이브 수동검증에 의존 |

---

## 📦 Dependencies

### Required Before Starting
- [x] `_stage_exam`(형성평가 풀이) 파이프라인 존재 — 캡처를 얹을 지점 (커밋 2601b17)
- [x] `watch._dismiss_quiz`(돌발퀴즈 처리) — 캡처를 얹을 지점 (커밋 9551948)
- [x] 돌발퀴즈/형성평가 DOM 구조 파악 (recon `player_frame0.html`: `.exam-content-box`·`.answerCh`·`.exam-answer-message`·`span[name=exqsCansCn]`·`div.exqsExplCn`)
- [x] `config.summary_dir`(볼트 경로) — 저장 위치 기준

### External Dependencies
- 신규 외부 패키지 없음(표준 라이브러리 + 기존 Playwright). HTML 생성은 순수 문자열.

---

## 🧪 Test Strategy

### Testing Approach
**TDD 원칙**: 테스트 먼저 작성 → 통과시키는 최소 구현. 기존 프로젝트 관례에 맞춰 **순수 로직은 단위테스트, LMS/브라우저/파일열기는 수동 검증 게이트**.

### Test Pyramid for This Feature
| Test Type | Coverage Target | Purpose |
|-----------|-----------------|---------|
| **Unit Tests** | 순수 로직 ≥90% | 데이터 모델 정규화·병합·load/save, 스캔 raw→정규화 파싱, HTML 렌더 |
| **Integration Tests** | 핵심 경로 | 캡처→저장→렌더 한 사이클(픽스처 기반) |
| **Manual Gate (E2E)** | 1개 강의 | 실제 이수 중 캡처 → quiz.html 생성 → 브라우저에서 풀이 |

### Test File Organization
```
tests/
├── test_quizbank.py     # Phase 1: 데이터 모델·저장소(순수)
├── test_quiz_capture.py # Phase 2: 스캔 raw→정규화 파싱(순수)
└── test_quiz_html.py    # Phase 3: HTML 렌더(순수)
# Phase 4 통합은 기존 test_main.py / test_app_views.py / test_runner.py 에 보강
```

### Coverage Requirements by Phase
- **Phase 1**: `quizbank.py` 순수 함수 ≥90%
- **Phase 2**: 스캔 파싱 순수 함수 ≥90%(실제 스캔은 수동 게이트)
- **Phase 3**: `quiz_html.render_*` ≥90%
- **Phase 4**: 통합 배선(빌더/단계 등록) 단위테스트 + 수동 e2e 1경로

### Test Command (이 프로젝트)
```powershell
.venv\Scripts\python.exe -m pytest -q
# (선택) 커버리지: .venv\Scripts\python.exe -m pytest --cov=quizbank --cov=quiz_html --cov=quiz_capture
```
> 이 저장소는 별도 린터/타입체커 CI가 없다. 코드 스타일은 주변 코드와 일치(주석 밀도·명명·관용)로 맞추고, 테스트 그린을 1차 게이트로 삼는다.

---

## 🚀 Implementation Phases

### Phase 1: 퀴즈 데이터 모델 & 저장소 (`quizbank.py`)
**Goal**: LMS·HTML과 독립적인, 테스트된 문제 스키마 + 병합/저장/로드. 이 단계만으로 "문제 묶음을 정규화·합치고 JSON으로 저장/복원"이 동작한다.
**Estimated Time**: 2h
**Status**: ✅ Complete

#### Tasks

**🔴 RED**
- [x] **Test 1.1**: `tests/test_quizbank.py` — 순수 함수 실패 테스트(15개, 모듈 부재로 RED 확인)
  - `normalize_question(raw)` → 표준 dict(`qid, source, qtype, question, options[{no,text}], answer_no, answer_text, explanation`) 생성/누락 필드 기본값/멱등/qid 필수
  - `merge_questions(existing, new)` → `qid` 기준 중복제거(신규가 정답/해설 보강 시 갱신, 빈 값으론 안 덮음, 순서 보존)
  - `load_bank/save_bank` JSON 라운드트립(UTF-8, ensure_ascii=False), 깨진/없는 파일 안전
  - `bank_path(cfg, course, seq)` 경로 규칙(과목 sanitize, `퀴즈/{과목}_{seq}강.json`)
  - 비밀값 미포함, 빈 입력 안전

**🟢 GREEN**
- [x] **Task 1.2**: `quizbank.py` 구현 — 위 함수들(표준 라이브러리만)

**🔵 REFACTOR**
- [x] **Task 1.3**: `download.sanitize` 재사용(지연 임포트), `_prefer`/`_merge_one` 추출, docstring 정리

#### Quality Gate ✋
- [x] RED→GREEN→REFACTOR 순서 준수(테스트 먼저 실패 확인)
- [x] `pytest -q` 전부 통과(320 = 기존 305 + 신규 15)
- [x] `quizbank.py` 순수 함수 테스트(정규화/병합/저장로드/경로 전부 커버)
- [x] 순수 함수에 파일/네트워크 IO 없음(load/save/bank_path 제외)
- [x] 수동: `save_bank`→`load_bank` 라운드트립 + 한글 보존 테스트로 확인

---

### Phase 2: LMS에서 문제·정답·해설 스캔 (`quiz_capture.py`)
**Goal**: 플레이어 DOM에서 문항 stem·보기 텍스트·정답·해설·출처를 읽어 `quizbank` 형식으로 만든다. 풀이 직후(정답/해설이 드러난 상태) 스캔.
**Estimated Time**: 3h
**Status**: ✅ Complete (순수 파싱) · ⏳ 라이브 스캔 수동검증 대기

#### Tasks

**🔴 RED**
- [x] **Test 2.1**: `tests/test_quiz_capture.py` — `parse_scanned(raw)` 순수 파싱(7개)
  - 정답 번호→보기 텍스트 보강 / 정답 텍스트→보기 번호 매칭 / 미풀이(정답 없음) / qtype 기본값 / 출처 폴백 / 식별불가 스킵 / 빈 입력

**🟢 GREEN**
- [x] **Task 2.2**: `parse_scanned` + `_resolve_answer` 구현(순수)
- [x] **Task 2.3**: 스캔 JS + IO `scan_quiz(frame, source)` 구현 — `.exam-content-box`/`#quiz_*` form 에서 문항·보기(`.exam-answer-message` textContent, hwpjson 주석 자동 제외)·정답(`[name=exqsCansCn]`)·해설(`.exqsExplCn`) 읽기. 실패 시 [] 반환(흐름 보호).

**🔵 REFACTOR**
- [x] **Task 2.4**: `quizbank.normalize_question` 재사용으로 정규화 일원화

#### Quality Gate ✋
- [x] `parse_scanned` 순수 테스트 통과(7), `pytest -q` 그린
- [x] 비밀값/JWT URL 미포함(문항·정답·해설만)
- [ ] **수동 게이트(미완)**: 실제 한 강의 형성평가 풀이 후 `scan_quiz` 결과가 문항 본문(stem 셀렉터)·정답·해설을 옳게 담는지 라이브 1회 확인 → 필요 시 stem 셀렉터 보정

---

### Phase 3: 인터랙티브 HTML 생성기 (`quiz_html.py`)
**Goal**: `render_quiz_html(lectures)` → 첨부 이미지 스타일의 **단일 자체완결 HTML**. 좌측 강의 목록·문제 카드·보기 선택·정답 보기(정답+해설)·진행률·강의 이동·초기화(localStorage).
**Estimated Time**: 4h
**Status**: ✅ Complete (순수 렌더) · ⏳ 브라우저 동작 수동검증 대기

#### Tasks

**🔴 RED**
- [x] **Test 3.1**: `tests/test_quiz_html.py` (12개) — 문서/제목/문항·보기/이스케이프/정답 기본숨김(`data-answer-no`+`answer-box hidden`)/사이드바 N개/내비·초기화/진행률·정답보기/출처배지/단일파일(외부링크·CDN·http 없음)/빈 입력/비밀값

**🟢 GREEN**
- [x] **Task 3.2**: `quiz_html.render_quiz_html` 구현 — 서버렌더 카드 + 인라인 CSS(이미지 테마: 다크틸 사이드바·옵션카드·정답박스)·JS(보기선택·정답공개·진행률·강의전환·prev/next·초기화 localStorage)

**🔵 REFACTOR**
- [x] **Task 3.3**: `_render_option/_render_card/_render_lecture/_render_sidebar_item` 분리, `_esc/_escattr` 일원화, CSS/JS는 f-string 충돌 피해 정적 문자열

#### Quality Gate ✋
- [x] 순수 렌더 테스트 통과(12), `pytest -q` 그린(339)
- [x] 정답 평문 비노출(`data-answer-no` + `answer-box hidden`만, 테스트 단언)
- [ ] **수동(미완)**: `quiz_demo.html`(샘플) 브라우저에서 보기 선택/정답 보기/강의 이동/초기화 동작 확인

---

### Phase 4: 파이프라인 · 앱/CLI 연동
**Goal**: 이수 중 자동 캡처 + "퀴즈 페이지 만들기·열기" 동작으로 `강의퀴즈.html` 생성·열기.
**Estimated Time**: 3h
**Status**: ✅ Complete (배선/조립) · ⏳ 실제 이수 e2e 수동검증 대기

#### Tasks

**🔴 RED**
- [x] **Test 4.1**: `tests/test_quiz_page.py` (6개) — `collect_banks`(과목·차시 정렬·빈강 제외·없는폴더), `build_quiz_page`(렌더·빈폴더 안전), `persist_questions`(병합·보강·빈입력 no-op) + `test_app_views`에 "퀴즈 페이지 만들기" 버튼 테스트

**🟢 GREEN**
- [x] **Task 4.2**: `_stage_exam`에 캡처 연결 — 풀이 후 `scan_quiz(형성평가)`→`persist_questions`(예외 격리)
- [x] **Task 4.3**: `watch.watch_lecture(on_quiz=)` → `_play_until_end` → `_dismiss_quiz(on_quiz=)`로 돌발퀴즈 캡처(등록 직후, best-effort·격리). `_stage_watch`가 `scan_quiz(돌발퀴즈)`→persist 콜백 제공
- [x] **Task 4.4**: `quiz_page.write_quiz_page` + run_view "퀴즈 페이지 만들기" 버튼(`default_quiz_paths`→생성→`os.startfile`)

**🔵 REFACTOR**
- [x] **Task 4.5**: 캡처 저장을 `persist_questions` 한 곳으로 공통화, 로깅 일관화

#### Quality Gate ✋
- [x] `pytest -q` 전부 그린(346 = 기존 305 + 신규 41)
- [x] `.gitignore`에 `퀴즈/`·`quiz*.html`·`_quiz_*.py` 추가 — `quiz_demo.html` 미추적 확인
- [x] 캡처 전 구간 try/except → 캡처 실패가 이수/시청을 막지 않음(콜백·스테이지 모두 격리)
- [ ] **수동 e2e(미완)**: 한 강의 이수 → `퀴즈/{과목}_{seq}강.json` 생성 확인 → 앱 "퀴즈 페이지 만들기" → 브라우저에서 풀이

---

### Phase 5 (선택): 디자인 충실도 · 재풀이 UX 마무리
**Goal**: 첨부 이미지에 맞춘 스타일 정밀화 + 재풀이 편의.
**Estimated Time**: 2h
**Status**: ✅ Complete (코드) · ⏳ 실데이터 시각 비교 수동검증 대기

#### Tasks
- [x] **Task 5.1**: 진행률 카드 "N / N" + "N문제 풀이" 라벨 + 그라데이션 바, 정답/오답 색상, 출처 배지(이미지 맞춤). 마크업 단언 테스트 2개 추가
- [x] **Task 5.2**: 재풀이 상태 localStorage 저장/복원 + "현재 강 초기화"·"전체 초기화"(Phase 3 구현, 유지)
- [x] **Task 5.3**: 반응형(@media 760px 사이드바 가로 배치), 정답 박스 헤더('정답') 정리
- [x] **Task 5.4**: README·README_GUI 에 "퀴즈 복습 페이지" 사용법 단락 + 기능 불릿 추가

#### Quality Gate ✋
- [x] `pytest -q` 그린(348), 마크업 단언 통과
- [ ] **수동(미완)**: `quiz_demo.html` 실데이터/이미지와 레이아웃·색·동작 비교

---

## ⚠️ Risk Assessment

| Risk | Probability | Impact | Mitigation |
|------|-------------|--------|------------|
| 보기/문항이 HWP 렌더 HTML(수식·이미지·거대한 json 주석) | High | Med | `.exam-answer-message`의 가독 텍스트만 추출, 실패 시 정제된 HTML/원문 fallback. 수식/이미지는 후속 과제로 분리 |
| 정답·해설은 제출 후에만 노출 → 이미 이수한 강의는 재스캔 시 결과뷰 의존 | Med | Med | 풀이 시점 캡처를 기본으로. 기존 완료 강의는 결과 화면 스캔 best-effort, 안되면 다음 재실행에서 보강 |
| 돌발퀴즈 캡처는 영상 중 타이밍 민감 | Med | Low | 형성평가를 주 데이터원으로, 돌발퀴즈는 best-effort. 캡처 실패가 시청을 막지 않게 예외 격리 |
| 캡처 부수효과가 이수/시청 흐름을 깨뜨림 | Low | High | 캡처 전 구간 try/except, 단계 결과는 캡처와 독립. 단위테스트로 격리 보장 |
| 개인 문제·정답 데이터 유출 | Low | High | bank JSON·quiz.html `.gitignore`. 렌더 출력에 비밀값 미포함 테스트 |
| 단일 HTML 비대화(강의 많을 때) | Low | Low | 강의별 지연 로드(JS)로 표시, 데이터는 한 번에 임베드(허용) |

---

## 🔄 Rollback Strategy

> 기능이 신규 파일 위주라 롤백이 단순하다. 각 Phase는 독립 커밋으로.

### If Phase 1 Fails
- `quizbank.py`, `tests/test_quizbank.py` 삭제(또는 커밋 revert). 기존 코드 영향 없음.

### If Phase 2 Fails
- `quiz_capture.py`, `tests/test_quiz_capture.py` 삭제. `exercise.py` 공용 추출했다면 그 변경만 revert.

### If Phase 3 Fails
- `quiz_html.py`, `tests/test_quiz_html.py` 삭제.

### If Phase 4 Fails
- `_stage_exam`/`_dismiss_quiz`의 캡처 호출 줄 제거(부수효과 한 줄), 진입점/버튼 제거. 데이터 모델·렌더는 보존.

### If Phase 5 Fails
- 스타일/문서 변경만 revert. 기능 동작 유지.

---

## 📊 Progress Tracking

### Completion Status
- **Phase 1**: ✅ 100%
- **Phase 2**: ✅ 100% (순수) · 라이브 스캔 수동검증 대기
- **Phase 3**: ✅ 100% (순수 렌더) · 브라우저 동작 수동검증 대기
- **Phase 4**: ✅ 100% (배선/조립) · 실제 이수 e2e 수동검증 대기
- **Phase 5(선택)**: ✅ 100% (코드) · 실데이터 시각 비교 대기

**Overall Progress**: 전 5단계 코드 완료(100%). 남은 것 = 라이브 수동검증(형성평가 stem 셀렉터·이수 e2e·디자인 시각 비교)

### Time Tracking
| Phase | Estimated | Actual | Variance |
|-------|-----------|--------|----------|
| Phase 1 | 2h | - | - |
| Phase 2 | 3h | - | - |
| Phase 3 | 4h | - | - |
| Phase 4 | 3h | - | - |
| Phase 5(선택) | 2h | - | - |
| **Total** | 12~14h | - | - |

---

## 📝 Notes & Learnings

### Implementation Notes
- 정답·해설(`exqsCansCn`/`exqsExplCn`)은 `registerUSTStudyExamRslt.ajax` 응답(`fnExqsCallback`의 `data.vo`)과 풀이 후 `.confirmDiv` DOM 양쪽에 나타남 → 어느 쪽이든 캡처 가능. DOM 스캔이 구현 단순.
- 출처 라벨은 첨부 이미지의 "기존" 배지 자리에 `형성평가`/`돌발퀴즈`로 매핑.

### Blockers Encountered
- (없음 — 작성 시점)

### Improvements for Future Plans
- 후속: 수식/이미지 보기 렌더, 오답노트, 통계(강의별 정답률) — 본 계획 범위 밖.

---

## 📚 References
- 디자인 참고: 사용자 첨부 이미지(파이썬 강의 퀴즈 스타일 — 사이드바·문제카드·정답 보기·진행률)
- DOM 구조: `recon_shots/player_frame0.html`(`.exam-content-box`, `.answerCh`, `.exam-answer-message`, `span[name=exqsCansCn]`, `div.exqsExplCn`, `.confirmAnswer`, `.quizClose`)
- 통합 지점: `main.py:_stage_exam`, `watch.py:_dismiss_quiz`, `exercise.py:scan_questions`, `config.summary_dir`

---

**Plan Status**: ✅ 전 5단계 코드 완료 — 라이브 수동검증만 남음
**Next Action**: 실제 한 강의 이수로 e2e 검증(형성평가 stem 셀렉터·정답/해설 캡처 확인) → 필요 시 stem 셀렉터 보정
**Blocked By**: None
