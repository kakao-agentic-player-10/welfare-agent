from __future__ import annotations

import re
from typing import Any

from welfare_agent.domain.regions import KNOWN_SIGUNGU


TARGET_KEYWORDS = {
    "youth": ["청년", "취준", "취업준비", "1인", "월세", "구직", "교통"],
    "newlywed": ["신혼", "혼인"],
    "single_parent": ["한부모", "조손"],
    "senior": ["노인", "어르신", "고령", "독거노인", "홀몸"],
    "disabled": ["장애", "장애인"],
    "pregnant": ["임산부", "임신", "출산", "난임"],
    "student": ["대학생", "중학생", "고등학생", "초등학생", "학생", "등록금", "학자금"],
    "job_seeker": ["구직", "취업준비", "취준", "면접", "자격증", "일자리"],
    "one_person_household": ["1인", "혼자", "독거"],
    "small_business": ["소상공", "자영업", "개인사업자", "매출", "정책자금", "경영"],
}

SEOUL_DISTRICTS = {
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
}

BROAD_REGION_ALIASES = {
    "서울특별시": ("서울", "서울시", "서울특별시"),
    "부산광역시": ("부산", "부산시", "부산광역시"),
    "대구광역시": ("대구", "대구시", "대구광역시"),
    "인천광역시": ("인천", "인천시", "인천광역시"),
    "광주광역시": ("광주", "광주광역시"),
    "대전광역시": ("대전", "대전시", "대전광역시"),
    "울산광역시": ("울산", "울산시", "울산광역시"),
    "세종특별자치시": ("세종", "세종시", "세종특별자치시"),
    "경기도": ("경기", "경기도"),
    "강원특별자치도": ("강원", "강원도", "강원특별자치도"),
    "충청북도": ("충북", "충청북도"),
    "충청남도": ("충남", "충청남도"),
    "전북특별자치도": ("전북", "전라북도", "전북특별자치도"),
    "전라남도": ("전남", "전라남도"),
    "경상북도": ("경북", "경상북도"),
    "경상남도": ("경남", "경상남도"),
    "제주특별자치도": ("제주", "제주도", "제주특별자치도"),
}

SIGUNGU_TO_SIDO = {
    **{district: "서울특별시" for district in SEOUL_DISTRICTS},
    "해운대구": "부산광역시",
    "달서구": "대구광역시",
    "남동구": "인천광역시",
    "유성구": "대전광역시",
    "수원시": "경기도",
    "원주시": "강원특별자치도",
    "제주시": "제주특별자치도",
}

TARGET_PRIORITY = [
    "single_parent",
    "disabled",
    "pregnant",
    "senior",
    "newlywed",
    "small_business",
    "job_seeker",
    "student",
    "youth",
    "one_person_household",
]


# 자연어/필드 입력을 하나의 지원금 탐색 프로필로 정규화한다.
def build_profile(
    *,
    text: str = "",
    age: int | None = None,
    region: str = "",
    household_type: str = "",
    employment_status: str = "",
    housing_type: str = "",
    marital_status: str = "",
    business_type: str = "",
    revenue_status: str = "",
    interests: list[str] | None = None,
) -> dict[str, Any]:
    interests = interests or []
    if age is None:
        age = infer_age(text)
    inferred = infer_target_type(text, interests, marital_status, business_type)
    if inferred in {"general", "one_person_household"} and isinstance(age, int) and 19 <= age <= 34:
        inferred = "youth"
    if not region:
        region = infer_region(text)
    region_sido, region_sigungu = infer_region_parts(" ".join([text, region]))

    audience_tags = infer_audience_tags(text, inferred)
    if isinstance(age, int) and 19 <= age <= 34:
        audience_tags = sorted(set(audience_tags + ["youth"]))
    dependent_tags = infer_dependent_tags(text)
    dependent_age_min, dependent_age_max = infer_dependent_age_range(dependent_tags)
    strict_eligibility_requested = infer_strict_eligibility_requested(text)
    missing = missing_fields(
        inferred,
        region,
        age,
        marital_status,
        business_type,
        strict=strict_eligibility_requested,
    )
    return {
        "text": text,
        "target_type": inferred,
        "audience_tags": audience_tags,
        "age": age,
        "region": region,
        "region_sido": region_sido,
        "region_sigungu": region_sigungu,
        "household_type": household_type or infer_household(text),
        "employment_status": employment_status or infer_employment(text),
        "housing_type": housing_type or infer_housing(text),
        "marital_status": marital_status,
        "business_type": business_type,
        "revenue_status": revenue_status,
        "interests": sorted(set(interests + infer_interests(text))),
        "dependent_tags": dependent_tags,
        "dependent_age_min": dependent_age_min,
        "dependent_age_max": dependent_age_max,
        "strict_eligibility_requested": strict_eligibility_requested,
        "missing_for_confidence": missing,
        "ready_for_strict_search": not missing,
        "follow_up_questions": follow_up_questions(missing),
    }


