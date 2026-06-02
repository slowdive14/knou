# PLAN: KNOU 형성평가 자동화 및 강의 노트 정리 — 비개발자용 Windows 데스크톱 앱 (Flet GUI)

> **CRITICAL INSTRUCTIONS**: 각 Phase 완료 후:
> 1. ✅ 완료한 작업 체크박스 체크
> 2. 🧪 Quality Gate 검증 항목 모두 실행
> 3. ⚠️ Quality Gate 전부 통과 확인
> 4. 📅 "Last Updated" 날짜 갱신
> 5. 📝 Notes 섹션에 배운 점 기록
> 6. ➡️ 그 다음에만 다음 Phase로 진행
>
> ⛔ Quality Gate를 건너뛰거나 실패한 상태로 진행하지 말 것

- **Last Updated**: 2026-06-02
- **Status**: ✅ Phase 1·2·3 완료 · 🔄 Phase 4(자동 예약)·Phase 5(배포) 구현완료 — Phase4: **창 없이 실행(VBS) + 실행 탭 로그 보기 + 예약 on/off + 실행 중 절전 억제(keep_awake) + 이름 변경(`KNOU_`)** / Phase5: **권장 배포경로(run_app.bat + 바탕화면 바로가기 + README_GUI.md + frozen 보정 토대)** 적용(테스트 **278 통과**, 절전억제·바로가기 .lnk 생성 라이브 확인) — 사용자 1회 실사용 검증 대기
- **App 이름**: `KNOU 형성평가 자동화 및 강의 노트 정리`(창 제목) · 작업 스케줄러 예약 접두사 `KNOU_`(영문, 안정적) · 패키징 exe 는 `KNOU.exe`(Phase 5)
- **Scope**: Large (5 phases, 약 10~17시간)
- **Stack**: Python 3.14 / **Flet**(데스크톱 GUI) / 기존 백엔드(Playwright·Gemini·ffmpeg) **그대로 구동** / Windows 작업 스케줄러 / PyInstaller(.exe)

---

## 1. Overview & Objectives

기존에 완성된 KNOU LMS 자동화 CLI(`main.py`)를 **비개발자도 더블클릭으로 쓸 수 있는 Windows 앱**으로 감싼다. 코딩·터미널·`.env` 편집 없이, 화면에서 버튼으로:

### 목표
- [x] **예습 노트 생성**: 과목·차시를 골라 버튼 한 번으로 예습 노트 생성(`--mode 요약`), 실시간 진행 표시 + 완료 시 노트 열기 *(구현 완료·수동 검증 대기)*
- [x] **영상 이수 / 형성평가**: 미이수 강의 자동 이수(`--mode 이수`) — **되돌릴 수 없는 형성평가 자동 제출**이므로 필수 확인 + 취소 가능 *(구현 완료·수동 검증 대기)*
- [x] **설정 화면**: 아이디/비밀번호/Gemini 키/볼트 경로를 화면에서 안전 입력(마스킹, 로그 미출력) — `.env` 직접 편집 불필요
- [ ] **자동 예약**: 모드·필터·시각을 골라 Windows 작업 스케줄러에 등록(앱·터미널 꺼져 있어도 새벽 자동 실행) *(Phase 4 진행 중)*
- [x] **배포**: `run_app.bat` 더블클릭 + **바탕화면 바로가기(콘솔 없이 pythonw 실행)** + 첫 실행 설정 마법사 + `README_GUI.md` *(권장 경로 채택 — 단일 .exe 는 Playwright 번들 취약성으로 보류, frozen 보정 토대만 선반영)*

### 핵심 설계 원칙
1. **백엔드 재작성 0** — GUI는 기존 `main.py`를 **하위 프로세스(subprocess)로 구동**하고 stdout 로그를 실시간 표시한다.
2. **프로세스 격리** — Playwright sync API가 GUI 이벤트 루프와 충돌하지 않게, 또 작업이 죽어도 앱이 살아 있게 별도 프로세스로 실행/취소한다.
3. **비밀유지 불변식** — 비밀번호·`GEMINI_API_KEY`는 화면 마스킹, 로그·콘솔 평문 출력 금지, `.env`에만 저장(기존 보안 원칙 계승).
4. **순수 로직만 단위테스트** — env 읽기/쓰기·명령 빌더·로그 파서·스케줄 인자 빌더 등은 TDD. Flet UI·실제 LMS·작업 스케줄러는 수동 검증 게이트(기존 프로젝트 철학과 동일).

### 사용자 컨텍스트
- 코딩 경험: **기초** → 화면은 단순하게, 위험한 동작엔 확인 다이얼로그.
- 형성평가 자동 제출은 **본인 계정·예습 목적**의 되돌릴 수 없는 행위 → 명시적 동의 후에만 실행.

---

## 2. Architecture Decisions

| 결정 | 내용 | 이유 |
|------|------|------|
| **Flet** GUI | Flutter 렌더 데스크톱 앱 | 순수 Python 한 언어, 기본 디자인이 모던(비개발자 친화), 진짜 데스크톱 창, `.exe` 패키징 |
| **subprocess 구동** | GUI가 `python -u main.py …`를 Popen으로 실행, stdout 라인 스트리밍 | Playwright sync ↔ GUI 루프 충돌 회피, 중간 취소, 크래시 격리 |
| **워커 스레드 + 콜백** | 자식 stdout을 워커 스레드에서 읽어 `page` 갱신 | UI 멈춤 없이 실시간 로그 |
| **기존 `.env` 사용** | 설정 화면이 `.env` 읽기/쓰기, `config.load_config`로 검증 | 단일 진실원, 백엔드와 동일 설정 |
| **강의 목록 스냅샷** | 가벼운 목록수집 진입점이 `lectures.json` 캐시 → 표시, "새로고침" 버튼 | 매번 로그인·수집 비용 회피, 빠른 UI |
| **Windows 작업 스케줄러** | `schtasks.exe` + 생성된 `run.bat` 진입점 | 앱 꺼져 있어도 동작(가장 안정적) |
| **PyInstaller(`flet pack`)** | 단일 `.exe` 산출 | 비개발자 더블클릭 배포. 무거운 `flet build windows`(Flutter SDK 필요)는 선택 |
| **브라우저 비동봉** | 기존 `channel="chrome"` 유지 | 설치된 Chrome 사용 → exe에 브라우저 안 넣어도 됨 |
| TDD 현실 적용 | 순수 로직만 단위테스트, GUI/LMS/스케줄러는 수동 게이트 | 기존 프로젝트와 동일 |

