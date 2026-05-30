# LMS 정찰 결과 (lms-map)

> `recon.py`로 직접 탐색하며 알아낸 셀렉터·URL·동작을 여기에 채운다.
> 이후 모든 단계(auth/discover/watch/download/capture)가 이 문서를 참조한다.

- 정찰 날짜: 2026-05-29 (진행 중)
- LMS 도메인: `ucampus.knou.ac.kr`
- "나의 학습"(강의목록) 페이지: `https://ucampus.knou.ac.kr/ekp/user/study/retrieveUMYStudy.sdo` (제목: 마이페이지-학습목록) ✅확인
- 학습하기(플레이어 컨테이너) 팝업: `https://ucampus.knou.ac.kr/ekp/user/study/retrieveUSTStudy.do` (제목: 학습하기) ✅확인
  - '강의보기' 클릭 시 **새 팝업 창**으로 열림 (about:blank → 위 URL 로 navigate)
- 실제 플레이어 iframe: `https://ucampus.knou.ac.kr/ekp/user/study/retrieveUSTStudyViewPlayer.do` ✅확인
  - 한 차시에 클립 여러 개(정찰 시 5개) → multiStream/playlist 구조

---

## 1. 로그인  ✅ 확인 (dump_dom.py로 로그인 페이지 HTML 분석)
- 로그인 페이지 URL: `https://ucampus.knou.ac.kr/ekp/user/login/retrieveULOLogin.do`
  - `retrieveUMYStudy.sdo` 등 보호 페이지 접근 시 자동 리다이렉트됨 (URL에 `rserpubk`=RSA공개키, `c_r_t`, `c_s_t` 쿼리 동반)
- 로그인 폼: `form#loginForm` (name=loginForm), method=post, `onsubmit="return false"`
- 아이디 입력칸: `#username` (name=username)
- 비밀번호 입력칸: `#password` (name=password)
- 로그인 버튼: `button[onclick*="actionLogin"]` (텍스트 "로그인") → JS `actionLogin()` 호출
- 탭: 방송대 학생/직원 = `#loginDivId li a[data-divcd="1"]` (기본 active). divcd=1이면 action=`/ekp/user/login/processULOLogin.do`
- hidden 필드: `strReturnUrl=/ekp/user/login/retrieveULOLoginCheck.sdo`, `_enpass_login_=submit`, `gateway=true`, `loginDivCd=1`
- **비밀번호 암호화**: `_enpass_login_`/`rserpubk` 기반 보안 스크립트가 submit을 가로채 처리(추정). → **직접 RSA 구현 불필요**, 진짜 필드 채우고 진짜 버튼 클릭하면 페이지 JS가 처리.
- "로그인됨" 판정 기준: `input[type=password]` 없음 + 페이지 제목에 "로그인" 없음 + URL이 login 페이지가 아님
- ⚠️ 세션 수명 짧음(jvmsso) + 헤드리스/하드클로즈 시 세션쿠키 유실 → **매 실행 로그인 여부 확인 후 필요시 재로그인** 필요

## 2. 강의(과목) 목록  ✅ 확인 (dom_myStudy_frame0.html 분석)
- 수강 과목 목록 페이지 URL: `retrieveUMYStudy.sdo` (= 나의 학습, 정적 HTML에 이미 렌더됨)
- 과목 컨테이너: `.lecture-progress .lecture-progress-item`
  - id = `lecture-{sbjtId}` (예: `lecture-KNOU1545001`)
- 과목명: `.lecture-title a.btn-toggle` 텍스트 (예: "이산수학")
- 과목 진도율(%): `.lecture-per .value` 텍스트 (예: "80")  / 진도바: `.per.01_rateBtn2` style width
- **형성평가 완료 배지**: `.divi2` 텍스트 "형성평가완료" 존재 여부
- 과목 식별자(차시 조회용): `ul.lecture-list[data-atlc][data-stype]`
  - `data-atlc` = atlcNo (강의계획서 번호, 예: "14802079")
  - `data-stype` = sType (예: "01")