# 입력 문맥에서 청년/신혼부부/소상공인 등 우선 타겟을 추론한다.
def infer_target_type(
    text: str,
    interests: list[str],
    marital_status: str,
    business_type: str,
) -> str:
    haystack = " ".join([text, " ".join(interests), marital_status, business_type])
    scores = {
        target: sum(1 for keyword in keywords if keyword in haystack)
        for target, keywords in TARGET_KEYWORDS.items()
    }
    if max(scores.values()) <= 0:
        return "general"
    for target in TARGET_PRIORITY:
        if scores.get(target, 0) > 0:
            return target
    return max(scores, key=scores.get)


# 자연어에서 시/군/구 수준의 지역명을 추출한다.
def infer_region(text: str) -> str:
    sido, sigungu = infer_region_parts(text)
    if sido and sigungu:
        return f"{short_sido(sido)} {sigungu}"
    return sigungu or short_sido(sido)


def infer_region_parts(text: str) -> tuple[str, str]:
    sido = infer_sido(text)
    sigungu = infer_sigungu(text)
    if not sido and sigungu:
        sido = SIGUNGU_TO_SIDO.get(sigungu, "")
    return sido, sigungu


def infer_sido(text: str) -> str:
    for canonical, aliases in BROAD_REGION_ALIASES.items():
        for alias in sorted(aliases, key=len, reverse=True):
            if contains_region_alias(text, canonical, alias):
                return canonical
    return ""


def infer_sigungu(text: str) -> str:
    for district in SEOUL_DISTRICTS:
        base = district.removesuffix("구")
        if district in text or (len(base) >= 2 and re.search(rf"(?<![가-힣]){re.escape(base)}(?![가-힣])", text)):
            return district
    for match in extract_region_tokens(text):
        if match in KNOWN_SIGUNGU:
            return match
    return ""


def extract_region_tokens(text: str) -> list[str]:
    return re.findall(r"([가-힣]+(?:구|군|시))(?=$|[\s,.)\]]|에|에서|의)", text)


def contains_region_alias(text: str, canonical: str, alias: str) -> bool:
    if canonical == "광주광역시" and alias == "광주시":
        return False
    if len(alias) <= 2:
        return bool(re.search(rf"(?<![가-힣]){re.escape(alias)}(?![가-힣])", text))
    return bool(re.search(rf"(?<![가-힣]){re.escape(alias)}(?![가-힣])", text))


def short_sido(sido: str) -> str:
    return {
        "서울특별시": "서울",
        "부산광역시": "부산",
        "대구광역시": "대구",
        "인천광역시": "인천",
        "광주광역시": "광주",
        "대전광역시": "대전",
        "울산광역시": "울산",
        "세종특별자치시": "세종",
        "경기도": "경기",
        "강원특별자치도": "강원",
        "충청북도": "충북",
        "충청남도": "충남",
        "전북특별자치도": "전북",
        "전라남도": "전남",
        "경상북도": "경북",
        "경상남도": "경남",
        "제주특별자치도": "제주",
    }.get(sido, sido)


# 자연어에서 나이 표현을 숫자로 추출한다.
def infer_age(text: str) -> int | None:
    match = re.search(r"(?:만\s*)?(\d{1,3})\s*(?:살|세)", text)
    return int(match.group(1)) if match else None


def infer_strict_eligibility_requested(text: str) -> bool:
    return any(
        phrase in text
        for phrase in (
            "신청가능한 복지만",
            "신청 가능한 복지만",
            "받을 수 있는 것만",
            "받을수 있는 것만",
            "조건에 맞는 것만",
            "내가 가능한 것만",
            "나한테 맞는 것만",
        )
    )