### 프로젝트 구조 (추가분)
```
knou/
├─ app/                       # ★ 신규: Flet GUI
│  ├─ __init__.py
│  ├─ main_app.py             # Flet 진입점: page, NavigationRail, 뷰 라우팅
│  ├─ views/
│  │  ├─ home_view.py         # 요약 상태/빠른 실행
│  │  ├─ run_view.py          # 강의 선택 + 예습 노트 생성 / 영상 이수
│  │  ├─ schedule_view.py     # 예약 추가/목록/삭제
│  │  └─ settings_view.py     # .env 입력(마스킹) + 검증
│  └─ widgets.py              # 공통 컴포넌트(로그패널, 상태배지, 진행바)
├─ gui_core.py                # ★ 순수: env 읽기/쓰기/검증, 마스킹, 첫실행 판정, 모델
├─ runner.py                  # ★ 순수+IO: build_command, parse_progress_line, JobRunner(subprocess)
├─ schedule_win.py            # ★ 순수+IO: schtasks 인자 빌더/파서, run.bat 생성, create/list/delete
├─ list_lectures.py           # ★ 신규(경량): 과목·차시 목록만 수집해 lectures.json 출력
├─ run_app.bat                # ★ 소스 실행용 더블클릭(ASCII)
├─ README_GUI.md              # ★ 비개발자 설치/사용 가이드
└─ tests/
   ├─ test_gui_core.py        # ★
   ├─ test_runner.py          # ★
   └─ test_schedule_win.py    # ★
```
> 기존 `auth/discover/watch/exercise/download/summarize/deck_match/capture/main/config.py`는 **수정 없이 재사용**. 필요한 경우 `main.py`에 가벼운 부가 진입점만 추가(예: 목록 수집), 기존 동작은 보존.

---

## 3. Phases

### Phase 1 — 앱 골격 + 설정 화면 (2-3h)
**Goal**: Flet 앱이 데스크톱 창으로 뜨고 좌측 네비(홈·실행·예약·설정) 전환. 설정 화면에서 `.env`를 안전하게 읽고/쓰고 검증(비번·키 마스킹).

**Test Strategy**: `gui_core.py` 순수 로직 단위테스트. UI는 수동 스모크.
- **Test File**: `tests/test_gui_core.py`
- **Test 시나리오**:
  - `read_env_file(path)` → dict, 파일 없으면 `{}`
  - `write_env_file(path, updates)` → 기존 **미지 키·주석 보존**, 지정 값만 갱신
  - `mask_secret(v)` → `"abcd…(가림)"` (앞 몇 글자만, 빈값은 빈 표시)
  - `validate_settings(d)` → 누락 필수키 리스트(`config.REQUIRED` 재사용: KNOU_ID/KNOU_PW/GEMINI_API_KEY/VAULT_PATH)
  - `first_run_needed(path)` → 필수키 누락이면 True
- **Expected Failures**: 함수 미구현 → ImportError/AttributeError
- **Coverage Target**: `gui_core` ≥ 90%
- **Mock/Fixture**: 파일 IO는 `tmp_path`. 비밀값은 더미 문자열.

**Tasks**:
1. **(RED)** `tests/test_gui_core.py` 작성 → 실패 확인 ✅ (`ModuleNotFoundError: gui_core` 확인 후 구현)
2. **(GREEN)** `gui_core.py` 구현(env 왕복/마스킹/검증/첫실행) ✅ 19 테스트 통과
3. **(GREEN)** `app/main_app.py`: Flet `page`, `NavigationRail`(4뷰), 창 제목·아이콘·최소크기 ✅
4. **(GREEN)** `app/views/settings_view.py`: 필드(KNOU_ID, KNOU_PW=password, GEMINI_API_KEY=password, VAULT_PATH, SUMMARY_SUBDIR, PLAYBACK_SPEED) + 저장 버튼 + 검증 결과 배너 ✅
5. **(REFACTOR)** 비번/키 표시 토글(눈 아이콘 `can_reveal_password`), 저장 결과 인라인 배너(색상), 빈 필수값 경고 ✅

**Quality Gate**:
- [x] `pytest tests/test_gui_core.py` 통과 (전체 스위트 166 통과, 신규 26: gui_core 19 + app_views 7)
- [x] 앱이 창으로 뜨고 4개 탭 전환됨(**수동 — 사용자 "전부 오케이" 확인 2026-06-01**)
- [x] 설정 저장 → 앱 재시작 시 값 유지(`.env` 왕복), 미지 키 보존 (write_env_file 왕복 테스트로 검증)
- [x] **비밀번호·API 키가 로그·콘솔에 평문 미출력**(화면은 마스킹; password+can_reveal_password)
- [x] 빈 필수값 저장 시 명확한 경고 배너 (apply_settings가 누락 키 반환 → 배너 RED)

**Dependencies**: 기존 `config.py`
**Rollback**: `app/`, `gui_core.py` 삭제

---

### Phase 2 — 강의 선택 + 예습 노트 생성 (3-4h)
**Goal**: 과목·차시 목록에서 선택 → "예습 노트 생성" → 실시간 진행 로그 패널 → 완료 시 "노트 열기".

**Test Strategy**: `runner.py` 순수 로직 단위테스트. 실제 생성은 한 강의 수동 검증.
- **Test File**: `tests/test_runner.py`
- **Test 시나리오**:
  - `build_command(py, mode, course, seq, limit, stages)` → 올바른 argv(한글 인자 포함, **비번·키 미포함**)
  - `parse_progress_line(line)` → 단계/상태 인식:
    - `"  ✓ summarize: 완료"` → `{stage:"summarize", status:"done"}`
    - `"  ✗ … 실패: …"` → `{status:"error"}`
    - `"── 데이터베이스시스템 13강 '트랜잭션'"` → `{event:"lecture", course, seq, name}`
    - `"매칭 21 + 전방채움 0 = 21/21개"` → `{event:"match", matched:21, total:21}`
    - `"=== 요약 === {…}"` → `{event:"summary"}`
  - `pct_for_stage(stage)` → 진행률 추정(download 25 / summarize 60 / capture 90 / done 100)
  - `parse_lectures_snapshot(json)` → `[LectureRow(course, seq, name, video_done, exam_done)]`
  - `note_path_for(cfg, course, seq, name)` → 결과 노트 경로(`summarize.note_filename` 재사용)
- **Expected Failures**: 미구현
- **Coverage Target**: `runner` 순수부 ≥ 85%
- **Mock/Fixture**: subprocess는 가짜 라인 리스트로 파서만 검증(실프로세스 미사용).

