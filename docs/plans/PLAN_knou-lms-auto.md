# PLAN: 방송대(KNOU) LMS 자동화 — 영상 자동이수 + 강의 요약

> **CRITICAL INSTRUCTIONS**: 각 Phase 완료 후:
> 1. ✅ 완료한 작업 체크박스 체크
> 2. 🧪 Quality Gate 검증 항목 모두 실행
> 3. ⚠️ Quality Gate 전부 통과 확인
> 4. 📅 "Last Updated" 날짜 갱신
> 5. 📝 Notes 섹션에 배운 점 기록
> 6. ➡️ 그 다음에만 다음 Phase로 진행
>
> ⛔ Quality Gate를 건너뛰거나 실패한 상태로 진행하지 말 것

- **Last Updated**: 2026-05-30
- **Status**: ✅ Phase 1~7 완료(자동이수+다운로드+요약+화면캡처+슬라이드 일치보정+전과목 조율 main.py 실측 검증) → 🔜 Phase 8(자동 예약 실행) 진입
- **Scope**: Large (9 phases, 약 18~26시간)
- **Stack**: Python 3.11+ / Playwright / Gemini API → 옵시디언 볼트

---

## 1. Overview & Objectives

방송대 LMS의 **형성평가 동영상을 자동으로 이수**하고, **강의 내용을 Gemini로 자동 요약**해 옵시디언 볼트에 저장하는 개인 학습 도구.

### 목표
- [ ] 수강 중 **전과목**의 미이수 동영상을 배속 재생으로 자동 이수 (서버 진도 충족)
- [ ] 강의별 **MP3(음성) + PDF(강의록)** 다운로드
- [ ] Gemini로 **요약 마크다운 노트** 자동 생성 (각 핵심 개념에 **영상 타임스탬프** 표기) → 옵시디언 볼트 저장
- [ ] 핵심 개념마다 **영상 화면 캡처 이미지**를 노트에 삽입 (DRM 시 PDF 슬라이드로 대체)
- [ ] 전과목 일괄 실행 + 중단 시 이어서 + 자동 예약 실행

### 사용자 컨텍스트
- 코딩 경험: **기초 수준** → 단계는 작게, 설명은 복붙 가능한 수준으로
- 영상은 나중에 직접 볼 예정(예습용) → **요약(Phase 4-5)은 이수(Phase 3)와 독립 실행 가능**하게 설계
- 로그인: 아이디/비밀번호만 (2FA 없음)
- 이수 조건: **실제 재생시간 필요** (배속 허용)

---

## 2. Architecture Decisions

| 결정 | 내용 | 이유 |
|------|------|------|
| Playwright (sync API) | 브라우저 자동화 | 초보자 친화, Chromium 자동설치, auto-wait |
| **영속 세션** (persistent context) | 로그인 세션 디스크 저장 | 매번 재로그인 방지 |
| **진짜 Chrome/Edge 채널 사용** (`channel="chrome"`) | 내장 Chromium 대신 설치된 Chrome 사용 | 내장 Chromium엔 H.264/AAC 코덱이 없어 강의 영상 재생 불가 → 진짜 브라우저 필수 |
| 모듈 분리 | `auth/discover/watch/download/summarize/main` | 한 파일씩 만들고 검증 |
| `.env` + python-dotenv | 자격증명/경로 분리 | 비밀번호 코드에 하드코딩 금지 |
| 상태 파일 (JSON) | 진행상황 기록 | 중단 후 이어서, 중복작업 skip |
| **영상 이수 = 시간 예산 방식** | `(total-watched)/배속`만큼 재생 후 검증 | 레퍼런스 검증된 방식, 폴링보다 단순/확실 |
| 화면 캡처 = Playwright seek+screenshot | 타임스탬프 지점으로 이동 후 플레이어 스크린샷 | 영상 파일 다운로드 불필요, watch와 같은 브라우저 재사용 |
| 캡처 fallback = PDF 슬라이드 추출 | DRM으로 검은화면 시 강의록 PDF 페이지를 이미지로 | DRM 영향 없음, 슬라이드 = 영상 화면과 동일 |
| TDD 현실 적용 | 순수 로직만 단위테스트, 브라우저/AI는 수동 검증 게이트 | 라이브 LMS·AI는 단위테스트 비현실적 |

### 프로젝트 구조 (목표)
```
knou/
├─ .env                  # KNOU_ID, KNOU_PW, GEMINI_API_KEY, VAULT_PATH 등 (gitignore)
├─ .env.example          # 키 이름만 (커밋용)
├─ requirements.txt
├─ config.py             # env 로드 + 상수(배속, 경로 등)
├─ auth.py               # 로그인 + 세션
├─ discover.py           # 과목·강의·진도 수집
├─ watch.py              # 동영상 자동이수
├─ download.py           # MP3 + PDF 다운로드
├─ summarize.py          # Gemini 요약(+타임스탬프) → md
├─ capture.py            # 타임스탬프 화면 캡처 / PDF 슬라이드 추출 → md에 이미지 삽입
├─ main.py               # 전과목 조율
├─ tests/                # pytest (순수 로직)
├─ logs/                 # 실행 로그
├─ downloads/            # 받은 자료
├─ .auth/                # 저장된 브라우저 세션 (gitignore)
├─ state.json            # 진행상황 (gitignore)
└─ docs/
   ├─ plans/PLAN_knou-lms-auto.md   # 이 문서
   └─ lms-map.md         # Phase 0 정찰 결과(셀렉터·URL)
```

