from __future__ import annotations

import re
from typing import Any

from welfare_agent.domain.regions import KNOWN_SIGUNGU

SEOUL_DISTRICTS = {
    "강남구", "강동구", "강북구", "강서구", "관악구", "광진구", "구로구", "금천구",
    "노원구", "도봉구", "동대문구", "동작구", "마포구", "서대문구", "서초구", "성동구",
    "성북구", "송파구", "양천구", "영등포구", "용산구", "은평구", "종로구", "중구", "중랑구",
}

BROAD_REGION_ALIASES = {
    "서울": ("서울", "서울시", "서울특별시"),
    "부산": ("부산", "부산시", "부산광역시"),
    "대구": ("대구", "대구시", "대구광역시"),
    "인천": ("인천", "인천시", "인천광역시"),
    "광주": ("광주", "광주시", "광주광역시"),
    "대전": ("대전", "대전시", "대전광역시"),
    "울산": ("울산", "울산시", "울산광역시"),
    "세종": ("세종", "세종시", "세종특별자치시"),
    "경기": ("경기", "경기도"),
    "강원": ("강원", "강원도", "강원특별자치도"),
    "충북": ("충북", "충청북도"),
    "충남": ("충남", "충청남도"),
    "전북": ("전북", "전라북도", "전북특별자치도"),
    "전남": ("전남", "전라남도"),
    "경북": ("경북", "경상북도"),
    "경남": ("경남", "경상남도"),
    "제주": ("제주", "제주도", "제주특별자치도"),
}

SIGUNGU_TO_BROAD_REGION = {
    **{district: "서울" for district in SEOUL_DISTRICTS},
    "해운대구": "부산",
    "달서구": "대구",
    "남동구": "인천",
    "유성구": "대전",
    "수원시": "경기",
    "원주시": "강원",
    "제주시": "제주",
}
AMBIGUOUS_SIGUNGU_NAMES = {"광주시"}

ZIP_PREFIX_TO_BROAD_REGION = {
    "11": "서울",
    "26": "부산",
    "27": "대구",
    "28": "인천",
    "29": "광주",
    "30": "대전",
    "31": "울산",
    "36": "세종",
    "41": "경기",
    "42": "강원",
    "51": "강원",
    "43": "충북",
    "44": "충남",
    "45": "전북",
    "52": "전북",
    "46": "전남",
    "47": "경북",
    "48": "경남",
    "50": "제주",
}

ZIP_CODE_TO_LOCAL_REGION = {
    "11110": "종로구",
    "11140": "중구",
    "11170": "용산구",
    "11200": "성동구",
    "11215": "광진구",
    "11230": "동대문구",
    "11260": "중랑구",
    "11290": "성북구",
    "11305": "강북구",
    "11320": "도봉구",
    "11350": "노원구",
    "11380": "은평구",
    "11410": "서대문구",
    "11440": "마포구",
    "11470": "양천구",
    "11500": "강서구",
    "11530": "구로구",
    "11545": "금천구",
    "11560": "영등포구",
    "11590": "동작구",
    "11620": "관악구",
    "11650": "서초구",
    "11680": "강남구",
    "11710": "송파구",
    "11740": "강동구",
}

NATIONAL_ORGANIZATION_TERMS = (
    "중앙부처",
    "국무조정실",
    "기획재정부",
    "교육부",
    "과학기술정보통신부",
    "외교부",
    "통일부",
    "법무부",
    "국방부",
    "행정안전부",
    "문화체육관광부",
    "농림축산식품부",
    "산업통상자원부",
    "보건복지부",
    "환경부",
    "고용노동부",
    "여성가족부",
    "성평등가족부",
    "국토교통부",
    "해양수산부",
    "중소벤처기업부",
    "기후에너지환경부",
    "식품의약품안전처",
    "국세청",
    "관세청",
    "조달청",
    "통계청",
    "병무청",
    "방위사업청",
    "경찰청",
    "소방청",
    "문화재청",
    "농촌진흥청",
    "산림청",
    "특허청",
    "질병관리청",
    "기상청",
    "개인정보보호위원회",
    "공정거래위원회",
    "금융위원회",
    "국민권익위원회",
    "방송통신위원회",
    "국가보훈부",
    "서민금융진흥원",
    "소상공인시장진흥공단",
    "중소벤처기업진흥공단",
    "근로복지공단",
    "국민건강보험공단",
    "국민연금공단",
    "한국장학재단",
    "한국토지주택공사",
    "한국주택금융공사",
    "국방전직교육원",
)

