"""discover 모듈 순수 파싱/필터 로직 단위 테스트.

실제 LMS JSON(recon_shots/lectlist_sample.json)에서 확인한 필드명을 기반으로
- parse_lecture: 차시 1건(raw dict) → Lecture
- parse_lectures: AJAX 응답 전체(dict) → list[Lecture]
- filter_incomplete: 영상 미이수 + 영상 있는 차시만
- parse_course_row: 나의학습 DOM 추출 dict → Course
- parse_progress: "55분 / 55분" 텍스트 → (시청분, 전체분)
를 검증한다. 브라우저 연동(list_courses/fetch_lectures)은 수동 검증.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from discover import (  # noqa: E402
    Course,
    Lecture,
    filter_incomplete,
    parse_course_row,
    parse_lecture,
    parse_lectures,
    parse_progress,
)

# 실제 JSON에서 가져온 완료 차시(1강) 형태
DONE_RAW = {
    "lectPldcTocSeq": "1",
    "lectPldcTocNm": "이산수학의 개요",
    "stdyHrMnt": "55",
    "vidoHrSec": "55",
    "lectProgRt": "100",
    "stdyCmyn": "Y",
    "valuCmyn": "Y",
    "examRespYn": "Y",
    "useYn": "Y",
    "cntsTc": "01",
    "sbjtId": "KNOU1545001",
    "lectPldcTocNo": "207542",
    "atlcNo": "14802079",
    "strSbjtId": "VV1avsxR+c5uz6dJs8QQnA==",
    "strLectPldcTocNo": "dmC3VF7lezqzP0Jb0bCD4Q==",
    "strAtlcNo": "CcQ5ljhl3BJxXNjhMlmBLQ==",
    "vidoUrl": "/KNOU1545001/KNOU15450012021100105H.mp4",
}

# 미완료 차시(13강): 2/105분, 진도 50%, stdyCmyn=N
PARTIAL_RAW = {
    "lectPldcTocSeq": "13",
    "lectPldcTocNm": "정수론",
    "stdyHrMnt": "2",
    "vidoHrSec": "105",
    "lectProgRt": "50",
    "stdyCmyn": "N",
    "valuCmyn": "N",
    "examRespYn": "N",
    "useYn": "Y",
    "cntsTc": "01",
    "sbjtId": "KNOU1545001",
    "lectPldcTocNo": "207554",
    "atlcNo": "14802079",
    "strSbjtId": "enc-s",
    "strLectPldcTocNo": "enc-t",
    "strAtlcNo": "enc-a",
    "vidoUrl": "/KNOU1545001/x.mp4",
}

# 미시청 차시(14강): 0분
NOTSTARTED_RAW = dict(PARTIAL_RAW, lectPldcTocSeq="14", lectPldcTocNm="오토마타",
                      stdyHrMnt="0", vidoHrSec="111", lectProgRt="0")

# 제작중(영상 없음) 차시
NOVIDEO_RAW = dict(PARTIAL_RAW, lectPldcTocSeq="99", lectPldcTocNm="제작중", useYn="N")


def test_parse_lecture_done():
    lec = parse_lecture(DONE_RAW)
    assert lec.seq == 1
    assert lec.name == "이산수학의 개요"
    assert lec.watched_min == 55
    assert lec.total_min == 55
    assert lec.prog_rt == 100
    assert lec.video_done is True
    assert lec.exam_done is True
    assert lec.has_video is True
    assert lec.sbjt_id == "KNOU1545001"
    assert lec.toc_no == "207542"
    assert lec.enc_sbjt_id == "VV1avsxR+c5uz6dJs8QQnA=="


def test_parse_lecture_partial_not_done():
    lec = parse_lecture(PARTIAL_RAW)
    assert lec.seq == 13
    assert lec.watched_min == 2
    assert lec.total_min == 105
    assert lec.video_done is False
    assert lec.exam_done is False
    assert lec.has_video is True


def test_parse_lecture_handles_missing_and_none():
    lec = parse_lecture({"lectPldcTocSeq": "5", "lectPldcTocNm": "X",
                         "stdyHrMnt": None, "vidoHrSec": ""})
    assert lec.seq == 5
    assert lec.watched_min == 0
    assert lec.total_min == 0
    assert lec.video_done is False
    assert lec.has_video is False  # useYn 없음 → 영상 없음 취급


def test_parse_lectures_from_ajax_shape():
    payload = {"atlcList": [{"sbjtId": "KNOU1545001", "sbjtNm": "이산수학",
                             "lectList": [DONE_RAW, PARTIAL_RAW, NOTSTARTED_RAW]}]}
    lects = parse_lectures(payload)
    assert len(lects) == 3
    assert [l.seq for l in lects] == [1, 13, 14]


def test_parse_lectures_empty_payload():
    assert parse_lectures({}) == []
    assert parse_lectures({"atlcList": []}) == []
    assert parse_lectures({"atlcList": [{"lectList": None}]}) == []


def test_filter_incomplete_excludes_done_and_novideo():
    lects = [parse_lecture(r) for r in
             (DONE_RAW, PARTIAL_RAW, NOTSTARTED_RAW, NOVIDEO_RAW)]
    todo = filter_incomplete(lects)
    # 완료(1강) 제외, 제작중(영상X) 제외 → 13강, 14강만
    assert [l.seq for l in todo] == [13, 14]


def test_parse_course_row():
    row = {
        "id": "lecture-KNOU1545001",
        "title": "이산수학",
        "progress": "80",
        "badge": "형성평가완료",
        "atlcNo": "14802079",
        "sType": "01",
    }
    c = parse_course_row(row)
    assert isinstance(c, Course)
    assert c.sbjt_id == "KNOU1545001"
    assert c.name == "이산수학"
    assert c.progress == 80.0
    assert c.atlc_no == "14802079"
    assert c.s_type == "01"
    assert c.fmtv_done is True


def test_parse_course_row_not_done_badge():
    row = {"id": "lecture-KNOU1823001", "title": "원격대학교육의이해",
           "progress": "85.71", "badge": "", "atlcNo": "14802072", "sType": "01"}
    c = parse_course_row(row)
    assert c.progress == 85.71
    assert c.fmtv_done is False


def test_parse_progress_text():
    assert parse_progress("55분 / 55분") == (55, 55)
    assert parse_progress("2분 / 105분") == (2, 105)
    assert parse_progress("-") == (0, 0)
    assert parse_progress("") == (0, 0)
