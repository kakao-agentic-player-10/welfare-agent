from __future__ import annotations

import re
from typing import Any, Callable

from welfare_agent.ingestion.codes import decode_youth
from welfare_agent.domain.regions import KNOWN_SIGUNGU


# 정규화된 지원사업 항목의 공통 필드.
NORMALIZED_FIELDS = (
    "id",
    "title",
    "summary",
    "target",
    "criteria",
    "content",
    "application_period",
    "business_period",
    "application_method",
    "organization",
    "contact",
    "url",
    "application_url",
    "extra_urls",
    "region_sido",
    "region_sigungu",
    "age_min",
    "age_max",
    "category",
)


# 응답 키의 대소문자가 소스마다 달라(lnLmt vs lnlmt) 소문자 인덱스로 매칭한다.
def pick(item: dict[str, Any], *names: str) -> str:
    lower_index = {str(key).lower(): value for key, value in item.items()}
    for name in names:
        value = item.get(name)
        if value in (None, ""):
            value = lower_index.get(name.lower())
        if value not in (None, "", [], {}):
            if isinstance(value, list):
                value = ", ".join(str(part) for part in value if part not in (None, ""))
            return str(value).strip()
    return ""


# 여러 필드를 구분자로 합쳐 표시/검색용 텍스트로 만든다.
def join_fields(item: dict[str, Any], *names: str, sep: str = " · ") -> str:
    parts = [pick(item, name) for name in names]
    return sep.join(part for part in parts if part)


# YYYYMMDD / YYYY-MM-DD 형태를 ISO(YYYY-MM-DD)로 정규화한다.
def to_iso_date(value: str) -> str:
    text = (value or "").strip()
    match = re.match(r"^(20\d{2})\D?(\d{2})\D?(\d{2})", text)
    if not match:
        return ""
    year, month, day = match.group(1), match.group(2), match.group(3)
    try:
        return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    except ValueError:
        return ""


# 서로 다른 OpenAPI 필드명을 내부 표준 지원사업 필드로 정규화한다.
def normalize_item(item: dict[str, Any], source: str = "") -> dict[str, Any]:
    base = {
        "id": pick(
            item, "serviceId", "svcId", "id", "service_id", "서비스ID", "servId",
            "plcyNo", "pblancId", "PAN_ID", "seq",
        ),
        "title": pick(
            item, "serviceName", "svcNm", "name", "title", "서비스명", "제목", "servNm",
            "plcyNm", "pblancNm", "finPrdNm", "상품명",
        ),
        "summary": pick(
            item, "summary", "servicePurpose", "svcPpo", "description", "서비스목적요약",
            "서비스목적", "요약", "servDgst", "plcyExplnCn", "wlfareInfoOutlCn", "bsnsSumryCn",
        ),
        "target": pick(
            item, "target", "supportTarget", "sprtTrgtCn", "지원대상", "대상",
            "trgterIndvdlArray", "trgterIndvdlNmArray", "trgetNm", "tgtrDtlCn",
            "suprTgtDtlCond", "trgt",
        ),
        "criteria": pick(
            item, "criteria", "selectionCriteria", "slctCritCn", "선정기준", "addAplyQlfcCndCn",
        ),
        "content": pick(
            item, "content", "supportContent", "sprtCn", "지원내용", "plcySprtCn",
            "alwServCn", "bsnsSumryCn", "SPL_XPC_AMT",
        ),
        "application_period": pick(
            item, "applicationPeriod", "aplyPrd", "신청기간", "신청기한", "aplyYmd",
            "reqstBeginEndDe", "reqstBeginEndDe",
        ),
        "business_period": "",
        "application_method": pick(
            item, "applicationMethod", "aplyMtd", "신청방법", "aplyMtdNm", "plcyAplyMthdCn",
            "jnMthd",
        ),
        "organization": pick(
            item, "organization", "department", "jurMnofNm", "소관기관명", "소관기관", "기관",
            "jurOrgNm", "bizChrDeptNm", "sprvsnInstCdNm", "operInstCdNm", "jrsdInsttNm",
            "suplyInsttNm", "ofrInstNm", "hdlInst",
        ),
        # inqNum은 '조회수'라 연락처 후보에서 제외한다(문의처는 rprsCtadr/refrnc 계열).
        "contact": pick(
            item, "contact", "phone", "문의처", "전화번호", "전화문의", "rprsCtadr",
            "refrnc", "refrncNm", "rfrcCnpl", "cnpl",
        ),
        "url": pick(
            item, "url", "detailUrl", "svcUrl", "상세URL", "상세조회URL", "링크", "servDtlLink",
            "aplyUrlAddr", "refUrlAddr1", "pblancUrl", "rceptEngnHmpgUrl", "rltSite",
        ),
        "application_url": pick(item, "applicationUrl", "온라인신청사이트URL", "aplyUrlAddr", "rceptEngnHmpgUrl"),
        "extra_urls": "",
        "region_sido": "",
        "region_sigungu": "",
        "age_min": "",
        "age_max": "",
        "category": pick(item, "서비스분야", "category"),
    }
    enricher = _ENRICHERS.get(source)
    if enricher:
        enricher(item, base)
    # 자유 텍스트 본문은 신청기간/사업기간/사용기간이 한 줄에 섞이는 경우가 많다.
    # 기간 컬럼은 신청 가능 여부에 직접 쓰이므로 구조화된 원본 필드만 승격한다.
    base["raw"] = item
    if source:
        base["source"] = source
    return base