**Tasks**:
1. **(RED)** `tests/test_runner.py`(명령 빌더·로그 파서·스냅샷 파서) → 실패 확인 ✅ (`ModuleNotFoundError: runner` 후 구현)
2. **(GREEN)** `runner.JobRunner`: `subprocess.Popen([py,"-u","main.py",…], stdout=PIPE, encoding="utf-8")` 워커 스레드에서 라인별 `on_line` 콜백, 종료코드 콜백, `cancel()`=terminate ✅
3. **(GREEN)** `list_lectures.py`(경량 목록수집) + "목록 새로고침" 버튼 → `lectures.json` 캐시 → 목록 표시 ✅
4. **(GREEN)** `app/views/run_view.py`: 과목 드롭다운 + 차시 드롭다운 + "예습 노트 생성" + 로그패널(`ListView auto_scroll`) + 진행바 + "노트 열기"(`os.startfile`) ✅
5. **(REFACTOR)** 실행 중 버튼/드롭다운 비활성화(`_set_running`), 완료/실패/취소 상태 배지(색상), 빈 선택 가드 ✅

**Quality Gate**:
- [x] `pytest tests/test_runner.py` 통과 (runner 23 + run_view 헬퍼/스모크 7 = 신규 30, 전체 196 통과)
- [x] **GUI에서 한 강의 예습 노트가 끝까지 생성됨**(**수동 OK 2026-06-01**: DB 15강 견고화 수정 후 재실행 성공)
- [x] 진행 로그가 실시간 표시되고 완료 시 "노트 열기" 동작(**수동 OK**: 스크린샷 + 재실행 확인)
- [x] 비번·키가 GUI·로그에 미출력 (argv는 모드/필터만, 비밀값은 자식이 `.env`서 직접 읽음; `test_build_command_never_contains_secrets`)
- [x] 실패(예: 빈 선택)해도 앱이 죽지 않고 에러 표시 (빈 선택 가드 + subprocess 실패 시 `on_exit` 종료코드 배지; 실 LMS 실패는 수동 확인)

**Dependencies**: Phase 1, 기존 `main.py`/`summarize.py`/`discover.py`
**Rollback**: `runner.py`, `list_lectures.py`, `run_view.py` 삭제

---

### Phase 3 — 형성평가 / 영상 이수 실행 + 안전장치 (1-3h)
**Goal**: 같은 실행 화면에서 "영상 이수 / 형성평가" 모드(`--mode 이수`) 실행. **되돌릴 수 없는 자동 제출**이므로 필수 확인 + 예상 소요시간 + 취소.

**Test Strategy**: 순수 로직 단위테스트(runner 확장).
- **Test File**: `tests/test_runner.py`(추가)
- **Test 시나리오**:
  - `requires_confirm(mode)` → "이수"/"전체"면 True(형성평가 자동제출 포함)
  - `estimate_watch_text(total_min, watched_min, speed)` → `"약 29분 예상"`(기존 `watch.wall_clock_seconds` 재사용)
  - `confirm_message(mode)` → "형성평가 답안이 실제 제출되어 되돌릴 수 없음" 경고 포함
  - 취소 후 상태 전이(`running`→`cancelled`)
- **Expected Failures**: 미구현
- **Coverage Target**: 추가 순수부 ≥ 85%

**Tasks**:
1. **(RED)** 확인·예상시간·취소 로직 테스트 → 실패 확인 ✅ (`ImportError: confirm_message` 등 확인 후 구현)
2. **(GREEN)** `run_view`에 모드 선택(예습 노트 / 영상 이수). 이수 실행 시 `AlertDialog`(체크박스 "형성평가 답안이 실제로 제출됨을 이해합니다" + 예상시간) → 동의해야 시작 ✅
3. **(GREEN)** 취소 버튼 → `runner.cancel()`(프로세스 종료) → 상태 배지 안내 ✅ (Phase 2 `on_cancel` 재사용)
4. **(REFACTOR)** 장시간 작업 경과시간/현재 활동 표시(`format_elapsed` 티커), 절전 주의 안내(`watch_sleep_warning`) ✅

**Quality Gate**:
- [x] `pytest` 통과 (전체 222 통과; runner 확인/예상시간/경과/watch파싱 + run_view 확인다이얼로그/모드라벨/절전)
- [x] **이수 실행은 필수 확인 후에만 시작**(미동의 시 실행 안 됨) — `build_confirm_dialog` 동의 전 `start_btn.disabled` + 핸들러 로직 차단(`test_confirm_dialog_start_disabled_until_agree`)
- [x] 취소가 즉시 자식 프로세스를 멈춤(좀비 없음) — `JobRunner.cancel`=terminate, `test_jobrunner_cancel_stops_process`
- [x] 형성평가 되돌릴 수 없음 경고가 명확히 표시 — `confirm_message`("되돌릴 수 없")  + 다이얼로그 본문 + 절전 경고
- [x] **실제 강의 1개 이수가 GUI에서 동작(수동, 짧은 미이수 강의로)** — ✅ 통계학개론 14강 이수 성공, UX 4건 수정 후 재검증 OK(사용자 "잘 됐어" 2026-06-02)

**Dependencies**: Phase 2, 기존 `watch.py`/`exercise.py`
**Rollback**: 이수 관련 UI/로직만 되돌림(Phase 2 예습 경로는 유지)

---

### Phase 4 — 자동 예약 (Windows 작업 스케줄러) (2-4h)
**Goal**: 예약 화면에서 모드+필터(과목/차시)+시각을 골라 작업 스케줄러에 등록 / 목록 / 삭제. 앱·터미널 꺼져 있어도 실행.

**Test Strategy**: `schedule_win.py` 순수 로직 단위테스트. 실제 `schtasks` 등록은 수동 검증.
- **Test File**: `tests/test_schedule_win.py`
- **Test 시나리오**:
  - `build_run_script(py, project_dir, mode, course, seq)` → `run_*.bat` 내용(venv python + `main.py` 인자, **ASCII 안전**)
  - `build_schtasks_create_args(name, time_hhmm, script_path, freq)` → `schtasks /Create …` argv(접두사 `KNOU_`)
  - `build_schtasks_delete_args(name)` → `/Delete /F` argv
  - `parse_schtasks_list(csv_output)` → `[{name, next_run, status}]` (우리 접두사만 필터)
  - `valid_time("02:00")` / 잘못된 시각 거부
- **Expected Failures**: 미구현
- **Coverage Target**: `schedule_win` 순수부 ≥ 85%
- **Mock/Fixture**: `schtasks` 출력은 샘플 CSV 문자열로 파서 검증(실호출 미사용).