---

## 3. Phases

### Phase 0 — 환경 셋업 & LMS 정찰 (1-2h)
**Goal**: Python+Playwright 환경 동작 + LMS 구조를 직접 열어보며 셀렉터/URL을 문서화 (이후 모든 단계의 기반)

**Test Strategy**: 코드 거의 없음 → 수동 검증 위주. `config.py`의 env 로드만 단위테스트.

**Tasks**:
- [x] Python venv 생성, `pip install playwright python-dotenv pytest google-genai PyMuPDF` (Python 3.14.2, 전부 설치 성공)
- [x] `playwright install chromium`
- [x] `.env.example` 작성 (`KNOU_ID`, `KNOU_PW`, `GEMINI_API_KEY`, `VAULT_PATH` 등) / **`.env`는 사용자가 채워야 함**
- [x] **(RED)** `tests/test_config.py`: env 누락 시 명확한 에러, 정상 로드 검증
- [x] **(GREEN)** `config.py` 작성 → 테스트 7개 통과
- [x] 정찰 스크립트 `recon.py`: persistent context로 브라우저 띄움 + 스크린샷/DRM밝기/seek 정보 출력 + `page.pause()`
- [ ] ▶ **사용자 실행**: `recon.py` 돌려 로그인 → 강의목록 → 강의 1개 → 플레이어 → 자료 위치 확인
- [ ] ▶ **사용자 실행**: **형성평가가 단순 출석 체크인지 / 실제 문제풀이가 필요한지** 직접 확인
- [ ] ▶ **사용자 실행**: **🔑 DRM 테스트** — `recon.py`가 찍은 `recon_shots/02_video.png`가 검은화면인지 확인 (검으면 Phase 6은 PDF 슬라이드 fallback)
- [ ] ▶ **사용자 실행**: 영상 **seek** 방법 확인 (`recon.py`가 video.currentTime 가능 여부 출력)
- [x] `docs/lms-map.md` **템플릿** 생성 (정찰 결과 기록용)
- [ ] ▶ **사용자 기입**: `docs/lms-map.md` 채우기 (셀렉터·URL·DRM·seek·자료링크·형성평가)
- [ ] ▶ **사용자 결정**: 옵시디언 요약 저장 폴더 확정 (예: `1.4. CS/방송대/`) → `.env`의 `VAULT_PATH`/`SUMMARY_SUBDIR`에 기록

**Quality Gate**:
- [ ] `pytest tests/test_config.py` 통과
- [ ] 브라우저가 뜨고 LMS 로그인/강의목록/플레이어 페이지가 열림
- [ ] `docs/lms-map.md`에 핵심 셀렉터·URL이 적혀 있음
- [ ] 형성평가 이수 메커니즘(클릭 vs 문제풀이)이 문서에 정리됨
- [ ] **플레이어 스크린샷 검은화면 여부 + seek 방법**이 문서에 기록됨 (Phase 6 경로 결정)

**Dependencies**: 없음
**Rollback**: 폴더/가상환경 삭제

---

### Phase 1 — 로그인 & 세션 유지 (1-2h)
**Goal**: `.env`의 아이디/비번으로 자동 로그인하고 세션을 저장(다음 실행 시 재로그인 최소화)

**Test Strategy**: "로그인됨?" 판정 로직을 HTML 스니펫 기반으로 단위테스트. 실제 로그인은 수동 검증.

**Tasks**:
- [ ] **(RED)** `tests/test_auth.py`: 자격증명 로드, `is_logged_in(html)` 판정 로직 테스트 → 실패 확인
- [ ] **(GREEN)** `auth.py`: persistent context로 브라우저 실행 → 로그인 폼 채우기 → 제출 → 로그인 확인
- [ ] 세션 저장 경로 `.auth/` 적용, 2회차 실행 시 세션 재사용 분기
- [ ] **(REFACTOR)** 로그인 실패(비번 오류 등) 시 명확한 에러 메시지
- [ ] `.gitignore`에 `.env`, `.auth/`, `state.json`, `downloads/`, `logs/` 추가

**Quality Gate**:
- [ ] `pytest` 전체 통과
- [ ] 실행하면 자동 로그인되어 대시보드 도달 (수동 확인)
- [ ] 두 번째 실행은 세션 재사용 (재로그인 안 함)
- [ ] 비밀번호가 로그/코드에 노출되지 않음

**Dependencies**: Phase 0
**Rollback**: `auth.py`, `.auth/` 삭제

---

### Phase 2 — 강의 목록 & 진도 파악 (2-3h)
**Goal**: 전과목 → 강의별 (제목, 회차, 이수여부, 진도 "17분/75분") 구조화 리스트 수집