def _enrich_youth(item: dict[str, Any], base: dict[str, Any]) -> None:
    base["age_min"] = _digits(pick(item, "sprtTrgtMinAge"))
    base["age_max"] = _digits(pick(item, "sprtTrgtMaxAge"))
    decoded = decode_youth(item)
    # 대상: 취업/특화 요건 코드를 디코딩(없으면 '청년').
    base["target"] = base["target"] or ", ".join(decoded["audience"]) or "청년"
    # 자격조건: 추가자격(자유텍스트) + 코드 디코딩 조건 + 참여제한.
    criteria_parts = []
    if pick(item, "addAplyQlfcCndCn"):
        criteria_parts.append(pick(item, "addAplyQlfcCndCn"))
    criteria_parts.extend(decoded["conditions"])
    if pick(item, "ptcpPrpTrgtCn"):
        criteria_parts.append(_restriction(pick(item, "ptcpPrpTrgtCn")))
    # 자유텍스트·코드 모두 제한이 없으면 '제한 없음'을 명시(빈칸 대신).
    criteria = " / ".join(part for part in criteria_parts if part)
    base["criteria"] = base["criteria"] or criteria or "연령·거주 요건 외 별도 추가 자격요건 없음(공고문 확인)"
    base["content"] = base["content"] or pick(item, "plcySprtCn")
    base["business_period"] = _date_range(
        to_iso_date(pick(item, "bizPrdBgngYmd")),
        to_iso_date(pick(item, "bizPrdEndYmd")),
    ) or pick(item, "bizPrdEtcCn")
    # 신청기간: aplyYmd 우선, 없으면 신청기간구분코드(상시/마감)로 보강.
    period = pick(item, "aplyYmd")
    if not period:
        period = "상시" if decoded["always_open"] else ("마감" if decoded["closed"] else "")
    base["application_period"] = base["application_period"] or period
    base["application_method"] = base["application_method"] or pick(item, "plcyAplyMthdCn")
    base["application_url"] = pick(item, "aplyUrlAddr") or base["application_url"]
    base["extra_urls"] = _join_unique_urls(pick(item, "refUrlAddr1"), pick(item, "refUrlAddr2"))
    # 지역: 기관명이 부처일 수 있어 법정동코드(zipCd)로 시도를 우선 보강한다.
    base["region_sido"] = (
        _sido_from_zip(pick(item, "zipCd"))
        or _sido_from_text(
            join_fields(item, "rgtrUpInstCdNm", "rgtrHghrkInstCdNm", "rgtrInstCdNm")
        )
    )
    base["region_sigungu"] = _sigungu_from_text(pick(item, "rgtrInstCdNm"))
    base["category"] = join_fields(item, "lclsfNm", "mclsfNm", "plcyKywdNm")
    base["url"] = pick(item, "aplyUrlAddr", "refUrlAddr1") or base["url"]