- 버튼 onclick 인자: `fnCoursePage(atlcNo, sbjtId, sbjtCd)`, `fnCourseDataPage(...)`(강의자료),
  `fnManagerPage(...)`(과제/시험), `fnCounseling(sbjtId)`, `fnReload(year, sem, sbjtId, atlcNo, this)`
- 형성평가 기간/완료기준: `.well2`에 기간, 배점 `학습영상:N점, 연습문제:N점`,
  완료기준 "12강 이상 학습영상 진도율 충족. 연습문제 풀이 필수(정오답 무관)"

## 3. 강의(차시) 목록 & 진도  ✅ 확인 (AJAX JSON 엔드포인트 발견)
- **차시 목록은 토글 클릭 시 AJAX로 로드** → 직접 JSON 호출이 가장 신뢰성 높음:
  - URL: `POST /ekp/user/study/retrieveUMYAtlcLectList.ajax`
  - body(form-encoded): `atlcNo={data-atlc}&sType={data-stype}`, header `Content-Type: application/json`
  - 응답 JSON: `data.atlcList[0].lectList[]` (+ `data.cntsInfo`, `atlcList[0].scafValuDc`, `atlcList[0].sbjtId`)
- lectList[i] 주요 필드:
  - `lectPldcTocSeq` 차시번호 + `medDvCd`(01/09→"회", else "강") + `lectPldcTocNm` 차시명
  - `stdyHrMnt` 학습(시청)한 분, `vidoHrSec` 전체 분  → 진도 "stdyHrMnt분 / vidoHrSec분"
  - **`stdyCmyn`="Y" → 학습영상 이수완료** (DOM에선 `i.checked`="수강완료" + `a.ch`(학습)에 `on` 클래스)
  - 연습문제 완료: `valuCmyn`="Y" 또는 `examRespYn`="Y" (DOM `a.ch`(연습문제)에 `on`)
  - `useYn`="N" → "제작중입니다"(영상 없음, 스킵)
  - `cntsTc`="01" 내부영상(fnCntsPopup으로 재생) / "03" 외부링크(cnnctUrl)
  - 강의보기 인자: `fnCntsPopup(strSbjtId, strLectPldcTocNo, strAtlcNo, useYn, scafValuDc, sbjtId)`
- 차시 DOM(확장 후): `li#lecture-pldc-{sbjtId}{lectPldcTocNo}`, 제목 `a.lecture-title`,
  강의보기 `a.lecture-view`, 진도 `.lecture-list-in li.time .time1`(시청)/`.time2`(전체)
- 이수 완료 표시: `stdyCmyn=="Y"` (JSON) / `i.checked`·`a.ch.on` (DOM)

## 4. 동영상 플레이어
- 플레이어 위치: **팝업창(`retrieveUSTStudy.do`) 안의 iframe(`retrieveUSTStudyViewPlayer.do`)** ✅
- 엔진: **JWPlayer 7.4.3** + 위앤소프트 wenplayer / `Streamingway.SniperPlayerV2`
  - 로드 스크립트: `/html/wenMedia/wenplayer.js`, `/html/wenMedia/jwplayer/jwplayer.js?v=0.2`, `multiStream.js`, `playlist.js`
- `<video>` 태그 존재 여부: 있음(추정, iframe 내부) — JWPlayer가 MSE로 생성 / **정찰 2차로 readyState·position 재확인 필요**
- 영상 소스: **HLS** — 호스트 `sdnw.knou.ac.kr`
  - 패턴: `https://sdnw.knou.ac.kr/<코스ID>/<클립ID>.mp4/playlist.m3u8?token=<JWT>` → `content.m3u8` → `content_0.ts, content_1.ts, ...`
  - 인증: URL `token=`(JWT, `exp` 만료) + `solsessionid`. **AES 암호화 키 흔적 없음 → ffmpeg 직접 다운로드 가능성 높음**
  - 클립ID 예: `KNOU15450012021101303H`(코스 `KNOU1545001`)