**Test Strategy**: 진도 파서·필터 로직을 단위테스트(HTML/문자열 입력).

**Tasks**:
- [ ] **(RED)** `tests/test_discover.py`:
  - `parse_progress("17분 / 75분")` → `{"watched":17,"total":75,"complete":False}`
  - `filter_incomplete(lectures)` → 미이수만 반환
  - → 실패 확인
- [ ] **(GREEN)** `discover.py`: 과목 목록 수집 → 각 과목 강의 목록·진도 수집 → dict 리스트 반환
- [ ] 결과를 콘솔 + `state.json`에 출력
- [ ] **(REFACTOR)** 과목/강의 데이터 모델 정리 (dataclass)

**Quality Gate**:
- [ ] `pytest` 전체 통과
- [ ] 전과목 강의 목록 + 이수상태가 정확히 출력됨 (LMS 화면과 대조 확인)
- [ ] 미이수 강의 필터링 정상

**Dependencies**: Phase 1
**Rollback**: `discover.py` 삭제

---

### Phase 3 — 🎬 동영상 자동 이수 (3-4h) [핵심]
**Goal**: 미이수 강의를 **시간 예산(time-budget) 방식**으로 자동 이수 — 재생 후 검증까지.

**핵심 로직 (레퍼런스 제작자가 공개한 방식 + 검증 단계 추가):**
1. 대시보드에서 `total`(전체시간), `watched`(학습시간) 읽기 → `remaining = total - watched`
2. 실제 대기 시간 `wait = remaining / 배속` 계산 (예: 58분 ÷ 2.0 = 29분). 버퍼링 대비 **여유(+10~15%)** 추가
3. 배속 설정 + 재생 시작 → `wait`만큼 벽시계 시간 대기 (서버 폴링은 *보조 안전장치*로만 가끔 확인)
4. **학습종료 후 재확인(verify)**: 대시보드 다시 읽어 이수 완료인지 확인
5. 미완료면 부족분만큼 **보충 재생(top-up)** 후 재검증 (최대 N회)

> ⚠️ 지름길 없음: 서버가 실제 재생시간을 요구하므로 `remaining/배속`만큼 벽시계 시간은 반드시 소요됨 → 전과목은 길어짐(야간 예약 Phase 8). 탭이 백그라운드면 플레이어가 throttle될 수 있으니 **재생 탭을 활성 상태로 유지**.

**Test Strategy**: 시간계산·검증·보충 판정 등 순수 로직을 단위테스트. 실제 재생은 한 강의로 수동 검증.

**Tasks**:
- [ ] **(RED)** `tests/test_watch.py`:
  - `remaining_minutes(total, watched)` → 음수면 0
  - `wall_clock_seconds(remaining_min, speed, buffer=0.12)` → `(remaining*60/speed)*(1+buffer)` (예: 58,2.0 → ≈1949s)
  - `is_complete(total, watched)` → watched >= total(또는 임계)
  - `needs_topup(total, watched_after)` → 검증 후 부족 여부
  - → 실패 확인
- [x] **(GREEN)** `watch.py`: 플레이어 열기 → 클립 인벤토리 → 배속 설정 → **위치기반 종료감지(_play_until_end)** → 저장(fnPlayStop) → done 재확인. *time-budget 대신 실측 위치추적이 더 정확 → 채택.*
- [x] "이어보기" 모달 처리(2종 id 기반, wp_elearning_play 금지), 형성평가 퀴즈(돌발퀴즈) dismiss 처리
- [x] 탭 활성 유지 / 재생 멈춤(stall) 감지 시 배속 재적용 + 퀴즈 dismiss
- [x] 강의 1개를 끝까지 자동 이수 (15강 풀 파일럿: video_done False→True, +102분/55실분, 2배속)
- [x] **(REFACTOR)** 진행 로그(클립별 상태/배속/SAVE XHR) 출력 (watch_one.py)
- [x] **(추가)** 연습문제 자동 풀이 `exercise.py`(정오답 무관 2-클릭) — 15강 exam_done False→True 검증

**Quality Gate**:
- [x] `pytest` 전체 통과 (시간계산 공식 검증 포함 — test_watch.py)
- [x] 강의 1개가 끝까지 자동 이수됨 (LMS video_done=Y + 재확인 통과)
- [x] 예상 소요시간이 로그에 정확히 출력됨 (wall_clock_seconds/budget)
- [x] 중간에 끊고 다시 실행하면 남은 분량만 이어서 진행 (15강 728초부터 이어보기, 0재시작 없음)
- [~] verify 실패 시 top-up — 현재는 위치기반 종료감지로 1회 완주. 명시적 top-up 루프는 Phase 7 조율에서 보강 예정
- [x] 형성평가(연습문제)가 정상 처리됨

**Dependencies**: Phase 2 (대시보드의 total/watched 수집)
**Rollback**: `watch.py` 삭제 (이미 이수된 강의는 LMS에 남음 — 되돌릴 필요 없음)

---

### Phase 4 — 강의자료 다운로드 (MP3 + PDF) (2h)
**Goal**: 강의별 MP3(음성) + PDF(강의록) 다운로드, 이미 받은 건 skip