def _enrich_public_service(item: dict[str, Any], base: dict[str, Any]) -> None:
    base["age_min"] = base["age_min"] or _digits(pick(item, "JA0110"))
    base["age_max"] = base["age_max"] or _digits(pick(item, "JA0111"))
    base["application_url"] = pick(item, "온라인신청사이트URL") or base["application_url"]
    base["url"] = base["url"] or base["application_url"]


def _digits(value: str) -> str:
    match = re.search(r"\d{1,3}", value or "")
    return match.group(0) if match else ""


def _join_unique_text(*values: str, sep: str = " · ") -> str:
    seen = set()
    parts = []
    for value in values:
        text = (value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        parts.append(text)
    return sep.join(parts)


def _join_unique_urls(*values: str) -> str:
    return _join_unique_text(*values, sep="\n")


def _date_range(start: str, end: str) -> str:
    if start and end:
        return f"{start} ~ {end}"
    return start or end


# 지역 필드에 기관/부서명이 섞이는 것을 막는다. 광역은 표준 시도명만 인정한다.
def _sido_from_text(value: str) -> str:
    text = (value or "").strip()
    if not text or text in ("-", "없음", "해당없음", "전국"):
        return ""
    for sido in sorted(set(_SIDO_CODE.values()), key=len, reverse=True):
        if sido in text:
            return sido
    return ""


# 지역 필드에 기관/부서명이 섞이는 것을 막는다. 시군구는 사전의 독립 토큰만 인정한다.
def _sigungu_from_text(value: str) -> str:
    text = (value or "").strip()
    if not text or text in ("-", "없음", "해당없음", "전국"):
        return ""
    candidates = re.findall(r"([가-힣]+(?:구|군|시))(?![가-힣])", text)
    for candidate in candidates:
        if candidate in KNOWN_SIGUNGU:
            return candidate
    return ""


# 법정동코드 앞 2자리 → 시도명.
_SIDO_CODE = {
    "11": "서울특별시", "26": "부산광역시", "27": "대구광역시", "28": "인천광역시",
    "29": "광주광역시", "30": "대전광역시", "31": "울산광역시", "36": "세종특별자치시",
    "41": "경기도", "42": "강원도", "51": "강원특별자치도", "43": "충청북도",
    "44": "충청남도", "45": "전라북도", "52": "전북특별자치도", "46": "전라남도",
    "47": "경상북도", "48": "경상남도", "50": "제주특별자치도",
}


# 청년정책 zipCd(법정시군구코드 목록)에서 시도를 추론한다. 여러 시도면 비워 둔다(전국성).
def _sido_from_zip(value: str) -> str:
    codes = [token.strip() for token in (value or "").replace(" ", "").split(",") if token.strip()]
    sidos = {_SIDO_CODE.get(code[:2]) for code in codes if len(code) >= 2}
    sidos.discard(None)
    return next(iter(sidos)) if len(sidos) == 1 else ""


# 참여제한대상 텍스트를 자격 설명용으로 다듬는다.
def _restriction(value: str) -> str:
    text = (value or "").strip()
    return f"참여제한: {text}" if text else ""


_ENRICHERS: dict[str, Callable[[dict[str, Any], dict[str, Any]], None]] = {
    "youth_policy": _enrich_youth,
    "public_service_benefits": _enrich_public_service,
}


# source/id/title 조합으로 중복 지원사업을 제거한다.
def dedupe_items(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    deduped = []
    for item in items:
        key = (item.get("source", ""), item.get("id", ""), item.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)
    return deduped
