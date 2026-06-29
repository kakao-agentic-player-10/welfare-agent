"""온통청년 청년정책 API 코드값 → 한글 매핑.

출처: docs/API코드정보.xlsx (온통청년 공식 코드집). 추측이 아니라 공식 표 기준이다.
"""

from __future__ import annotations

from typing import Any

MRG_STTS = {"0055001": "기혼", "0055002": "미혼", "0055003": "제한없음"}
EARN_CND = {"0043001": "무관", "0043002": "연소득", "0043003": "기타"}
JOB = {
    "0013001": "재직자", "0013002": "자영업자", "0013003": "미취업자", "0013004": "프리랜서",
    "0013005": "일용근로자", "0013006": "(예비)창업자", "0013007": "단기근로자",
    "0013008": "영농종사자", "0013009": "기타", "0013010": "제한없음",
}
SCHOOL = {
    "0049001": "고졸 미만", "0049002": "고교 재학", "0049003": "고졸 예정", "0049004": "고교 졸업",
    "0049005": "대학 재학", "0049006": "대졸 예정", "0049007": "대학 졸업", "0049008": "석·박사",
    "0049009": "기타", "0049010": "제한없음",
}
MAJOR = {
    "0011001": "인문계열", "0011002": "사회계열", "0011003": "상경계열", "0011004": "이학계열",
    "0011005": "공학계열", "0011006": "예체능계열", "0011007": "농산업계열", "0011008": "기타",
    "0011009": "제한없음",
}
SBIZ = {
    "0014001": "중소기업", "0014002": "여성", "0014003": "기초생활수급자", "0014004": "한부모가정",
    "0014005": "장애인", "0014006": "농업인", "0014007": "군인", "0014008": "지역인재",
    "0014009": "기타", "0014010": "제한없음",
}
APLY_PRD = {"0057001": "특정기간", "0057002": "상시", "0057003": "마감"}

# "제약 없음"에 해당해 자격 설명에서 생략하는 값.
_UNRESTRICTED = {"제한없음", "무관", "기타", ""}


def _get(item: dict[str, Any], key: str) -> str:
    lower = {str(k).lower(): v for k, v in item.items()}
    value = item.get(key)
    if value in (None, ""):
        value = lower.get(key.lower())
    return str(value).strip() if value not in (None, "") else ""


# 청년정책 코드값을 사람이 읽는 대상/자격 정보로 디코딩한다.
def decode_youth(item: dict[str, Any]) -> dict[str, Any]:
    job = JOB.get(_get(item, "jobCd"), "")
    sbiz = SBIZ.get(_get(item, "sbizCd"), "")
    mrg = MRG_STTS.get(_get(item, "mrgSttsCd"), "")
    earn = EARN_CND.get(_get(item, "earnCndSeCd"), "")
    school = SCHOOL.get(_get(item, "schoolCd"), "")
    major = MAJOR.get(_get(item, "plcyMajorCd"), "")
    aply = APLY_PRD.get(_get(item, "aplyPrdSeCd"), "")

    audience = [value for value in (job, sbiz) if value not in _UNRESTRICTED]
    conditions = []
    if mrg not in _UNRESTRICTED:
        conditions.append(f"결혼상태: {mrg}")
    if earn not in _UNRESTRICTED:
        conditions.append(f"소득조건: {earn}")
    if school not in _UNRESTRICTED:
        conditions.append(f"학력: {school}")
    if major not in _UNRESTRICTED:
        conditions.append(f"전공: {major}")
    return {
        "audience": audience,
        "conditions": conditions,
        "always_open": aply == "상시",
        "closed": aply == "마감",
    }