**Test Strategy**: 파일명 빌더·중복 skip 로직 단위테스트.

**Tasks**:
- [x] **(RED)** `tests/test_download.py`: build_filename/needs_download/sanitize/build_file_url/match_pdf_post (12개)
- [x] **(GREEN)** `download.py`: MP3는 lectlist `strVidoAudoUrl`(Lecture.audio_url) 직접, PDF는 강의자료실 게시판 매칭(분류 '강의자료' + apndFileNm 'NN-' 접두사) → `/user_uploading` GET → `downloads/`에 저장
- [x] **(REFACTOR)** 다운로드 진행/완료 로그 + HTML 에러응답 방어 + 멱등 skip
- [x] **(추가 정찰)** 강의자료실 구조 확정(probe_data/2/3.py): initUCRLectureData.ajax 글목록, /user_uploading 다운로드

**Quality Gate**:
- [x] `pytest` 전체 통과 (41개)
- [x] 강의 1개 자료가 정확한 이름으로 `downloads/`에 저장됨 (이산수학 1강: MP3 39.9MB `ID3`, PDF 2.2MB `%PDF-1.5`)
- [x] 재실행 시 기존 파일 skip (멱등 검증 완료)

**Dependencies**: Phase 2 (강의 목록). Phase 3와 독립 실행 가능.
**Rollback**: `download.py` 삭제, `downloads/` 정리

---

### Phase 5 — 🤖 Gemini 요약 + 타임스탬프 → 옵시디언 (3-4h)
**Goal**: MP3+PDF를 Gemini에 업로드 → 요약 마크다운 생성(**각 핵심 개념에 영상 타임스탬프 표기**) → 볼트 저장. 캡처용 타임스탬프 목록도 별도 산출.

**Test Strategy**: 프롬프트 빌더·파일경로·타임스탬프 파서·중복 skip을 단위테스트. 실제 AI 호출은 한 강의로 수동 검증.

**Tasks**:
- [x] **(RED)** `tests/test_summarize.py` (14 tests):
  - `build_prompt(subject, seq, name)` → "[HH:MM:SS] 표기 / 음성기준 근사치" 지시 포함 검증
  - `extract_timestamps(md)` → `[{"timestamp":"00:01:30","seconds":90,"label":"..."}, ...]` 추출(초 기준 dedupe, 마커 제거)
  - `timestamp_to_seconds` / `seconds_to_timestamp` 왕복
  - `note_filename(subject,seq,name)` → `이산수학 1강 - 이산수학의 개요.md` (sanitize)
  - `needs_summary(path)` 이미 있으면 False
  - → 실패 확인
- [x] **(GREEN)** `summarize.py`: google-genai로 MP3+PDF 업로드 → 구조화 요약(개념별 `🎬 [HH:MM:SS]` + 추정 강의록 페이지 `(교재 p.N)`) → 마크다운 + `.timestamps.json` 산출 → 볼트 저장
- [x] 프롬프트에 "타임스탬프는 음성 기준, 근사치 허용" 명시 / 대용량 오디오(40MB MP3) 대응
- [x] **(REFACTOR)** 라벨 정리(볼드/이모지/잔여구두점 제거), 한글 파일명 업로드 우회(파일객체+명시 mime_type)

**Quality Gate**:
- [x] `pytest` 전체 통과 (55 passed)
- [x] 강의 1개 요약 `.md`가 볼트에 생성, 개념마다 타임스탬프가 붙어 있음 (이산수학 1강, 12개 타임스탬프)
- [x] `capture.py`가 쓸 타임스탬프 JSON(`*.timestamps.json`)이 산출됨
- [x] Gemini API 키가 로그에 노출되지 않음 / 재실행 시 skip(`needs_summary`)

**Dependencies**: Phase 4 (자료). Phase 3와 독립 실행 가능.
**Rollback**: `summarize.py` 삭제, 생성된 노트 정리

---

### Phase 6 — 🎞️ 동영상 프레임 캡처 & 슬라이드 매핑 (3-4h)
**Goal**: Phase 5가 뽑은 타임스탬프마다 화면 이미지를 확보해 요약 노트에 삽입. 1순위 = 플레이어 스크린샷, fallback = PDF 강의록 슬라이드.

**Test Strategy**: 이미지 파일명·ffmpeg 명령·길이매칭 클립선택·캡처필요판정·인라인 임베드 로직을 단위테스트. 실제 캡처는 한 강의 수동 검증.

**채택 방식(확정)**: **ffmpeg HLS 프레임 추출**(DRM 차단 없음 확정 → 스크린샷/PDF fallback 불필요).
영상은 차시당 여러 클립(오리엔테이션/들어가기/학습하기/정리하기/…)으로 쪼개져 있고,
요약 MP3 = **길이가 가장 가까운 클립과 1:1 일치** → 그 클립을 절대초로 seek.