**Tasks**:
1. **(RED)** `tests/test_schedule_win.py`(스크립트·인자 빌더·CSV 파서·시각검증) → 실패 확인 ✅ (`ModuleNotFoundError: schedule_win` 확인 후 구현)
2. **(GREEN)** `schedule_win.create_task/list_tasks/delete_task`: `subprocess` `schtasks.exe`(`/FO CSV /NH`), `run_*.bat` 파일 생성 후 그 경로 등록 ✅ 18 테스트 통과
3. **(GREEN)** `app/views/schedule_view.py`: 모드 드롭다운 + (선택)과목/차시 + 시각 입력 + 반복(매일/한번) + "예약 추가" + 기존 예약 표(삭제 버튼) ✅ main_app 예약 탭 배선
4. **(REFACTOR)** 중복 이름 방지(결정적 작업명 + `/F` 덮어쓰기), 최고권한/실행계정 안내, 다음 실행시각 표시 ✅

**Quality Gate**:
- [x] `pytest tests/test_schedule_win.py` 통과 (schedule_win 18 + schedule_view 스모크 3, 전체 244 통과)
- [ ] **GUI에서 만든 예약이 Windows 작업 스케줄러에 보이고**(수동 확인) 지정 시각에 실행되어 `logs/`에 기록 — ⏳ 사용자 검증 대기
- [ ] 예약 목록/삭제가 GUI에서 동작 — ⏳ 사용자 검증 대기 (조회·파싱 경로는 실제 `schtasks /Query` 로 read-only 확인 OK)
- [ ] 예약 실행 시 세션 만료여도 자동 재로그인(기존 `force_fresh`) — ⏳ 지정 시각 실행 시 확인
- [ ] `run_*.bat`가 ASCII로 안전하게 생성(cmd 한글 깨짐 없음) — 파일명 ASCII 자동 보장 + `chcp 65001`(UTF-8)로 한글 인자 보존, 수동 1회 확인 권장

**Dependencies**: Phase 1~3(실행 명령 재사용)
**Rollback**: 작업 스케줄러 항목 삭제, `schedule_win.py`/`schedule_view.py` 삭제

---

### Phase 5 — 패키징 & 비개발자 배포 (2-3h)
**Goal**: `KNOU.exe` 더블클릭 실행 + 첫 실행 설정 마법사 + 바탕화면 바로가기 + README.

**Test Strategy**: 코드 적음 → 수동 검증 위주 + 첫실행/리소스경로 단위테스트.
- **Test File**: `tests/test_gui_core.py`(추가)
- **Test 시나리오**:
  - `first_run_needed(path)` → `.env` 없거나 필수키 누락 시 True → 앱이 설정 탭 자동 오픈
  - `resource_path(rel)` → PyInstaller `_MEIPASS` 대응(번들 리소스 경로 정확)
- **Expected Failures**: 미구현
- **Coverage Target**: 추가분 100%(작은 함수)

**Tasks**:
1. **(RED)** `first_run_needed`·`resource_path` 테스트 → 실패 확인
2. **(GREEN)** 첫 실행 시 설정 비면 마법사 화면 유도
3. **(GREEN)** `flet pack app/main_app.py` → `dist/KNOU.exe`(아이콘). PyInstaller hidden-imports(playwright, google.genai, dotenv 등) 보강
4. **(GREEN)** `run_app.bat`(소스 실행) + `README_GUI.md`(설치/사용/주의 — 비개발자용)
5. **(REFACTOR)** 창 아이콘/제목/최소크기, 실행 중 종료 시 경고

**Quality Gate** (권장경로 — bat+바로가기 기준):
- [x] `run_app.bat` 더블클릭 시 앱 실행(소스+venv) — 기존 검증
- [ ] 설정 탭 [바탕화면 바로가기 만들기] → 바탕화면 `.lnk` 더블클릭 시 **콘솔 없이** 앱 실행(수동)
- [ ] 첫 실행 설정 마법사로 `.env` 생성 → 예습 노트 생성까지 동작(end-to-end)
- [x] `README_GUI.md`만 보고 비개발자가 설치·실행 가능(문서 작성 완료)
- [ ] (확인) 기존 CLI(`python main.py …`)도 그대로 동작(회귀 없음)

**Dependencies**: Phase 1~4
**Rollback**: `deploy.py`·`README_GUI.md`·바로가기 제거(코드 토대 `is_frozen`/`resource_path` 는 무해하게 유지)

---

## 4. Risk Assessment

| 리스크 | 확률 | 영향 | 완화 |
|--------|------|------|------|
| Playwright sync ↔ GUI 루프 충돌 | Med | High | **subprocess 격리**로 원천 차단(GUI는 구동/취소만) |
| PyInstaller가 playwright/genai 동적 import 누락 | Med | Med | hidden-imports/collect-all, **클린 환경 exe 스모크**(Phase 5 게이트) |
| Flet 버전 API 변동·빌드 복잡 | Med | Med | `requirements.txt`에 버전 핀, `flet pack`(PyInstaller) 우선, 무거운 `flet build`는 선택 |
| 작업 스케줄러 권한/한글 인코딩 | Med | Med | `schtasks /fo CSV /nh` 파싱, **ASCII run.bat**, 최고권한 옵션 안내 |
| 형성평가 오용(되돌릴 수 없는 제출) | Low | High | **필수 확인 다이얼로그** + 명시 경고 + 취소 |
| 비밀번호·API 키 노출 | Low | High | 화면 마스킹, 로그 금지, `.env`만 저장, `.gitignore` 확인 |
| 장시간 이수 중 PC 절전/탭 throttle | Med | Med | 작업 스케줄러 권장 + 절전 끄기 안내(기존 watch 로직 재사용) |
| 강의 목록 수집 비용(로그인 반복) | Med | Low | `lectures.json` 캐시 + "새로고침"으로만 갱신 |

> ⚠️ **참고**: 본 도구는 본인 계정·예습 목적의 개인 학습 자동화. 학교 LMS 이용약관/학칙 준수 여부는 사용자 책임 영역.

---

## 5. Progress Tracking

| Phase | 상태 | 완료일 |
|-------|------|--------|
| 1. 앱 골격 + 설정 화면 | ✅ 완료 | 2026-06-01 |
| 2. 강의 선택 + 예습 노트 생성 | ✅ 완료 | 2026-06-01 |
| 3. 형성평가/영상 이수 + 안전장치 | ✅ 완료 | 2026-06-02 |
| 4. 자동 예약(작업 스케줄러) | 🔄 구현완료·수동검증 대기 | - |
| 5. 패키징 & 배포 | 🔄 권장경로(bat+바로가기+README) 구현완료·수동검증 대기 | 2026-06-02 |

상태 범례: ⬜ 대기 / 🔄 진행중 / ✅ 완료 / ⚠️ 막힘

---

## 6. Notes & Learnings

> 각 Phase 진행하며 배운 점, 막힌 점, Flet/스케줄러 특이사항을 여기에 기록.