NATIONAL_ORGANIZATION_TYPES = {"중앙행정기관"}
LOCAL_ORGANIZATION_TYPES = {"지방자치단체"}

# 키워드 가산 점수에 쓰는 조건/관심사 키워드.
MATCH_KEYWORDS = [
    "청년", "월세", "주거", "취업", "취업준비", "구직", "신혼", "전세",
    "출산", "육아", "소상공인", "정책자금", "매출", "창업", "임대", "한부모",
    "장애인", "임산부", "노인", "독거", "무주택",
]

# 점수 가중치.
_W_SEMANTIC = 50
_W_REGION = 22
_W_REGION_PENALTY = -35
_W_AGE = 16
_W_AGE_PENALTY = -45
_W_TARGET = 12
_W_INTEREST = 8
_W_KEYWORD = 3
_W_AUDIENCE_TAG = 14


# 프로필과 사용자 키워드로 검색 쿼리를 만든다(임베딩 입력).
def benefit_search_keyword(profile: dict[str, Any], keyword: str = "") -> str:
    if keyword:
        return keyword
    target = profile.get("target_type", "general")
    parts = [
        profile.get("region", ""),
        target_type_label(target),
        profile.get("household_type", ""),
        profile.get("housing_type", ""),
        profile.get("employment_status", ""),
        profile.get("marital_status", ""),
        profile.get("business_type", ""),
        " ".join(profile.get("interests", [])),
    ]
    if target == "newlywed" and not profile.get("interests"):
        parts.extend(["주거", "출산"])
    if target == "small_business" and not profile.get("interests"):
        parts.extend(["정책자금", "경영안정"])
    parts.append("지원")
    return " ".join(str(part).strip() for part in parts if str(part).strip())