**Tasks**:
- [x] **(RED)** `tests/test_capture.py` (17 tests):
  - `capture_filename(subject,seq,seconds)` → `이산수학_1강_00-04-50.jpg` (sanitize, ':'→'-')
  - `pick_clip_by_duration(clips, target)` → MP3 길이에 가장 가까운 클립 선택
  - `build_ffmpeg_cmd(url,sec,out)` → `-ss`가 `-i` 앞(fast seek), `-frames:v 1`, `-y`
  - `needs_capture(path)` 없음/0바이트면 True
  - `embed_captures(md, {sec:fn})` → 타임스탬프 줄 아래 `![[fn]]` 삽입(멱등)
  - → 실패 확인
- [x] **(GREEN)** `capture.py`: 플레이어에서 클립 조회(`ifrmVODPlayer_dataN`→hlsUrl) → ffprobe 길이 →
  MP3 길이로 매칭 → 타임스탬프마다 ffmpeg 단일 프레임(jpg) → 노트 인라인 임베드
- [x] 캡처 이미지를 볼트 `_captures/` 하위에 저장, 요약 노트의 해당 개념 줄 아래 `![[..]]` 임베드
- [x] **(REFACTOR)** 토큰(JWT, ~2h) 세션 유지 위해 팝업 열어둔 채 캡처 / 재실행 시 skip(`needs_capture`)

**Quality Gate**:
- [x] `pytest` 전체 통과 (72 passed)
- [x] 강의 1개 요약 노트에 개념별 화면 이미지 삽입(이산수학 1강 12개 캡처, 73~156KB, 슬라이드 선명)
- [x] 캡처 위치 정확도: 선택 클립이 MP3와 0.0s 차 / 프레임이 라벨 내용과 일치(13:58 'What? 이산수학' 등)
- [x] 캡처 실패해도 노트 자체는 깨지지 않음(성공/기존분만 임베드)

**Dependencies**: Phase 5 (타임스탬프), Phase 0 (DRM 판정=차단없음). 클립 조회는 Phase 1 세션 + Phase 3 플레이어 오픈 재사용.
**Rollback**: `capture.py` 삭제, 첨부 이미지·임베드 정리

---

### Phase 7 — 전과목 일괄 조율 (2-3h)
**Goal**: `main.py`가 전과목 순회: (이수 → 다운로드 → 요약 → 캡처), 로깅, 이미 done이면 skip, 한 강의 실패해도 계속

**Test Strategy**: 조율 skip/resume 로직·강의별 상태 추적 단위테스트.

**Tasks**:
- [x] **(RED)** `tests/test_main.py` (22 tests): `stages_for_mode`/`lecture_key`/`stage_done`/`lecture_done`/`mark_stage`/`select_lectures`/`pending_lectures` 상태·필터 로직 → 실패 확인
- [x] **(GREEN)** `main.py`: 브라우저 1회 기동+로그인 → 전과목 강의 수집 → 모드별 단계 호출(watch→download→summarize→capture), 단계마다 `state.json` 원자적 갱신
- [x] CLI 옵션: `--mode 이수|요약|전체` + `--course`(부분일치) + `--seq`(차시) 필터 (예습용 요약만 따로 돌리기)
- [x] try/except로 강의·단계 단위 실패 격리 → 다음 강의 진행, 실패+에러 state 기록·로그
- [x] **(REFACTOR)** `logs/run_{ts}.log` 콘솔+파일 동시 로깅, summarize/capture만 genai.Client 생성(이수 모드 0비용)

**Quality Gate**:
- [x] `pytest` 전체 통과 (110 passed: main.py 22 + 기존 88)
- [x] 단일강의 스모크(요약, 이산수학 1강) 완주 — download skip→summarize skip→capture 클립매칭+임베드 skip(비전 0비용)
- [x] 단계 실패 시 해당 강의만 break, 다른 강의 계속(강의 단위 try/except 격리)
- [x] 재실행 시 done 강의 lecture 단위 skip (idempotency: 처리 0 / 사전skip 1)
- [x] 로그 파일 생성됨 (`logs/run_*.log`) + `state.json` 단계별 ok/at 기록

**Dependencies**: Phase 3, 4, 5, 6
**Rollback**: `main.py` 이전 버전 복원

---

### Phase 8 — 자동 예약 실행 (1-2h)
**Goal**: Windows 작업 스케줄러로 정해진 시각(예: 새벽) 자동 실행

**Test Strategy**: 코드 변경 적음 → 수동 검증 위주.

**Tasks**:
- [ ] 실행 진입점 `run.ps1` 또는 배치 (venv 활성화 + `python main.py`)
- [ ] Windows 작업 스케줄러 등록 (정해진 시각 트리거)
- [ ] 예약 실행 결과가 `logs/`에 남는지 확인
- [ ] (선택) `/schedule` 스킬로 대체 검토

**Quality Gate**:
- [ ] 예약 시각에 자동 실행되어 로그 생성됨
- [ ] 세션 만료 시 자동 재로그인 동작

**Dependencies**: Phase 7
**Rollback**: 작업 스케줄러 항목 삭제

---