- (설계) 기존 백엔드는 `main.run(mode, course, seq, …)` 단일 진입점 + `--mode/--course/--seq/--limit/--stages` CLI로 이미 GUI 친화적 → **GUI는 얇은 구동 껍데기**로 충분(재작성 0).
- (설계) `config.REQUIRED = [KNOU_ID, KNOU_PW, GEMINI_API_KEY, VAULT_PATH]`, 비번/키는 `config._dunder` 없이 `.env`만 사용. 설정 화면은 이 목록을 그대로 검증에 재사용.
- (설계) 진행 로그는 `main.py`가 이미 `logs/run_*.log` + 콘솔에 단계별(`✓ download/summarize/capture`, `=== 요약 ===`)로 찍으므로 **stdout 라인 파싱**만으로 진행바·상태를 구성 가능.
- (보안) Windows PowerShell 환경 — git/명령 체이닝(`&&`,`;`) 금지, `git add` 후 별도 `git commit`. 비번·키 로그 출력 영구 금지.

### Phase 1 (2026-06-01)
- (설치) **Flet 0.85.2** 설치 완료(`requirements.txt`에 `flet>=0.85,<0.86` 핀). 버전 확인은 `importlib.metadata.version('flet')` 사용(`flet.version.version`은 AttributeError).
- (Flet 0.85 API 변동) 구버전 예제와 다름 — 반드시 주의:
  - `ft.Icons.HOME` / `ft.Colors.RED` — **대문자** 네임스페이스(구버전 `ft.icons`/`ft.colors` 소문자 아님).
  - `ft.dropdown.Option(...)` — **소문자** 모듈(클래스 `ft.Dropdown.Option` 아님). Phase 2 드롭다운에서 사용 예정.
  - `page.window`·`page.open`이 `dir(ft.Page)`에 안 보임 → 창 크기 설정은 **try/except로 방어적** 적용. 스낵바/다이얼로그 대신 Phase 1은 **인라인 배너**(`ft.Text` 색상) 사용.
- (테스트 전략) Flet 컨트롤은 디스플레이 없이도 **오프라인 인스턴스화** 가능 → 컨트롤 트리 워크(`.controls`/`.content`)로 구조 검증하는 스모크 테스트 작성(`tests/test_app_views.py` 7개). `_FakePage`(window/add/update/title)로 `main(page)` 셸 구성도 예외 없이 검증.
- (실행) `app/main_app.py`는 `python -m app.main_app`로 구동(=`run_app.bat`). `PROJECT_ROOT`를 `sys.path`에 삽입해 스크립트 직접 실행도 대응.
- (수동 게이트 남음) 실제 창 띄우기·4탭 전환·설정 저장 왕복은 **사용자가 `run_app.bat` 더블클릭으로 검증** 후 Phase 2 진행. → 2026-06-01 "전부 오케이" 확인 완료.

### Phase 2 (2026-06-01)
- (구조) `runner.py` = GUI↔백엔드 다리. 순수부(`build_command`/`parse_progress_line`/`pct_for_stage`/`parse_lectures_snapshot`/`note_path_for`)는 완전 단위테스트(23개), `JobRunner`(Popen+워커스레드)는 짧은 `python -c` 가짜 자식으로 라인수집·종료·취소만 검증.
- (로그 파싱) `main.py` 는 `logging` 포맷 `"%(asctime)s %(levelname)s %(message)s"` 라 stdout 라인이 `12:34:56 INFO …` 로 시작 → 파서가 **로그 프리픽스를 정규식으로 제거**한 뒤 본문 매칭. 최종 `=== 요약 ===` 줄만 프리픽스 없음(직접 `print`).
- (인식 이벤트) 강의 헤더 `── 과목 N강 '제목'`, 단계 `✓ stage: 완료/skip`·`· stage: 이미 완료 skip`·`✗ stage 실패/예외:`, 매칭 `매칭 A + 전방채움 B = P/T개`, 요약 `=== 요약 ===`.
- (Flet 0.85 추가 발견) **`ft.Dropdown` 은 `on_change` 가 없고 `on_select` 사용**(Material3 DropdownMenu 기반). `ft.dropdown.Option(key=, text=)`. `ft.ListView(auto_scroll=True)` 로 로그 자동 스크롤. **`ft.border.all()` 헬퍼는 0.85에서 제거됨** → 테두리 대신 `bgcolor=ft.Colors.with_opacity(...)` + `border_radius` 로 로그 패널 구분.
- (보안) 실행 argv 는 `python -u main.py --mode 요약 --course … --seq … --limit 1` 뿐 — 비번·키 평문이 인자/로그에 흐르지 않음(자식이 `.env`서 직접 읽음). `test_build_command_never_contains_secrets` 로 회귀 방지.
- (실행 파이썬) 소스 실행 시 `sys.executable`(=venv python). 패키징(exe) 시 `sys.executable` 이 exe 자신이라 subprocess 가 깨질 수 있음 → **Phase 5에서 보정 필요**(메모).
- (수동 게이트 남음) 실제 한 강의 예습 노트 끝까지 생성·실시간 로그·"노트 열기"는 **사용자가 `run_app.bat` → 실행 탭에서 검증**.

#### Phase 2 수동검증 1차 — 발견·수정 (2026-06-01)
- (검증) GUI 배관 정상: 로그인→MP3/PDF 다운로드→Gemini 업로드→실시간 로그 스트리밍·진행바 모두 동작 확인(스크린샷).
- (버그 A·GUI) `main.py` 는 강의 1개가 실패해도 **종료코드 0** 으로 끝난다(실패는 `=== 요약 ===` 의 `failed` 와 `✗` 로그로만). 초기 `on_exit` 가 `code==0` → 무조건 초록 "완료" 표시 → **실패인데 성공으로 오표시**. → 수정: `parse_progress_line` 의 summary 이벤트에 `processed`/`failed` 추출 추가, run_view 가 `had_error`·`failed`·`processed` 로 실제 성공/실패 판정(실패 시 빨강 "실패 ❌ … ✗ 줄 확인", '노트 열기'는 실성공+파일존재일 때만).
- (버그 B·백엔드) DB 15강에서 `summarize 실패: 빈 요약 응답`. 원인: `summarize_lecture` 가 `max_output_tokens`·thinking 한도 **미설정** → gemini-2.5-flash 가 긴 입력에서 thinking 으로 출력 예산을 잠식, 본문이 빈 채 반환(추정 finish_reason=MAX_TOKENS). 게다가 그냥 `""` 반환이라 원인 불명. → 수정(사용자 승인): `MAX_OUTPUT_TOKENS=32768` + `THINKING_BUDGET=8192` 명시, 빈 응답 시 `finish_reason`/`block_reason` 로그 후 **thinking 끄고 1회 재시도**, `resp.text` 비면 candidates parts 폴백. 순수 헬퍼(`_strip_code_fence`/`_resp_text`/`_finish_reason`/`_block_reason`) 단위테스트 5개 추가.
- (테스트) 전체 202 통과. **15강 재실행 성공(사용자 "성공" 확인 2026-06-01)** → 견고화 수정 실증, Phase 2 게이트 통과.

