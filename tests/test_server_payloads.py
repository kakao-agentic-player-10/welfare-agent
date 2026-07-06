import json

from welfare_agent.server import (
    build_benefit_comparison,
    CONTENT_LIMIT,
    CRITERIA_LIMIT,
    MAX_COMPARE_BENEFITS,
    MAX_MATCH_REASONS,
    MAX_SEARCH_RESPONSE_ITEMS,
    SUMMARY_LIMIT,
    TARGET_LIMIT,
    to_search_item,
)


def test_to_search_item_keeps_playmcp_payload_compact():
    verbose_item = {
        "id": 1,
        "source": "test",
        "external_id": "benefit-1",
        "title": "청년 취업 지원",
        "summary": "요약" * 300,
        "target": "대상" * 300,
        "criteria": "기준" * 300,
        "content": "본문" * 400,
        "period_reason": "긴 기간 판정 설명" * 100,
        "extra_urls": "https://example.test/extra",
        "matched_reasons": [
            "프로필과 의미적으로 매우 유사한 사업입니다." * 10,
            "지역 조건이 일치합니다.",
            "연령 조건이 대상 범위에 포함됩니다.",
            "이 사유는 응답 크기를 줄이기 위해 제외됩니다.",
        ],
        "vector_distance": 0.123456789,
    }

    compact = to_search_item(verbose_item)

    assert len(compact["summary"]) <= SUMMARY_LIMIT
    assert len(compact["target"]) <= TARGET_LIMIT
    assert len(compact["criteria"]) <= CRITERIA_LIMIT
    assert len(compact["content"]) <= CONTENT_LIMIT
    assert len(compact["matched_reasons"]) == MAX_MATCH_REASONS
    assert compact["vector_distance"] == 0.1235
    assert "period_reason" not in compact
    assert "extra_urls" not in compact


def test_search_items_stay_under_playmcp_content_size():
    verbose_item = {
        "id": 1,
        "source": "test",
        "external_id": "benefit-1",
        "title": "청년 취업 지원",
        "summary": "요약" * 300,
        "target": "대상" * 300,
        "criteria": "기준" * 300,
        "content": "본문" * 400,
        "application_method": "신청 방법" * 200,
        "contact": "문의처" * 100,
        "matched_reasons": ["일치 사유" * 50] * 5,
    }
    payload = {
        "ok": True,
        "query": "청년 취업",
        "items": [to_search_item(verbose_item) for _ in range(MAX_SEARCH_RESPONSE_ITEMS)],
    }

    encoded = json.dumps(payload, ensure_ascii=False)

    assert len(encoded.encode()) < 12_000


def test_build_benefit_comparison_accepts_match_items():
    profile = {
        "age": 28,
        "region": "서울",
        "employment_status": "취업준비생",
        "interests": ["청년", "취업"],
    }
    match_item = {
        "likelihood": "가능성 높음",
        "match_score": 88,
        "matched_reasons": ["연령 조건이 대상 범위에 포함됩니다.", "지역 조건(서울)이 일치합니다."],
        "benefit": {
            "title": "청년 취업준비 비용 지원사업",
            "summary": "1인당 최대 10만원 지원",
            "target": "서울 거주 19~39세 미취업 청년",
            "application_period": "2026.02.02~2026.12.11",
            "application_method": "온라인 신청",
            "organization": "마포구",
            "url": "https://www.gov.kr/portal/rcvfvrSvc/dtlEx/313000000127",
            "region_sido": "서울",
            "region_sigungu": "마포구",
            "age_min": 19,
            "age_max": 39,
        },
    }

    result = build_benefit_comparison(profile=profile, benefits=[match_item], focus="취업")

    assert result["ok"] is True
    assert result["compared_count"] == 1
    row = result["comparison"][0]
    assert row["title"] == "청년 취업준비 비용 지원사업"
    assert row["region"] == "서울 마포구"
    assert row["age"] == "19~39세"
    assert row["official_link"].startswith("https://www.gov.kr/")
    assert row["fit"]["likelihood"] == "가능성 높음"
    assert row["fit"]["match_score"] == 88


def test_compare_payload_stays_compact():
    verbose_benefit = {
        "title": "청년 지원 사업" * 20,
        "summary": "요약" * 500,
        "target": "대상" * 500,
        "criteria": "기준" * 500,
        "content": "본문" * 500,
        "application_method": "신청 방법" * 300,
        "contact": "문의처" * 100,
        "url": "https://example.test/benefit",
        "matched_reasons": ["일치 사유" * 100] * 4,
    }
    result = build_benefit_comparison(
        profile={"age": 28, "region": "서울"},
        benefits=[verbose_benefit for _ in range(MAX_COMPARE_BENEFITS)],
    )

    encoded = json.dumps(result, ensure_ascii=False)

    assert len(encoded.encode()) < 12_000