## 4. Risk Assessment

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| LMS DOM 미지 / 셀렉터 변경 | High | High | Phase 0 정찰 우선, `lms-map.md`로 셀렉터 중앙 관리 |
| 형성평가가 실제 문제풀이 요구 | Med | Med | Phase 0에서 확인 후 Phase 3 분기 설계 |
| **DRM으로 화면 스크린샷 검은화면** | Med | Med | Phase 0에서 미리 1장 테스트 → PDF 강의록 슬라이드 추출 fallback(Phase 6) |
| 타임스탬프 부정확(근사치) | Med | Low | "약 32분" 식 표기, 영상 seek 시 여유 |
| 전과목 실제 재생 = 장시간 | High | Med | 배속 + 야간 예약 실행(Phase 8) |
| Gemini 무료 한도/대용량 오디오 | Med | Med | PDF 우선 요약, 필요 시 청크 분할 |
| 세션 만료 | Med | Low | persistent context + 자동 재로그인 |
| 자격증명 노출 | Low | High | `.env` + `.gitignore`, 로그 마스킹 |

> ⚠️ **참고**: 본 도구는 본인 계정·예습 목적의 개인 학습 자동화. 학교 LMS 이용약관/학칙 준수 여부는 사용자 책임 영역.

---

## 5. Progress Tracking

| Phase | 상태 | 완료일 |
|-------|------|--------|
| 0. 환경셋업 & 정찰 | ✅ 완료 | 2026-05-28 |
| 1. 로그인 & 세션 | ✅ 완료 (force-fresh 단일세션) | 2026-05-29 |
| 2. 강의목록 & 진도 | ✅ 완료 (video_done/exam_done 파싱) | 2026-05-29 |
| 3. 동영상 자동이수 | ✅ 완료 (15강 풀 파일럿 + 연습문제 실측 검증) | 2026-05-29 |
| 4. 자료 다운로드 | ✅ 완료 (이산수학 1강 MP3+PDF 실측) | 2026-05-30 |
| 5. Gemini 요약 + 타임스탬프 | ✅ 완료 (이산수학 1강 요약노트+타임스탬프 12개 실측) | 2026-05-30 |
| 6. 화면 캡처 & 슬라이드 매핑 | ✅ 완료 (ffmpeg HLS, 이산수학 1강 12프레임 실측) | 2026-05-30 |
| 6.5 비전 프레임 검증 | ✅ 완료 (Gemini 비전 슬라이드 일치보정, 1강 6/12 교정 실측) | 2026-05-30 |
| 7. 전과목 조율 | ✅ 완료 (main.py 모드+필터 CLI, 요약 스모크+재실행 skip 실측) | 2026-05-30 |
| 8. 자동 예약 실행 | ⬜ 대기 | - |

상태 범례: ⬜ 대기 / 🔄 진행중 / ✅ 완료 / ⚠️ 막힘

---

## 6. Notes & Learnings

> 각 Phase 진행하며 배운 점, 막힌 점, LMS 특이사항을 여기에 기록.