### Phase 3 (2026-06-01)
- (구조) 같은 실행 화면에 **모드 라디오**(예습 노트 생성 / 영상 이수) 추가. `on_primary` 가 `requires_confirm(mode)` 로 분기 → 요약은 즉시 `_run_summary`, 이수는 `_open_confirm` → 동의 후 `_run_watch`. argv 는 `--mode 이수 --course … --seq … --limit 1`(비밀값 없음, Phase 2 빌더 재사용).
- (안전장치·핵심) `build_confirm_dialog` 는 **UI disabled 뿐 아니라 핸들러 로직에서도** 미동의 클릭을 차단한다(`_on_start` 가 `start_btn.disabled` 면 `return`). → 실수 클릭·자동화로도 형성평가가 제출되지 않음. 오프라인 테스트로 "동의 전 클릭 → on_confirm 0회, 동의 후 → 1회" 검증.
- (확인 다이얼로그) `confirm_message`(비가역성 경고) + `estimate_watch_text`(남은 분·배속→예상 벽시계) + `watch_sleep_warning`(PC 절전 금지)을 한 다이얼로그에 모음. `page.show_dialog`/`page.pop_dialog`(0.85; `page.open`/`close` 없음).
- (경과시간) 이수는 길게 걸려 로그가 드물다 → **데몬 티커 스레드**가 1초마다 `format_elapsed(monotonic-t_start)` + 현재 활동(강의/단계/매칭)을 `elapsed_text` 에 갱신. `on_exit` 에서 `_stop_ticker`(Event.set)로 종료, 최종 경과 고정. `page.update()` 는 0.85에서 락 보호 → 펌프 스레드와 동시 갱신 허용(저빈도).
- (성공 판정 일원화) `on_exit` 가 인라인 계산 대신 **`job_status(code, had_error, failed, processed)`** 사용(테스트된 단일 규칙). 절전 경고는 요약 모드에선 숨기고 이수 선택 시 노출(`on_mode_change`).
- (수동 게이트 남음·필수) **실제 짧은 미이수 강의로 이수 1건**을 GUI에서 검증해야 Phase 3 완료. 형성평가가 실제 제출되는 **되돌릴 수 없는** 동작이므로, 사용자가 직접 동의·실행·결과 확인할 것. → 검증 전까지 Phase 4 진행 금지.

#### Phase 3 수동검증 1차 — 발견·수정 (2026-06-02)
- (검증) **통계학개론 14강 영상 이수 성공**(사용자 확인). 모드 선택→동의 다이얼로그→이수 자동 실행까지 배관 정상.
- (버그 1·라벨) **Flet 0.85 `FilledButton` 에는 `text` 속성이 없음** — 라벨은 `content`(문자열/컨트롤)에 들어간다. 첫 위치인자도 `content` 로 매핑. `gen_btn.text=…` 는 무시되어 모드 바꿔도 버튼이 "예습 노트 생성" 그대로였음(절전경고는 같은 핸들러라 정상 토글되어 원인 격리 가능). → `gen_btn.content=…` 로 수정 + 회귀 테스트(`test_mode_change_updates_button_label`).
- (버그 2·경과 표시) 기존엔 **벽시계 경과**만 표시 → 2배속 재생인데 1배속처럼 느리게 보여 혼란. watch 로그(`{'pos','dur','rate','paused','ended'}`)를 `parse_progress_line` 에 추가 파싱(`event:"watch"`), run_view 가 **마지막 pos 를 배속만큼 보간**해 `영상 6:00 / 1:22:52 (7%) · 2배속` 로 실제 재생속도와 맞게 표시(진행바도 pos/dur).
- (개선 3·총 길이) 위 표시에 **총 영상 길이**를 함께 노출 → 얼마 남았는지 직관적.
- (개선 4·통합 모드) **`영상 이수 + 예습 노트`(`--mode 전체`)** 라디오 추가 — 이수와 노트 생성을 한 번에. 전체도 `requires_confirm`(되돌릴 수 없는 제출 포함) → 동의 다이얼로그 필수, 완료 시 '노트 열기' 활성.
- (구조) `_run_summary`/`_run_watch` → 단일 `_run(cfg, mode, …)` 로 통합(요약·이수·전체 공용, note 는 요약/전체만). `_open_confirm(mode,…)` 로 일반화(이수/전체 공용 경고문).
- (재검증 필요) 라벨 정상화 + 영상 진행도/총길이 표시 + **전체(통합) 모드**는 새로 추가/변경된 경로 → 사용자가 짧은 미이수 강의로 **이수 / 전체** 각각 한 번 더 확인 권장.

#### Phase 3 마감 — 예습 노트 따옴표 절제 (2026-06-02)
- (재검증 OK) 사용자 "잘 됐어" — 라벨/진행도/전체 모드 모두 정상. **Phase 3 완료**.
- (개선·노트 품질) Gemini 예습 노트가 `시스템 장애`·`트랜잭션` 같은 일반 용어를 습관적으로 작은따옴표로 둘러 가독성이 떨어짐. → `summarize.build_prompt` 에 따옴표 절제 규칙(요구사항 7) 추가: 일반 용어엔 따옴표 금지, 강조는 **굵게**, 작은따옴표는 코드·명령어·글자그대로 인용에만. 기존 `test_build_prompt_mentions_key_requirements` 영향 없음(28 통과).