def infer_audience_tags(text: str, target_type: str) -> list[str]:
    tags: list[str] = []
    tag_keywords = {
        "youth": ["청년", "취준", "취업준비"],
        "newlywed": ["신혼", "혼인"],
        "single_parent": ["한부모", "조손"],
        "senior": ["노인", "어르신", "고령", "독거노인", "홀몸"],
        "disabled": ["장애", "장애인"],
        "pregnant": ["임산부", "임신", "출산", "난임"],
        "student": ["대학생", "중학생", "고등학생", "초등학생", "학생", "등록금", "학자금"],
        "job_seeker": ["구직", "취업준비", "취준", "면접", "자격증", "일자리"],
        "one_person_household": ["1인", "혼자", "독거"],
        "no_home": ["무주택"],
    }
    dependent_tags = set(infer_dependent_tags(text))
    for tag, keywords in tag_keywords.items():
        if tag == "student" and dependent_tags and not has_user_student_context(text):
            continue
        if tag == target_type or any(keyword in text for keyword in keywords):
            tags.append(tag)
    return sorted(set(tags))


def infer_dependent_tags(text: str) -> list[str]:
    if re.search(r"(아직\s*)?(아이|자녀)(는|가)?\s*(없어|없음|없습니다|없다)", text):
        return []
    tags: list[str] = []
    if re.search(r"(초등학생|중학생|고등학생|학생)\s*(아이|자녀|아들|딸)", text):
        tags.append("student_child")
    if re.search(r"초등학생\s*(아이|자녀|아들|딸)", text):
        tags.append("elementary_student_child")
    if "아이" in text or "자녀" in text:
        tags.append("child")
    return sorted(set(tags))


def infer_dependent_age_range(dependent_tags: list[str]) -> tuple[int | None, int | None]:
    tag_set = set(dependent_tags)
    if "elementary_student_child" in tag_set:
        return 6, 12
    if "student_child" in tag_set:
        return 6, 18
    if "child" in tag_set:
        return 0, 18
    return None, None


def has_user_student_context(text: str) -> bool:
    return bool(re.search(r"(나는|제가|본인|현재)?\s*(대학생|중학생|고등학생|학생)이야", text)) or any(
        keyword in text for keyword in ("등록금", "학자금")
    )


# 자연어에서 1인 가구/신혼부부 같은 가구 형태를 추론한다.
def infer_household(text: str) -> str:
    if "1인" in text or "혼자" in text:
        return "1인 가구"
    if "신혼" in text or "부부" in text:
        return "신혼부부"
    return ""


# 자연어에서 취업준비/아르바이트/사업자 상태를 추론한다.
def infer_employment(text: str) -> str:
    if "취준" in text or "취업준비" in text:
        return "취업준비생"
    if "알바" in text:
        return "아르바이트"
    if "사업자" in text or "운영" in text:
        return "소상공인"
    return ""


# 자연어에서 월세/전세/자가 같은 주거 형태를 추론한다.
def infer_housing(text: str) -> str:
    if "월세" in text:
        return "월세"
    if "전세" in text:
        return "전세"
    if "자가" in text:
        return "자가"
    return ""


# 자연어 키워드를 주거/취업/육아/소상공인 관심사로 매핑한다.
def infer_interests(text: str) -> list[str]:
    found: list[str] = []
    mapping = {
        "주거": ["월세", "전세", "이사", "주거"],
        "취업": ["취업", "구직", "취준"],
        "출산/육아": ["출산", "육아", "난임", "보육", "아이"],
        "소상공인": ["소상공", "자영업", "사업자", "매출", "정책자금"],
    }
    for label, keywords in mapping.items():
        if any(keyword in text for keyword in keywords):
            found.append(label)
    return found


# 매칭 신뢰도를 높이기 위해 추가로 확인해야 할 필드를 계산한다.
def missing_fields(
    target_type: str,
    region: str,
    age: int | None,
    marital_status: str,
    business_type: str,
    *,
    strict: bool = False,
) -> list[str]:
    missing = []
    if not region:
        missing.append("거주지/사업장 지역")
    if strict and age is None:
        missing.append("만 나이")
    if strict and target_type == "newlywed" and not marital_status:
        missing.append("혼인 기간")
    if strict and target_type == "small_business" and not business_type:
        missing.append("업종/사업자 유형")
    return missing


def follow_up_questions(missing: list[str]) -> list[str]:
    templates = {
        "거주지/사업장 지역": "현재 거주지 또는 사업장 지역은 어디인가요? 예: 서울 관악구",
        "만 나이": "만 나이가 어떻게 되나요?",
        "혼인 기간": "혼인 기간 또는 혼인신고 여부를 알려주세요.",
        "업종/사업자 유형": "업종과 사업자 유형을 알려주세요.",
    }
    return [templates[field] for field in missing if field in templates]