- (Phase 0) Python 3.14.2 환경. 패키지(playwright 1.60, google-genai 2.6, PyMuPDF 1.27 등) 전부 정상 설치. PowerShell 도구가 이 환경에선 응답 안 함 → **Bash(Git Bash) 사용**. venv python 경로: `.venv/Scripts/python.exe`.
- (Phase 0) ⚠️ **내장 Chromium은 동영상 코덱(H.264/AAC) 없음 → 강의 영상 재생 불가 + 로그인 화면 깨짐**. 해결: `launch_persistent_context(channel="chrome")`로 설치된 진짜 Chrome 사용(없으면 msedge). recon.py에 chrome→msedge→내장 순 fallback 구현. **Phase 1~3의 브라우저 실행도 동일하게 channel="chrome" 적용 필수.**
- (Phase 0) LMS 도메인 확정: `ucampus.knou.ac.kr`. 나의학습 페이지: `retrieveUMYStudy.sdo`. 사용자: 코딩 완전 초보 → 실행은 더블클릭 `.bat`(순수 ASCII로, 한글 넣으면 cmd가 깨뜨림)로 제공.
- (Phase 3 설계) 레퍼런스 제작자 공개: 영상 이수 = **대시보드의 `전체시간 - 학습시간` → `÷배속` = 실제 대기시간 만큼 재생 → 학습종료 후 재확인**. 서버가 실제 재생시간을 요구해 지름길 없음(전과목은 장시간 → 야간 예약). 우리는 여기에 verify+top-up 추가.
- (Phase 1) ⚠️ **jvmsso 단일 세션**: KNOU는 동시 1세션만 허용 → 다른 곳 로그인 시 즉시 킥. `ensure_logged_in(force_fresh=True)`로 매 실행 쿠키 초기화 후 신선 로그인이 가장 안정적. 자격증명은 `.env`→`config.load_config()`, **로그·하드코딩 금지 유지**.
- (Phase 2) 진도 판정: `prog_rt`(진행률)는 **재생 없이도 0↔50 출렁여 신뢰 불가** → 오직 `video_done`(stdyCmyn=="Y"), `exam_done`((valuCmyn=="Y") or (examRespYn=="Y"))만 사용. 차시당 실제 영상클립 1~3개(빈 ViewPlayer 슬롯은 `<video>` 유무로 필터).
- (Phase 3 실측 ✅) **영상 적립 = 재생 위치(vidoLocSec) 기반, 실시간(wall-clock) 아님**. 2배속도 100% 적립(15강: 실제 55분에 watched +102분). 300초마다 heartbeat POST `registerUSTStudyRslt.ajax`(state=play, vidoSpd=2) + pause/stop 시 저장. **0초 재시작 치명적**(vidoLocSec 리셋) → 절대 wp_elearning_play 클릭 금지.
- (Phase 3 실측 ✅) **이어보기 모달 2종(id 기반, 의미 반대)**: ①"이어서 시청" → 예=wp_elearning_seek(이어보기/정답), 아니오=wp_elearning_play(0재시작). ②"처음부터 다시"(이미 완료) → 예=wp_elearning_play(재시작, 클릭금지), 아니오=wp_elearning_stop(취소/정답). **id로 구분, wp_elearning_play는 절대 클릭 안 함.**
- (Phase 3 실측 ✅) **짧은 클립 종료 감지**: 짧은 클립은 끝나면 `<video>`가 언로드(pos=0/dur=None)되어 `ended` 이벤트를 못 봄 → `_play_until_end`에 max_pos>1.0 재생 후 2연속 polls 동안 video "gone"이면 종료로 판정(seen_dur/gone_count).
- (Phase 3 실측 ✅) **연습문제는 영상 완료와 독립**(자동 완료 안 됨). 박스 `.exam-content-box`는 플레이어 팝업 **메인 프레임**(retrieveUSTStudy.do, ViewPlayer 아님)에 위치. 1세트(tespNo)에 N문항(15강=8). 각 문항 `<form id="frm_{tespNo}_{exqsId}">` + 라디오 4개(.answerCh) + .confirmAnswer 버튼.
- (Phase 3 실측 ✅) **정오답 무관 2-클릭**: exqsTc=='2' && exqsDc in('3','4') && resultCnt==0(첫클릭)=정답 사전검사만(retrieveUSTStudyExamRslt) → 오답이면 alert "다시 한번 생각해 보세요" + 미등록(resultCnt→1). 두 번째 클릭(resultCnt==1)=정오답 무관 등록(`registerUSTStudyExamRslt.ajax`). **≤2클릭/문항이면 무조건 등록.** (주의: `registerUSTStudyPldcRply.ajax`는 Q&A 답글이지 답안 아님). 15강 exam_done False→True 검증.
- (Phase 4 실측 ✅) **MP3는 정찰 불필요** — lectlist의 `strVidoAudoUrl`(절대 URL, sdn.knou.ac.kr CDN)을 `Lecture.audio_url`에 파싱해 바로 GET. 1강 39.9MB(`ID3`).
- (Phase 4 실측 ✅) **PDF(강의록)는 별도 강의자료실 게시판**. lectlist엔 없음. `fnCourseDataPage(atlc,sbjt,cnts)`→`initUCRLectureData.do` 진입 → 목록 AJAX `initUCRLectureData.ajax`(응답 `data.list[]`에 첨부 메타 `apndFileNm`/`apndFileSaveNm` 직접 포함) → **분류 '강의자료' + apndFileNm 'NN-'(2자리) 접두사**로 차시 매칭 → `GET /user_uploading?pathkey=COURSE.DATA&addSavePath={sbjtId}&getfile={저장명}&realFileName={표시명}`. 1강 2.2MB(`%PDF-1.5`). cntsId=sbjtId 끝3자리 제거(KNOU1545001→KNOU1545).
- (Phase 4) 다운로드는 persistent context의 `ctx.request.get`(쿠키 공유)로 받아 바이트 저장(브라우저 다운로드 다이얼로그 회피). HTML 에러응답(작은 크기+`<html`)은 실패로 처리. `needs_download`(없음/0바이트)로 멱등 skip.
- (Phase 6.5 실측 ✅) **비전 검증 프레임 선택(옵션 2)** — 타임스탬프는 *말하는 시점*이라 *슬라이드가 화면에 뜬 시점*과 어긋남(±한두 슬라이드). 해결: 개념마다 후보 N프레임(`VISION_OFFSETS=(-40,-20,0,20,40,60)`, 6장)을 ffmpeg로 `_captures/_cand/`에 임시 캡처 → 인라인 바이트로 Gemini 비전에 전송 → `build_vision_prompt`(개념 라벨+0-based 후보) → JSON `{index,reason}` 구조화 출력 → `parse_vision_choice`(−1/범위초과/깨짐=None) → 고른 1장만 `_captures/`로 이동·나머지 삭제. **−1/호출실패 시 t정각 fallback**. `embed_captures`는 타임스탬프 줄 아래 기존 임베드를 **교체**(중복 삽입 방지)하도록 보강. 비용 ≈ 강당 $0.013~0.02(~18~27원). API 키 미출력 유지.
- (Phase 6.5 튜닝 ✅) **후보 창 4장(−20~+30) → 6장(−40~+60)**: 이산수학 1강 fallback **6→4 감소**(비전 pick 6→8), 멀리 간 Δ±40 픽도 시각 확인 결과 올바른 슬라이드(회귀 없음). **orphan 청소**: `orphan_captures()`로 노트가 더는 참조 않는 `{과목}_{seq}강_*` 캡처만 골라 삭제(다른 차시/과목 파일은 접두사로 보호) — 재실행 시 11개 정리. `capture_lecture_verified(..., prune=True)`.
- (Phase 7 실측 ✅) **전과목 조율 `main.py`** — 모드별 단계맵 `MODES={이수:[watch], 요약:[download,summarize,capture], 전체:[watch,download,summarize,capture]}`. 순수 로직(단위테스트 22개): `stages_for_mode`(복사본 반환)/`lecture_key`(`{과목}|{seq}`)/`stage_done`·`lecture_done`/`mark_stage`/`select_lectures`(course 부분일치+seq)/`pending_lectures`. 오케스트레이션: 브라우저 1회 기동+`ensure_logged_in`(force_fresh) → `list_courses`×`fetch_lectures`로 (과목,lec) 쌍 수집 → 필터·pending → **강의×단계 try/except 격리**(단계 예외/실패 시 그 강의만 break, state에 ok=False+error 기록 후 다음 강의 계속). 단계마다 `save_state`(원자적 tmp→replace)로 중단 후 이어서. `_needs_gemini`로 summarize/capture 있을 때만 `genai.Client` 생성(이수 모드 0비용·0키노출). 로깅 `logs/run_{ts}.log` 콘솔+파일.
- (Phase 7 실측 ✅) **단일강의 스모크**(`--mode 요약 --course 이산수학 --seq 1`): download(MP3·PDF 이미 존재→skip)→summarize(노트 존재→`needs_summary`=False skip)→capture(클립 MP3 0.0s 매칭 후 12개 임베드 전부 skip, **비전 호출 0**) 완주. `state.json`에 download/summarize/capture ok=true+at 기록. **재실행 시 `pending_lectures`가 강의 단위로 걸러 처리 0/사전skip 1**(idempotency 확인). `cfg.summary_dir`는 `vault_path`+`summary_subdir` 합성 property.
- (Phase 6.5 버그픽스 ✅) **긴 강의 캡처: 타임스탬프 형식 + MP3↔다중클립 정렬** — 1강은 MP3=단일클립(2490s)이라 우연히 맞았지만, 13강은 MP3(7209s)=**여러 클립 오디오 연결**이고 Gemini가 1시간 미만 시점을 `MM:SS:00`으로 오기재(`09:21:00`→`timestamp_to_seconds`가 9h21m=33660s로 파싱). 결과 18개 중 12개 캡처 실패 + 6개는 단일클립 절대초 seek라 일괄 **536s 어긋남**. 수정: 순수함수 3개 — `normalize_ts_seconds(sec,dur)`(raw가 길이를 60s+ 초과+시프트결과가 길이 이내면 `h→분,m→초` 필드시프트로 교정, 그 외 보존)·`clip_timeline(clips)`(재생순 누적 `(start,end,clip)`, 길이無/0 클립 제외)·`locate_clip(clips,sec)`(MP3 절대초→`(clip, 클립내 오프셋)`). `capture_lecture_verified`를 단일 `pick_clip_by_duration` 대신 **타임스탬프마다 교정→클립매핑→클립내 오프셋 seek**로 리팩터링. 파일명·embed 키는 노트 마커 초(`note_sec`) 유지(embed/skip/orphan 일관성). 라이브 13강 재검증: **18/18 캡처(비전 pick 16·fallback 2·실패 0), 임베드 18/18, 옛 어긋난 캡처 6개 orphan 정리**. 단위테스트 +14(`tests/test_capture.py`, 총 127 통과). 재검증 하네스 `capture_verify_one.py`는 `--course/--seq/--name` 인자화.
- (Phase 5/6.5 후속 ✅) **타임스탬프 형식 정규화(노트 표시까지)** — 캡처 *이미지*는 위 픽스로 해결됐지만 노트 본문/`timestamps.json`엔 여전히 `🎬 [09:21:00]`(9분21초인데 9h21m로 표시)가 남음. (a) **앞으로**: `normalize_ts_seconds`를 `summarize.py`로 이전(캡처는 재import), 신규 `normalize_markdown_timestamps(md, duration)`로 마커 `[09:21:00]→[00:09:21]` 치환, `save_summary(..., duration=)`가 저장 전 md 교정→이후 `extract_timestamps`가 올바른 초로 사이드카 기록, `main._stage_summarize`는 MP3 길이 probe 후 전달. (b) **기존 13강**: `_plan_renormalize`(순수: 새 md+리네임목록)+`renormalize_note`(오프라인 IO)로 **재캡처 없이** 마커·임베드·캡처파일명(`…09-21-00.jpg`→`…00-09-21.jpg` 12개)·json을 일괄 정정 — 18쌍 마커↔임베드↔파일 정합 0불일치, json 1시간초과 0. 단위테스트 +13(`test_summarize.py`/`test_capture.py`, 총 140 통과).