### Phase 4 (2026-06-02)
- (구조) `schedule_win.py` = GUI↔작업 스케줄러 다리. 순수부(`valid_time`/`normalize_time`/`task_display_name`/`script_filename`/`build_run_script`/`build_schtasks_create_args`·`delete`·`query`/`parse_schtasks_list`)는 완전 단위테스트(18개), IO(`create_task`/`list_tasks`/`delete_task` via `schtasks.exe`)는 수동 게이트. `schedule_view` 는 오프라인 스모크 3개.
- (한글 인자 보존) 예약 `.bat` 은 **파일명만 ASCII**(`run_summary.bat`/`run_watch_<hash8>.bat` — 모드는 ASCII 토큰, 필터는 md5 8자리로 유일성)로 만들고, **내용은 `chcp 65001`(UTF-8) + `PYTHONUTF8=1`** 로 `--mode 요약`·`--course 데이터베이스시스템` 같은 한글 인자를 보존한다. 작업 이름(`/TN`)은 영문 접두사 + 한글 모드·과목(`KNOU_요약_…`) — argv 는 `CreateProcessW`(Unicode)로 전달되어 콘솔 코드페이지와 무관하게 안전.
- (⚠️ 버그·인코딩) **`schtasks` 출력은 UTF-8 이 아니라 OEM 콘솔 코드페이지(한국어=cp949)**. 처음에 `subprocess(text=True, encoding="utf-8")` 로 읽었더니 `�` 치환문자 발생 → 작업 이름의 한글 `도우미` 가 깨져 **접두사 필터가 실패(우리 예약이 목록에 안 뜸)** 할 뻔. → `_console_encoding()` 이 `kernel32.GetOEMCP()`(=cp949)로 디코딩하도록 수정. 실제 `schtasks /Query /FO CSV /NH` read-only 호출로 치환문자 없음·rc=0 확인.
- (중복 방지) 작업 이름이 (모드·과목·차시)에 대해 **결정적** → 같은 조건 재등록은 `/Create /F` 로 기존을 덮어써 중복이 생기지 않음. 화면에 "같은 조건 재추가 시 덮어씀" 안내.
- (안전장치 재사용) 이수/전체 예약은 **사람이 안 보는 시각에 형성평가가 자동 제출**되므로, Phase 3 의 `build_confirm_dialog`(동의 전 로직 차단)에 `start_label="예약 등록"` 파라미터만 추가해 그대로 재사용 → 등록 전 동의 다이얼로그 필수. 요약 예약은 확인 없이 바로 등록.
- (Flet 0.85 재확인) 모드/과목/차시는 `ft.Dropdown`(`on_select`), 반복은 `RadioGroup`(`on_change`), 시각은 `TextField`. 등록은 `threading.Thread` 로 `schtasks` 호출(UI 블로킹 회피). `page.show_dialog`/`pop_dialog`.
- (⚠️ 버그·권한, 수동검증 1차) 첫 GUI 등록에서 **"액세스가 거부되었습니다"** — 원인은 `/RL HIGHEST`(최고권한)였다. 최고권한 작업은 schtasks 가 **관리자 권한으로 실행**돼야만 등록되는데 앱은 일반 사용자라 거부됨. 이 앱은 관리자 권한이 불필요(브라우저 자동화 + 사용자 볼트 파일 쓰기)하므로 → **최고권한 기본 OFF** + `create_task` 가 거부 시 **일반 권한으로 자동 재시도(downgraded=True)** 하고 화면에 안내. 라이브 검증: 일반 권한으로 create→list→delete 성공, 목록에 `KNOU도우미_요약_운영체제_15강 | 2026-06-03 오전 2:00:00 | 준비`(한글·AM/PM 정상) 확인.
- (수동 게이트 남음) 실제 GUI에서 예약 추가→작업 스케줄러에 보임→지정 시각 실행→`logs/` 기록, 목록/삭제 동작은 **사용자가 직접 검증**. 특히 이수/전체 예약은 되돌릴 수 없는 자동 제출이므로 짧은 미이수 강의로 신중히 1회.

### Phase 4 보강 — 창 없이 실행 + 실행 탭 로그 보기 + 예약 on/off (2026-06-02)
- (요구) "예약은 잘 도는데 **터미널 창이 뜬다** → 창 띄우지 말고, 실행 결과를 **앱 안에서** 보게 해 달라" + "예약을 **잠시 끄는**(off) 기능도 필요".
- (창 숨김, VBS 런처) 작업 스케줄러가 `.bat` 을 `/TR` 로 직접 돌리면 콘솔 창이 깜빡인다. → `.bat` 을 **창 없이 실행하는 VBS**(`build_vbs_launcher`: `WScript.Shell.Run "<bat>", 0, False` — **0=SW_HIDE**)를 같은 폴더에 함께 만들고, `/TR` 을 `wscript.exe //B //Nologo "<vbs>"`(`build_run_command`)로 등록. `build_schtasks_create_args` 의 `/TR` 는 이제 **받은 명령을 그대로**(추가 따옴표 가공 없이) 넣는다(argv 리스트 한 원소로 전달 → schtasks 가 통째 저장). 라이브 확인: 등록 작업의 Action = `wscript.exe` / Args = `//B //Nologo "…run_summary.vbs"`, VBS 내용에 `, 0, False`.
- (실행 탭에서 로그 보기) 예약은 창 없이 백그라운드로 도니 화면 로그가 없다 → `main.py` 가 남기는 `logs/run_*.log` 가 유일한 흔적. `runner.latest_log_path()`(이름 내림차순=시간 내림차순으로 최신 1개) + `read_log_tail(path, n)`(마지막 n줄) 순수 헬퍼 추가, `run_view` 에 **"최근 실행 로그 보기"** 버튼 → 로그 패널에 최신 실행 로그를 불러옴. (비밀값은 로그에 안 남음 — 기존 철학 유지.)
- (예약 on/off) 삭제하지 않고 잠시 끄기: `build_schtasks_change_args(name, enabled)`(`/Change /ENABLE|/DISABLE`) + `set_task_enabled` 추가. 예약 표의 각 행에 **[끄기]/[켜기]·[삭제]** 버튼(처음엔 아이콘만이라 안 보인다는 피드백 → **글자 라벨 버튼**으로 변경, `build_task_row` 순수 함수로 분리해 단위테스트). 상태 `사용 안 함`이면 `is_disabled_status`로 감지해 회색·"(꺼짐)"·버튼 '켜기'. 라이브 확인: `/DISABLE`→State `Disabled`, `/ENABLE`→State `Ready`(rc=0). ※ 버튼은 **등록된 예약이 있어야** 그 줄에 나타남(목록 비면 안 보임).
- (이름 변경) "도우미"가 캐주얼하다는 피드백 → **앱 제목 `KNOU 형성평가 자동화 및 강의 노트 정리`**(창 제목 전용이라 길어도 무방), **작업 스케줄러 예약 접두사 `KNOU도우미_` → `KNOU_`**(영문·짧음). 접두사가 영문이라 cp949 인코딩이 틀려도 목록 필터가 안 깨지는 보너스. (예약 이름엔 '형성평가'를 안 붙임 — 요약 모드는 형성평가 제출이 없어 오해 소지.) 내부 Gemini 프롬프트의 '학습 도우미'/'매칭 도우미'는 화면 비노출이라 그대로 둠. 패키징 exe 도 `KNOU.exe`(Phase 5).
- (사용자 혼동 해소) 화면의 "다음 실행: N/A" 는 **한 번(ONCE) 예약이 이미 지난 경우**다(한 번짜리는 실행 후 다음 실행이 없음). **매일(DAILY)** 로 등록하면 다음 실행에 `다음 날 지정시각`(예: `2026-06-03 오전 2:00:00`)이 뜨고 매일 반복된다. 검증 중 만든 테스트용 ONCE 작업 2개(옛 접두사 `KNOU도우미_요약`, `KNOU도우미_요약_운영체제_15강`)는 삭제해 목록을 비움.
- (테스트) 순수 추가분: `build_vbs_launcher`/`build_run_command`/`/TR` 그대로/`build_schtasks_change_args`/`is_disabled_status`(schedule_win 5) + `latest_log_path`/`read_log_tail`(runner 4) + 실행 탭 로그 버튼 스모크(1) + `build_task_row` 끄기/켜기/콜백(app_views 3) = 전체 **257 통과**.
- (수동 게이트 남음) GUI에서 **매일** 요약 예약 1건 등록 → 지정 시각에 **창이 안 뜨고** 실행 → '실행' 탭 '최근 실행 로그 보기'에 그 로그가 보이는지, on/off 토글이 듣는지 **사용자 직접 1회 확인**.