# 사용자 프로필과 후보를 비교해 가능성 점수 순으로 정렬한다.
def match_benefits(profile: dict[str, Any], benefits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    profile_text = _profile_text(profile)
    profile_region_set = set(profile_regions(profile_text))
    matched = []
    for benefit in filter_target_applicable(
        profile,
        filter_age_applicable(profile, filter_region_applicable(profile, benefits)),
    ):
        score, reasons = score_benefit(
            profile, benefit, profile_text=profile_text, profile_region_set=profile_region_set
        )
        matched.append(
            {
                "benefit": benefit,
                "likelihood": likelihood_label(score),
                "score": score,
                "matched_reasons": reasons,
            }
        )
    return sorted(matched, key=lambda item: item["score"], reverse=True)


# 한 후보의 가능성 점수와 근거를 만든다(벡터 유사도 + 구조 신호).
def score_benefit(
    profile: dict[str, Any],
    benefit: dict[str, Any],
    *,
    profile_text: str | None = None,
    profile_region_set: set[str] | None = None,
) -> tuple[int, list[str]]:
    profile_text = profile_text if profile_text is not None else _profile_text(profile)
    profile_region_set = (
        profile_region_set if profile_region_set is not None else set(profile_regions(profile_text))
    )
    benefit_text = _benefit_text(benefit)
    reasons: list[str] = []
    score = 0.0

    distance = benefit.get("vector_distance")
    if distance is not None:
        semantic = 1.0 / (1.0 + float(distance))
        score += semantic * _W_SEMANTIC
        if semantic >= 0.6:
            reasons.append("프로필과 의미적으로 매우 유사한 사업입니다.")

    score += _region_score(profile_region_set, benefit, reasons)
    score += _age_score(profile, benefit, reasons)
    score += _audience_tag_score(profile, benefit, benefit_text, reasons)

    target_label = target_type_label(profile.get("target_type", ""))
    if target_label and target_label in benefit_text:
        score += _W_TARGET
        reasons.append(f"'{target_label}' 대상 사업입니다.")

    interest_hits = [
        interest
        for interest in profile.get("interests", [])
        if interest and interest in benefit_text
    ]
    if interest_hits:
        score += _W_INTEREST * len(set(interest_hits))
        reasons.append(f"관심 분야({', '.join(sorted(set(interest_hits)))})와 연결됩니다.")

    keyword_hits = [kw for kw in MATCH_KEYWORDS if kw in profile_text and kw in benefit_text]
    if keyword_hits:
        score += _W_KEYWORD * len(keyword_hits)
        reasons.append(f"조건 키워드({', '.join(keyword_hits)})가 일치합니다.")

    if not reasons:
        reasons.append("직접 일치 조건이 적어 상세 자격 확인이 필요합니다.")
    return int(round(score)), reasons


def _region_score(
    profile_region_set: set[str],
    benefit: dict[str, Any],
    reasons: list[str],
) -> int:
    if not profile_region_set:
        return 0
    benefit_region_set = set(profile_regions(benefit_region_text(benefit)))
    if not benefit_region_set:
        return 0  # 전국/미상 → 지역 가점·감점 없이 중립
    if profile_region_set & benefit_region_set:
        matched = profile_region_set & benefit_region_set
        reasons.append(f"지역 조건({', '.join(sorted(matched))})이 일치합니다.")
        return _W_REGION
    profile_broad = {r for r in profile_region_set if is_broad_region(r)}
    benefit_broad = {r for r in benefit_region_set if is_broad_region(r)}
    if profile_broad and benefit_broad and profile_broad.isdisjoint(benefit_broad):
        reasons.append("다른 지역 전용 사업으로 보입니다(지역 확인 필요).")
        return _W_REGION_PENALTY
    return 0


def _age_score(profile: dict[str, Any], benefit: dict[str, Any], reasons: list[str]) -> int:
    age = profile.get("age")
    if not isinstance(age, int):
        return 0
    age_min = _to_int(benefit.get("age_min"))
    age_max = _to_int(benefit.get("age_max"))
    if age_min is None and age_max is None:
        return 0
    if dependent_age_applicable(profile, benefit, age_min=age_min, age_max=age_max):
        reasons.append("자녀 연령 조건이 대상 범위와 겹칩니다.")
        return _W_AGE
    if (age_min is not None and age < age_min) or (age_max is not None and age > age_max):
        lo = age_min if age_min is not None else "?"
        hi = age_max if age_max is not None else "?"
        reasons.append(f"연령 대상({lo}~{hi}세) 범위를 벗어납니다.")
        return _W_AGE_PENALTY
    reasons.append("연령 조건이 대상 범위에 포함됩니다.")
    return _W_AGE


def filter_region_applicable(
    profile: dict[str, Any], benefits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [benefit for benefit in benefits if is_region_applicable(profile, benefit)]


def filter_age_applicable(
    profile: dict[str, Any], benefits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [benefit for benefit in benefits if is_age_applicable(profile, benefit)]


def filter_target_applicable(
    profile: dict[str, Any], benefits: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    return [benefit for benefit in benefits if is_target_applicable(profile, benefit)]


def is_age_applicable(profile: dict[str, Any], benefit: dict[str, Any]) -> bool:
    age = profile.get("age")
    age_min = _to_int(benefit.get("age_min"))
    age_max = _to_int(benefit.get("age_max"))
    if age_min is None and age_max is None:
        return True
    if isinstance(age, int) and not _age_outside_range(age, age_min, age_max):
        return True
    if dependent_age_applicable(profile, benefit, age_min=age_min, age_max=age_max):
        return True
    if not isinstance(age, int):
        return True
    return False


def is_region_applicable(profile: dict[str, Any], benefit: dict[str, Any]) -> bool:
    return bool(region_scope_info(profile, benefit)["region_applicable"])


def is_target_applicable(profile: dict[str, Any], benefit: dict[str, Any]) -> bool:
    profile_tags = set(profile.get("audience_tags") or [])
    if profile.get("target_type"):
        profile_tags.add(str(profile["target_type"]))
    dependent_tags = set(profile.get("dependent_tags") or [])
    benefit_text = _exclusive_target_text(benefit)
    if profile_target_matches_benefit(profile_tags, benefit, benefit_text):
        return True
    exclusive_targets = {
        "youth": ("청년",),
        "disabled": ("장애인", "장애"),
        "pregnant": ("임산부", "임신", "난임"),
        "single_parent": ("한부모", "조손"),
        "senior": ("노인", "어르신", "고령", "홀몸"),
        "small_business": ("소상공인", "자영업자", "사업자"),
    }
    for tag, labels in exclusive_targets.items():
        if tag not in profile_tags and any(label in benefit_text for label in labels):
            return False

    if "student" not in profile_tags and not dependent_tags:
        if any(label in benefit_text for label in ("대학생", "초등학생", "중학생", "고등학생")):
            return False
    if "student" not in profile_tags and dependent_tags:
        if "대학생" in benefit_text and "college_student_child" not in dependent_tags:
            return False
    return True


def profile_target_matches_benefit(
    profile_tags: set[str],
    benefit: dict[str, Any],
    benefit_text: str,
) -> bool:
    for tag in profile_tags:
        label = audience_tag_label(tag)
        if label and (label in benefit_text or support_condition_flag(benefit, tag)):
            return True
    return False


def dependent_age_applicable(
    profile: dict[str, Any],
    benefit: dict[str, Any],
    *,
    age_min: int | None,
    age_max: int | None,
) -> bool:
    dependent_min = _to_int(profile.get("dependent_age_min"))
    dependent_max = _to_int(profile.get("dependent_age_max"))
    if dependent_min is None and dependent_max is None:
        return False
    if not is_dependent_target_benefit(benefit):
        return False
    return ranges_overlap(dependent_min, dependent_max, age_min, age_max)


def is_dependent_target_benefit(benefit: dict[str, Any]) -> bool:
    text = _exclusive_target_text(benefit)
    return any(
        keyword in text
        for keyword in ("아동", "자녀", "초등", "중등", "고등", "학생", "양육", "보육", "교육비", "학비", "장학")
    )


def ranges_overlap(
    left_min: int | None,
    left_max: int | None,
    right_min: int | None,
    right_max: int | None,
) -> bool:
    left_lo = left_min if left_min is not None else -10**9
    right_lo = right_min if right_min is not None else -10**9
    left_hi = left_max if left_max is not None else 10**9
    right_hi = right_max if right_max is not None else 10**9
    lo = max(left_lo, right_lo)
    hi = min(left_hi, right_hi)
    return lo <= hi


def _age_outside_range(age: int, age_min: int | None, age_max: int | None) -> bool:
    return (age_min is not None and age < age_min) or (age_max is not None and age > age_max)


def _exclusive_target_text(benefit: dict[str, Any]) -> str:
    return " ".join(
        str(benefit.get(key, ""))
        for key in ("title", "summary", "target", "category")
    )


def region_scope_info(profile: dict[str, Any], benefit: dict[str, Any]) -> dict[str, Any]:
    allowed_regions = set(profile_region_terms(profile))
    if not allowed_regions:
        return {
            "region_applicable": True,
            "region_scope": "unfiltered",
            "region_scope_reason": "프로필에 지역 정보가 없어 지역 필터를 적용하지 않았습니다.",
        }

    # 지역 토큰이 없으면 원본 zipCd나 중앙/전국 기관 근거가 있을 때만 통과시킨다.
    benefit_regions = set(profile_regions(benefit_region_text(benefit)))
    if not benefit_regions:
        return inferred_region_scope_info(profile, benefit)

    profile_broad_regions = {region for region in allowed_regions if is_broad_region(region)}
    benefit_broad_regions = {region for region in benefit_regions if is_broad_region(region)}
    profile_local_regions = {region for region in allowed_regions if is_local_region(region)}
    benefit_local_regions = {region for region in benefit_regions if is_local_region(region)}

    if profile_broad_regions and benefit_broad_regions and profile_broad_regions.isdisjoint(benefit_broad_regions):
        return {
            "region_applicable": False,
            "region_scope": "other_region",
            "region_scope_reason": region_reason(
                benefit,
                f"다른 광역 지역 전용 사업입니다: {', '.join(sorted(benefit_broad_regions))}",
            ),
        }
    if profile_local_regions and benefit_local_regions - profile_local_regions:
        return {
            "region_applicable": False,
            "region_scope": "other_region",
            "region_scope_reason": region_reason(
                benefit,
                f"다른 시군구 전용 사업입니다: {', '.join(sorted(benefit_local_regions))}",
            ),
        }
    if profile_local_regions & benefit_local_regions:
        matched = (profile_broad_regions & benefit_broad_regions) | (
            profile_local_regions & benefit_local_regions
        )
        return {
            "region_applicable": True,
            "region_scope": "specific_region",
            "region_scope_reason": region_reason(
                benefit,
                f"지역 조건({', '.join(sorted(matched))})이 일치합니다.",
            ),
        }
    if profile_broad_regions & benefit_broad_regions:
        matched = profile_broad_regions & benefit_broad_regions
        return {
            "region_applicable": True,
            "region_scope": "specific_region",
            "region_scope_reason": region_reason(
                benefit,
                f"지역 조건({', '.join(sorted(matched))})이 일치합니다.",
            ),
        }
    matched = allowed_regions & benefit_regions
    return {
        "region_applicable": bool(matched),
        "region_scope": "specific_region" if matched else "other_region",
        "region_scope_reason": region_reason(
            benefit,
            (
                f"지역 조건({', '.join(sorted(matched))})이 일치합니다."
                if matched
                else f"프로필 지역과 다른 지역 사업입니다: {', '.join(sorted(benefit_regions))}"
            ),
        ),
    }


def profile_region_terms(profile: dict[str, Any]) -> list[str]:
    regions: list[str] = []
    append_region_terms(regions, profile.get("region_sido", ""))
    append_region_terms(regions, profile.get("region_sigungu", ""))
    profile_text = " ".join(str(value) for value in [profile.get("text", ""), profile.get("region", "")])
    for region in profile_regions(profile_text):
        append_unique(regions, region)
    return regions


# 지역 판단은 신뢰도 높은 필드(제목·기관·구조화 지역)에서만 한다. 본문은 여러 지역을 인용해 노이즈가 크다.
def benefit_region_text(benefit: dict[str, Any]) -> str:
    return " ".join(
        str(benefit.get(key, ""))
        for key in ("title", "organization", "region_sido", "region_sigungu")
    )


def inferred_region_scope_info(profile: dict[str, Any], benefit: dict[str, Any]) -> dict[str, Any]:
    profile_broad_regions = {region for region in profile_region_terms(profile) if is_broad_region(region)}
    profile_local_regions = {region for region in profile_region_terms(profile) if is_local_region(region)}
    zip_broad_regions = broad_regions_from_zip(benefit)
    if zip_broad_regions:
        zip_local_regions = local_regions_from_zip(benefit)
        if profile_local_regions and zip_local_regions:
            local_matched = profile_local_regions & zip_local_regions
            if local_matched:
                return {
                    "region_applicable": True,
                    "region_scope": "zip_region",
                    "region_scope_reason": (
                        f"원본 법정동코드(zipCd)가 {', '.join(sorted(local_matched))} 지역을 포함합니다."
                    ),
                }
            return {
                "region_applicable": False,
                "region_scope": "other_region",
                "region_scope_reason": (
                    f"원본 법정동코드(zipCd)가 다른 시군구만 포함합니다: "
                    f"{', '.join(sorted(zip_local_regions))}"
                ),
            }
        matched = profile_broad_regions & zip_broad_regions
        if matched:
            return {
                "region_applicable": True,
                "region_scope": "zip_region",
                "region_scope_reason": f"원본 법정동코드(zipCd)가 {', '.join(sorted(matched))} 지역을 포함합니다.",
            }
        if profile_broad_regions:
            return {
                "region_applicable": False,
                "region_scope": "other_region",
                "region_scope_reason": (
                    f"원본 법정동코드(zipCd)가 다른 광역 지역만 포함합니다: "
                    f"{', '.join(sorted(zip_broad_regions))}"
                ),
            }
        return {
            "region_applicable": True,
            "region_scope": "zip_region",
            "region_scope_reason": "원본 법정동코드(zipCd)가 있으나 프로필 광역 지역을 추론하지 못해 통과시켰습니다.",
        }
    if has_national_organization(benefit):
        return {
            "region_applicable": True,
            "region_scope": "national",
            "region_scope_reason": "중앙부처/전국기관 사업으로 판단했습니다.",
        }
    return {
        "region_applicable": False,
        "region_scope": "unknown",
        "region_scope_reason": "지역 범위를 확인할 근거가 없어 제외했습니다.",
    }


def broad_regions_from_zip(benefit: dict[str, Any]) -> set[str]:
    raw = benefit.get("raw") if isinstance(benefit.get("raw"), dict) else {}
    zip_codes = str(raw.get("zipCd") or "").replace(" ", "").split(",")
    return {
        ZIP_PREFIX_TO_BROAD_REGION[code[:2]]
        for code in zip_codes
        if len(code) >= 2 and code[:2] in ZIP_PREFIX_TO_BROAD_REGION
    }


def local_regions_from_zip(benefit: dict[str, Any]) -> set[str]:
    raw = benefit.get("raw") if isinstance(benefit.get("raw"), dict) else {}
    zip_codes = str(raw.get("zipCd") or "").replace(" ", "").split(",")
    return {
        ZIP_CODE_TO_LOCAL_REGION[code[:5]]
        for code in zip_codes
        if len(code) >= 5 and code[:5] in ZIP_CODE_TO_LOCAL_REGION
    }


def has_national_organization(benefit: dict[str, Any]) -> bool:
    if organization_type(benefit) in NATIONAL_ORGANIZATION_TYPES:
        return True
    text = " ".join(
        str(benefit.get(key, ""))
        for key in ("organization", "title", "source")
    )
    if any(term in text for term in NATIONAL_ORGANIZATION_TERMS):
        return True
    return False


def organization_type(benefit: dict[str, Any]) -> str:
    raw = benefit.get("raw") if isinstance(benefit.get("raw"), dict) else {}
    return str(raw.get("소관기관유형") or "").strip()


def region_reason(benefit: dict[str, Any], reason: str) -> str:
    org_type = organization_type(benefit)
    if org_type in LOCAL_ORGANIZATION_TYPES:
        return f"{reason} 소관기관유형이 지방자치단체입니다."
    return reason


def is_local_region(region: str) -> bool:
    return region.endswith(("구", "군", "시")) and not is_broad_region(region)


def is_broad_region(region: str) -> bool:
    return region in BROAD_REGION_ALIASES


def profile_regions(profile_text: str) -> list[str]:
    regions: list[str] = []
    for canonical, aliases in BROAD_REGION_ALIASES.items():
        if any(contains_region_alias(profile_text, canonical, alias) for alias in aliases):
            append_unique(regions, canonical)
    for district in SEOUL_DISTRICTS:
        district_base = district.removesuffix("구")
        if district in profile_text or (len(district_base) >= 2 and district_base in profile_text):
            if "서울" in regions or not any(is_broad_region(region) for region in regions):
                append_unique(regions, "서울")
            append_unique(regions, district)
    for region in extract_region_tokens(profile_text):
        canonical = canonical_region(region)
        # 사전(시군구) 또는 표준 시도만 인정 → '도시/응시/체육시/인구/가구' 같은 가짜 토큰 차단.
        if canonical in BROAD_REGION_ALIASES or canonical in KNOWN_SIGUNGU:
            broad = SIGUNGU_TO_BROAD_REGION.get(canonical)
            if broad and not any(is_broad_region(item) for item in regions):
                append_unique(regions, broad)
            append_unique(regions, canonical)
    return regions


def append_region_terms(regions: list[str], value: Any) -> None:
    for region in profile_regions(str(value or "")):
        append_unique(regions, region)


def extract_region_tokens(text: str) -> list[str]:
    return re.findall(r"([가-힣]+(?:구|군|시|도))(?=$|[\s,.)\]]|에|에서|의)", text)


def contains_region_alias(text: str, canonical: str, alias: str) -> bool:
    if not text:
        return False
    if canonical == "광주" and alias == "광주시":
        if "경기도 광주시" in text:
            return False
        if "광주시청" in text:
            return True
        return bool(re.search(r"(?<![가-힣])광주시(?![가-힣])", text))
    if len(alias) <= 2:
        return bool(re.search(rf"(?<![가-힣]){re.escape(alias)}(?![가-힣])", text))
    return bool(re.search(rf"(?<![가-힣]){re.escape(alias)}(?![가-힣])", text))


def canonical_region(region: str) -> str:
    region = region.strip()
    if region in AMBIGUOUS_SIGUNGU_NAMES:
        return region
    for canonical, aliases in BROAD_REGION_ALIASES.items():
        if region in aliases:
            return canonical
    if region in SEOUL_DISTRICTS:
        return region
    seoul_district = f"{region}구"
    if seoul_district in SEOUL_DISTRICTS:
        return seoul_district
    return region


def append_unique(items: list[str], item: str) -> None:
    if item and item not in items:
        items.append(item)


def target_type_label(target_type: str) -> str:
    return {
        "youth": "청년",
        "newlywed": "신혼부부",
        "single_parent": "한부모",
        "senior": "노인",
        "disabled": "장애인",
        "pregnant": "임산부",
        "student": "학생",
        "job_seeker": "구직자",
        "one_person_household": "1인가구",
        "small_business": "소상공인",
        "general": "",
    }.get(target_type, "")


def _audience_tag_score(
    profile: dict[str, Any],
    benefit: dict[str, Any],
    benefit_text: str,
    reasons: list[str],
) -> int:
    profile_tags = set(profile.get("audience_tags") or [])
    if not profile_tags:
        return 0

    matched_labels: list[str] = []
    for tag in profile_tags:
        label = audience_tag_label(tag)
        if not label:
            continue
        if label in benefit_text or support_condition_flag(benefit, tag):
            matched_labels.append(label)

    if not matched_labels:
        return 0
    labels = sorted(set(matched_labels))
    reasons.append(f"대상 조건({', '.join(labels)})과 연결됩니다.")
    return _W_AUDIENCE_TAG * len(labels)


def audience_tag_label(tag: str) -> str:
    return {
        "youth": "청년",
        "newlywed": "신혼",
        "single_parent": "한부모",
        "senior": "노인",
        "disabled": "장애인",
        "pregnant": "임산부",
        "student": "학생",
        "job_seeker": "구직자",
        "one_person_household": "1인가구",
        "no_home": "무주택",
    }.get(tag, "")


def support_condition_flag(benefit: dict[str, Any], tag: str) -> bool:
    flags = benefit.get("condition_flags")
    flag_map = {
        "pregnant": ("pregnant",),
        "disabled": ("disabled",),
        "single_parent": ("single_parent",),
        "one_person_household": ("one_person_household",),
        "no_home": ("no_home",),
        "job_seeker": ("job_seeker",),
        "student": ("student",),
    }
    if isinstance(flags, dict) and tag in flag_map:
        return any(bool(flags.get(flag)) for flag in flag_map[tag])

    raw = benefit.get("raw") if isinstance(benefit.get("raw"), dict) else {}
    conditions = raw.get("supportConditions") if isinstance(raw.get("supportConditions"), dict) else raw
    code_map = {
        "pregnant": ("JA0302", "JA0303"),
        "disabled": ("JA0328",),
        "single_parent": ("JA0403",),
        "one_person_household": ("JA0404",),
        "no_home": ("JA0412",),
        "job_seeker": ("JA0327",),
        "student": ("JA0317", "JA0318", "JA0319", "JA0320"),
    }
    return any(_truthy_flag(conditions.get(code)) for code in code_map.get(tag, ()))


def _truthy_flag(value: Any) -> bool:
    text = str(value or "").strip().lower()
    return bool(text and text not in {"n", "no", "false", "0", "해당없음", "없음", "-"})


# 점수를 사용자에게 보여줄 가능성 라벨로 변환한다.
def likelihood_label(score: int) -> str:
    if score >= 55:
        return "가능성 높음"
    if score >= 28:
        return "확인 필요"
    return "가능성 낮음"


def _profile_text(profile: dict[str, Any]) -> str:
    return " ".join(
        str(value)
        for value in [
            profile.get("text", ""),
            profile.get("region", ""),
            profile.get("target_type", ""),
            target_type_label(profile.get("target_type", "")),
            profile.get("household_type", ""),
            profile.get("employment_status", ""),
            profile.get("housing_type", ""),
            profile.get("marital_status", ""),
            profile.get("business_type", ""),
            " ".join(profile.get("interests", [])),
        ]
    )


def _benefit_text(benefit: dict[str, Any]) -> str:
    return " ".join(
        str(benefit.get(key, ""))
        for key in (
            "title", "summary", "target", "criteria", "content",
            "category", "region_sido", "region_sigungu", "organization",
        )
    )


def _to_int(value: Any) -> int | None:
    try:
        text = str(value).strip()
        return int(text) if text else None
    except (TypeError, ValueError):
        return None