- **멀티클립 구조** ✅: 한 차시 = 부모 `retrieveUSTStudy.do`(frame0) + 클립 N개 iframe
  `ifrmVODPlayer_0..N`(각 `retrieveUSTStudyViewPlayer.do`). 정찰 시 13강=5클립.
  - 각 클립 iframe 안에 전역 `$player = jwplayer("divMovie_1")` 인스턴스(렌더 div id=`player0`)
  - 클립별 이어보기 위치 = `continuePos`(초). 예: clip1=97, clip4=1807
- **재생 제어** ✅ (클립 iframe 내 함수):
  - 시작 `fnPlayStart()`(=$player.play()), 정지 `fnPlayStop()`, 토글 `fnPlayToggle()`
  - **배속 `fnPlaySpeed(val)`** → `wp_changePlaybackRate(...)`. 가능값 0.5/0.8/1.2/1.4/1.6/1.8/**2.0**. 기본 settings.speed=1.4
  - autoStart="N" → **재생버튼 클릭(또는 $player.play()) 필요**. 초기 상태 jw-state-idle, 큰 ▶ 오버레이
- **seek 비활성** ✅: `vidoFwdYn="N"`,`vidoRewdYn="N"` → 앞으로감기/되감기 UI 숨김.
  **끝으로 점프 불가 → 실시간(배속) 재생 필수** = time-budget 방식 정당함
- **진도 보고** ✅ (가장 중요):
  - 클립 iframe `fnCheckPlayTime()`가 1초마다 돌며 state=="playing"일 때 **실제 벽시계 시간 `timeCheck`(ms) 누적**
  - 누적 300초(5분)마다 + play/pause/complete 시 `parent.fnPlayerProgCheck(tocNo, playTimeSec, vidoLocSec, speed, state)` 호출
  - 부모 frame0 `fnPlayerProgCheck` → **POST `/ekp/user/study/registerUSTStudyRslt.ajax?state=<state>`**
    (body = `#frm` serialize, 필드 `timeSec`=실제재생초, `vidoSpd`=배속, `vidoLocSec`=위치, `timeLectPldcTocNo`)
  - 응답 `resultMsg`: "Y"/"S"(다른기기접속→창닫힘)/"NS"(세션종료). → **단일 세션만 유지**할 것
- **돌발퀴즈** ⚠️: `wp_event_savePostion`이 `tmpVidoHrSec`의 특정 위치 도달 시 `$player.pause()` 후
  `parent.fnOutQuiz(tocNo, tespNo)` → 모달 `#quiz_{tocNo}_{tespNo}` 표시(영상 멈춤).
  형성평가대상(scafValuDc=Y, examCnt>0) 차시에 존재. **정오답 무관** → 아무 답 제출 후 재개 필요.
  - 제출: `registerUSTStudyExamRslt.ajax` / 연습문제 `registerUSTStudyPldcRply.ajax`
- "학습종료" 버튼: `fnStudyEnd()` → confirm 후 `registerUSTStudyLastRslt.ajax`(최종 저장) 후 창 닫힘
- 이어보기 모달: `econtinue="Y"` 설정 있으나 continuePos는 클립 setup에 직접 주입됨(모달 없이 자동 이어보기로 보임)

### 4-1. 진도 적립 메커니즘 — 실측 확정 (15강 풀 파일럿, 2026-05-29) ✅✅
- **적립 기준 = 영상 '위치'(vidoLocSec) 커버리지**, 실제 벽시계 초가 아님.
  - **2배속 100% 풀 크레딧**: 12분→114분(Δ+102분 적립)을 **실제 55분**에 완료. `done=False→True`.
- **저장 시점**: ① `state=play` 하트비트가 **300 실초마다**(timeSec=300, vidoSpd=2 확인) ②클립 종료/일시정지 시 `state=stop`(vidoLocSec=끝위치). POST `registerUSTStudyRslt.ajax`.
- **0초 재시작 절대 금지**: vidoLocSec이 0으로 리셋되면 서버 적립이 깎인다(13강이 watched=2에 멈춰 있던 원인).
- **재생기록(이어보기) 모달 2종 — 예/아니오 의미가 정반대(id로만 판별)**:
  - 모달1 "이어서 시청하시겠습니까?"(부분시청): 예=`wp_elearning_seek`(이어보기) / 아니오=`wp_elearning_play`(처음부터)
  - 모달2 "처음부터 다시 시청하시겠습니까?"(이미 완청): 예=`wp_elearning_play`(처음부터 ← **절대 클릭 금지**) / 아니오=`wp_elearning_stop`(취소)
  - 자동이수는 모달1=seek 클릭, 모달2=stop 클릭. **wp_elearning_play 는 어떤 경우에도 누르지 않음.** (실측: 728초에서 0초 재시작 없이 정상 이어짐)
- **`prog_rt`(진도율) 신뢰 불가**: 재생과 무관하게 0↔50 흔들림 → 완료판정은 **`stdyCmyn`(=video_done)만** 사용.
- **멀티클립**: 차시당 영상 1~3개(가변). ViewPlayer 슬롯에 빈 것 섞임 → `<video>` 유무로 필터(`clip_inventory`). 15강=clip0(6883초·전체강의)+clip1(138초) 둘 다 커버해야 완료.
  - ⚠️ 짧은 클립은 종료 시 `ended` 플래그 없이 `<video>`가 언로드(pos=0/dur=None)될 수 있음 → 종료감지에 "재생후 video 사라짐 2회연속" 보강(`_play_until_end`).
- 구현: `watch.py` `watch_lecture()` / `_play_until_end()` / `_trigger_save()` / `_handle_resume_modal()`. 검증 스크립트 `watch_one.py`.

## 5. 🔑 DRM / 화면 캡처 가능 여부  ✅ 확정
- 전체 화면 스크린샷 밝기: 148.9~237.3/255 → 검은화면 아님(내용 보임) ✅
- **영상 영역 스크린샷 밝기: 231.2/255 → 검은화면 아님, 실제 영상 프레임 캡처됨** ✅ (tab2_video.png)
- 영상 재생 확인: `.ts` 조각이 content_0~content_39 연속 다운로드 → 실제 재생 진행 확인 ✅
- **결론(확정): DRM 화면차단 없음.** 캡처 경로 두 가지 모두 가능:
  - 경로 A: 브라우저 `<video>` 영역 스크린샷 (밝기 정상)
  - 경로 B(유력): **ffmpeg로 HLS(.m3u8/.ts) 직접 다운로드 → 프레임 추출** (AES 키 없음, 토큰만)
  → Phase 6 영상 화면 캡처는 검은화면 걱정 없이 진행 가능.

## 6. 강의자료 다운로드  ✅ 정찰·구현 검증 (probe_data*.py + download.py, 이산수학 1강 실측)
- **MP3(음성)**: lectlist JSON(§3)의 `strVidoAudoUrl`에 **절대 URL이 이미 존재** → 정찰 불필요.
  - 예: `https://sdn.knou.ac.kr/AD/KNOU1545001/KNOU15450012021101.mp3` (sdn.knou.ac.kr CDN)
  - `discover.Lecture.audio_url`에 파싱해 둠. persistent context 세션으로 GET → 정상(1강 39.9 MB, `ID3` 헤더).
- **PDF(강의록)**: 별도 **강의자료실(게시판)**에서 받음. lectlist엔 PDF 링크 없음.
  - 진입: 나의학습 페이지의 `fnCourseDataPage(atlcNo, sbjtId, cntsId)` → form POST
    `/ekp/user/lectureData/initUCRLectureData.do` (cntsId = sbjtId 끝3자리 제거, 예 KNOU1545001→KNOU1545)
  - 글 목록: `POST /ekp/user/lectureData/initUCRLectureData.ajax` (페이지의 `$('#frm').serialize()`,
    `recordCountPerPage`/`pageIndex` 조정). 응답 `data.list[]` 각 글에 첨부 메타 직접 포함:
    `bdotNo`, 분류 `sbjtBdotClcd`, 제목 `sbjtNotcTitNm`, `fileCnt`,
    표시명 `apndFileNm`, 저장명 `apndFileSaveNm`(멀티첨부는 `:`로 구분).
  - **차시 매칭**: 분류 `'강의자료'` + `apndFileNm`이 `'NN-'`(2자리 0패딩, seq)로 시작하는 글.
    (1~4강 제목은 "1강-..", 5강+는 "05-.." 식이라 제목 대신 **apndFileNm 접두사**로 매칭이 안정적.)
    이산수학: 1강=`01-이산수학의개요(수정).pdf`(bdotNo 106970) … 15강=`15-교과목 정리 (강의자료).pdf`(108532).
    분류 '강의자료'라도 정오표(NN- 없음)는 매칭 안 됨. 기출문제/인터넷보충학습 등은 별도 분류.
  - **다운로드 URL**: `GET /user_uploading?pathkey=COURSE.DATA&addSavePath={sbjtId}`
    `&getfile={apndFileSaveNm}&realFileName={apndFileNm(URL인코딩)}`
    (저장은 우리가 직접 이름 부여하므로 realFileName은 Content-Disposition용·선택. 1강 PDF 2.2 MB, `%PDF-1.5`.)
- **파일명 규칙**: `download.build_filename(subject, seq, ext)` = `"{과목}_{seq}강.{ext}"`
  (금지문자 `\/:*?"<>|`→`_`). 예: `이산수학_1강.mp3`, `이산수학_1강.pdf`. 저장 폴더 `cfg.downloads_dir`.
- **재실행**: `needs_download(path)`(없음/0바이트)로 판정 → 기존 파일 skip(멱등). 실측 검증 완료.
- 구현: `download.py`(순수: sanitize/build_filename/needs_download/build_file_url/match_pdf_post +
  브라우저: fetch_data_posts/download_url/download_lecture), 검증: `download_one.py`, 테스트: `tests/test_download.py`(12).

## 7. 형성평가(연습문제)  ✅ 정찰 (player_frame0.html + probe_exam.py)
- **위치**: 플레이어 팝업의 **메인 프레임(`retrieveUSTStudy.do`, ViewPlayer 아님)** 안 `.exam-content-box`
  (제목 "형성평가대상 연습문제"). 영상과 독립 — **영상 완청해도 연습문제는 자동완료 안 됨**(15강 실측: 영상done=True인데 exam_done=False).
- **구조**: 한 연습문제 세트 = `tespNo` 1개에 문항 N개(15강=8문항, 13강=10문항).
  - 문항별 `<form name="frm_{tespNo}_{exqsId}">`, hidden: `tespNo`,`examApexNo`,`exqsId`,`sbjtId`,`lectPldcTocNo`,`exqsDc`,`exqsTc`,`resultCnt`,`ansCn`
  - 4지선다 = `input.answerCh`(radio) 4개 / 서술형이면 `.answerTxt`
  - 문항 선택 버튼 `li.exam-number-btn`(Q1..QN, 클릭 시 해당 form 활성화), 완료표시 `li#mark_{...}_{exqsId}`
  - 정답 확인 버튼 `button.confirmAnswer`(form마다 1개), 다음문항 `.btnNext`
- **제출 흐름(정오답 무관의 실제 동작)** — `.confirmAnswer` 핸들러(frame0 JS):
  - 답 미선택 시 alert("답변을 선택해주세요") → 등록 안 됨. 반드시 `.answerCh` 1개 check 후 클릭.
  - `exqsTc=='2' && exqsDc in('3','4') && resultCnt==0`(첫 시도): `retrieveUSTStudyExamRslt.ajax`로 **정답 먼저 검사** →
    - 오답(resultVal=='N'): alert("다시 한번 생각해 보세요") 후 **등록 안 함**, resultCnt=1 세팅
    - 정답: `registerUSTStudyExamRslt.ajax` 등록
  - 그 외(resultCnt==1 즉 **2번째 클릭** 또는 다른 타입): **정오답 무관 `registerUSTStudyExamRslt.ajax` 등록**
  - ⇒ 자동화: 각 문항 라디오 선택→확인. 오답 alert면 한 번 더 확인 → 등록. (1문항당 최대 2클릭)
  - 콜백 `fnExqsCallback`. ⚠️ `registerUSTStudyPldcRply.ajax`는 **연습문제가 아니라 Q&A 댓글 등록**(`fnReplyInsert`,`rplCn`)이니 혼동 금지.
- **돌발퀴즈**(별개): 영상 중 `fnOutQuiz(toc,tesp)` → 모달 `#quiz_{toc}_{tesp}`(예: `quiz_221135_22315`), 제출도 `.confirmAnswer`/`registerUSTStudyExamRslt.ajax`. 이어보기로 트리거 위치를 지나치면 안 뜸.
- **완료 판정**: `examRespYn=='Y'` 또는 `valuCmyn=='Y'`(discover.exam_done). **✅실측 검증(15강)**: 8문항 응답 등록 → exam_done False→True.
  - 실측: 첫 답(보기1)이 오답이면 alert "다시 한번 생각해 보세요" → 2번째 클릭으로 정오답 무관 등록(제출 XHR `registerUSTStudyExamRslt`). 정답이면 1클릭 등록.
- ⚠️ **주의**: 실제 답안이 서버에 제출되는 되돌릴 수 없는 행위. 배점 "학습영상15+연습문제5" 중 연습문제 5점은 풀이(정오답무관)로 부여되는 구조로 보임.
- 구현: `exercise.py` `solve_exercises(popup, dialog_msgs, ...)`. 호출 측이 `popup.on("dialog")`로 alert accept+수집. 테스트 `solve_exam_15.py`.
- 미완 현황(2026-05-29): 영상done = 1~12 + 15강(13개), exam_done = 1~12 + 15강. **남은 미완: 13·14강(영상·연습문제 둘 다)**.

## 8. 강의 요약 (Gemini)  ✅ 구현 검증 (summarize.py, 이산수학 1강 실측)
- **입력**: 다운로드한 MP3(음성) + PDF(강의록)를 **함께** google-genai File API로 업로드.
  - MP3 = 정확한 음성 타임스탬프 근거, PDF = 내용/교재 페이지 매핑.
  - **모델**: `gemini-2.5-flash` (DEFAULT_MODEL). 40MB MP3 업로드/요약 정상.
- **⚠️ 한글 파일명 업로드 함정**: google-genai가 파일 경로 업로드 시 `X-Goog-Upload-File-Name` 헤더에
  basename(한글)을 그대로 넣어 httpx ASCII 인코딩 실패(`UnicodeEncodeError`).
  → **파일 객체(`open(path,'rb')`) + 명시적 `config={'mime_type': ...}`로 업로드**하면 헤더를 안 붙여 우회됨.
  (`_extra_utils.prepare_resumable_upload` L675-678: str/PathLike일 때만 파일명 헤더 추가.)
- **업로드 대기**: `client.files.upload` 후 `client.files.get(name=...)`로 `state`가 `ACTIVE` 될 때까지 폴링(FAILED/timeout 예외).
- **프롬프트**(`build_prompt`): `# {과목} {N}강 - {차시명}` 제목 → `##`대주제/`###`핵심개념, 개념마다
  `🎬 [HH:MM:SS]`(음성 기준 근사치) + `(교재 p.N)`, KaTeX 인라인 `$...$`, 끝에 `## 핵심 요약`. 코드펜스 금지.
- **출력**: 볼트의 `summary_dir`(=`VAULT_PATH/SUMMARY_SUBDIR`, 기본 `방송대`)에
  - `{과목} {N}강 - {차시명}.md` (요약 노트)
  - `{과목} {N}강 - {차시명}.timestamps.json` (Phase 6 캡처용 사이드카: `[{timestamp,seconds,label}]`, 초 기준 dedupe)
- **타임스탬프 추출**(`extract_timestamps`): 마크다운 줄에서 `[HH:MM:SS]`/`[MM:SS]` 정규식 매칭 → 초 변환·정규화,
  라벨은 줄에서 ts/이모지(🎬)/볼드(`**`)/리스트마커/잔여구두점 제거.
- **재실행 skip**: `needs_summary(note_path)` — 노트가 있고 비어있지 않으면 skip.
- **🔑 보안**: `GEMINI_API_KEY`는 config에서만 사용, 로그/출력에 절대 노출 금지.
- 구현: `summarize.py`(순수: timestamp 변환/note_filename/needs_summary/extract_timestamps/build_prompt,
  IO: upload_and_wait/summarize_lecture/save_summary). 단위테스트 `tests/test_summarize.py`(14개), 수동검증 `summarize_one.py`.
- **실측(이산수학 1강, 2026-05-30)**: 요약 노트 8.4KB + 타임스탬프 12개. DIKW/추상화/알고리즘/의사코드 제어구조 등 구조화, 교재 페이지·KaTeX·표 포함.

## 9. 동영상 화면 캡처 (Phase 6)  ✅ 구현 검증 (capture.py, 이산수학 1강 12프레임 실측)
- **방식**: ffmpeg로 HLS m3u8에서 타임스탬프 지점 단일 프레임(jpg) 추출. DRM 차단 없음(§5)이라 스크린샷/PDF fallback 불필요.
- **⚠️ 영상이 차시당 여러 클립으로 쪼개짐**: 플레이어 팝업 메인 프레임에 전역 `ifrmVODPlayer_data0..N` 존재.
  각 클립 = `{source[0].fileTitle, source[0].stream[0].hlsUrl(고/저화질)}`.
  - 이산수학 1강 실측: [0]오리엔테이션 41:30 / [1]들어가기 3:07 / [2]학습하기 54:59 / [3]정리하기 4:58 / [4]수학의 발견 0:56.
  - ⚠️ 정찰HTML(player_frame0.html)의 toc/토큰은 stale → **라이브로 조회 필수**(toc도 다름).
- **MP3↔클립 매핑(핵심)**: 다운로드한 MP3(`strVidoAudoUrl`)는 **특정 한 클립의 오디오와 길이가 정확히 일치**.
  - 1강: MP3 2490.97s == 클립[0] 오리엔테이션 2490.92s (차 0.0s). → **요약 타임스탬프(MP3 기준)와 그 클립 영상이 1:1**.
  - 규칙: `pick_clip_by_duration(clips, mp3_dur)` = MP3 길이에 **가장 가까운 클립** 선택(자급자족, 추가정보 불필요).
- **HLS URL/토큰**: `https://sdnw.knou.ac.kr/{sbjtId}/{file}H.mp4/playlist.m3u8?token=<JWT>`.
  JWT payload에 `path`,`exp`(발급~2시간). 토큰이 URL에 있어 ffmpeg가 세션 없이 직접 접근 가능하나,
  안전하게 **플레이어 팝업을 캡처 끝날 때까지 열어 둔 채** 진행.
- **ffmpeg 명령**: `ffmpeg -y -loglevel error -ss {sec} -i {url} -frames:v 1 -q:v 2 -an {out.jpg}`
  (`-ss`를 `-i` 앞 = 입력단계 fast seek, 키프레임 스냅 — 타임스탬프 근사치라 충분). ffprobe로 클립 길이 측정.
- **저장/임베드**: 볼트 `summary_dir/_captures/{과목}_{seq}강_{HH-MM-SS}.jpg`.
  `embed_captures(md, {sec:fn})` — 타임스탬프 줄 **바로 아래**에 `![[fn]]` 인라인 삽입(같은 sec이 여러 줄이면 각 줄에, 멱등).
- **재실행 skip**: `needs_capture(path)`(없음/0바이트). 캡처 성공/기존분만 임베드 → 실패해도 노트 안 깨짐.
- 구현: `capture.py`(순수: capture_filename/pick_clip_by_duration/build_ffmpeg_cmd/needs_capture/embed_captures,
  IO: probe_duration/collect_clips/resolve_clips/capture_frame/capture_lecture). 테스트 `tests/test_capture.py`(17), 정찰 `probe_video.py`, 수동검증 `capture_one.py`.
- **실측(이산수학 1강, 2026-05-30)**: 12프레임 캡처(73~156KB) 전부 선명한 슬라이드, 노트에 `![[..]]` 13개(=37:35 두 줄 언급) 임베드. 위치 정확도 양호(라벨↔화면 일치). 단 타임스탬프는 근사치라 1~2분 드리프트 가능.

## 10. 기타 메모
-