### Phase 4 보강 2 — 실행 중 절전 억제(keep_awake) (2026-06-02)
- (요구) "자동 이수 돌아가던 중 **절전모드** 들어가면?" → 야간 무인 실행엔 입력이 없어 Windows 유휴 절전 타이머가 작동 → 영상 재생 멈춤(시청시간 0=이수 실패) + HLS 시한부 토큰 만료 + 깨어나도 세션 사망. (이미 자고 있으면 작업 자체가 시작 안 됨 — WakeToRun 기본 off.) 사용자 선택: **실행 동안만 절전 억제**(전역 전원설정·화면절전·main.py 불변).
- (런처) `keep_awake.py` 신규: `begin_keep_awake()`가 `SetThreadExecutionState(ES_CONTINUOUS|ES_SYSTEM_REQUIRED)`로 "시스템 자지 마" 요청 → `main.py` 를 자식 프로세스로 끝까지 실행 → `finally`에서 `end_keep_awake()`로 즉시 해제(프로세스 종료 시 자동 해제도 됨). 화면(모니터)은 숨겨진 실행이라 `ES_DISPLAY_REQUIRED` 미사용. 비 Windows/실패 시 조용히 통과(자식 실행은 항상 보장). 라이브 확인: `SetThreadExecutionState` → `0x1`(성공) 반환.
- (배선) `build_run_script` 가 `.bat` 에서 `python -u main.py …` → `python -u keep_awake.py main.py …`로 변경(래퍼가 같은 venv python=`sys.executable`로 자식 구동, `cd /d`·UTF-8 환경 그대로 상속). 체인: `wscript(숨김) → run_*.bat → keep_awake.py(절전억제 ON) → main.py → 종료 시 OFF`.
- (테스트) `keep_awake` 6(플래그 상수·자식 명령 빌더·begin/end 무예외·빈 인자 오류코드) + `build_run_script` keep_awake 경유/순서 1 = +7 → 전체 **264 통과**.
- (남은 보강 여지) PC가 시각 전부터 이미 자고 있으면 시작 자체가 안 됨 → 필요 시 WakeToRun(PowerShell/XML 등록) 별도 추가.

### Phase 5 — 패키징 & 배포 (권장경로 채택) (2026-06-02)
- (의사결정) 단일 `KNOU.exe`(`flet pack`)는 백엔드가 Playwright(브라우저 바이너리)·ffmpeg 의존이라 **번들이 취약·무겁고**(브라우저 ~300MB+, hidden-import 누락, 클린환경 스모크 까다로움) → 사용자 선택으로 **권장경로(소스+venv 기반 배포)** 채택. 단일 exe 는 보류하되 **frozen 보정 토대**(`sys.executable`이 exe 가 되는 문제 대비)는 미리 넣어 나중에 전환 가능하게 둠.
- (frozen 토대) `gui_core.is_frozen()`(`getattr(sys,'frozen',False)`) + `resource_path(rel)`(frozen=`sys._MEIPASS` / 소스=`BASE_DIR` 기준 — 아이콘 등 번들 리소스 경로 단일화). 소스 실행에선 동작 동일, exe 빌드 시 분기 진입점이 됨.
- (비개발자 실행) `deploy.py` 신규 — `pythonw_path(py)`(같은 폴더 `pythonw.exe`: **콘솔 창 없이** Flet 창만), `build_launch_command(py)`→`[pythonw,'-m','app.main_app']`, `build_shortcut_ps(...)`(WScript.Shell COM 으로 `.lnk` 생성 PowerShell 스크립트, 작은따옴표 `''` 이스케이프), `desktop_dir()`(OneDrive\Desktop 폴백), IO `create_desktop_shortcut()`. 비밀값은 명령·바로가기 어디에도 없음. 라이브 확인: 임시폴더 `.lnk` 생성 rc=0·파일 존재.
- (설정 탭) **[바탕화면 바로가기 만들기]** 버튼(`create_desktop_shortcut`) + **첫 실행 안내 배너**("처음이신가요? 필수(*) 채우고 저장…" — 필수값 누락 시에만 노출 → 설정 마법사 역할). 첫 실행 시 설정 탭 자동 오픈(`first_run_needed`)은 기존 유지.
- (문서) `README_GUI.md` — 비개발자용: 준비물(Python/ffmpeg/Gemini키) → 설치(venv·pip·playwright install) → 켜기(bat/바로가기) → 첫 설정 → 사용(실행·예약·로그·on/off) → **절전 안내** → 문제해결 → **안전요약(형성평가 비가역·비밀값 .env 한정·캡처 .gitignore)**.
- (테스트) `deploy` 8(pythonw 경로·실행명령·바로가기 PS 빌더·이스케이프·옵션생략·비밀값 미포함·desktop_dir) + `gui_core` 4(`is_frozen`/`resource_path` 소스·base·frozen) + `settings_view` 2(바로가기 버튼·첫실행 안내) = +14 → 전체 **278 통과**.
- (수동 게이트 남음) 설정 탭 [바탕화면 바로가기 만들기] → 바탕화면 `.lnk` 더블클릭 시 **콘솔 없이** 앱이 뜨는지 / 첫 실행 마법사로 `.env` 채워 예습 노트까지 동작하는지 **사용자 직접 1회 확인**.
- (남은 여지) 진짜 단일 exe 가 필요해지면 `flet pack` + **재실행 디스패치**(`KNOU.exe --run-backend …`로 main.py 대신 실행) + Playwright 브라우저 번들/경로 처리 + 클린환경 스모크를 별도 진행.
