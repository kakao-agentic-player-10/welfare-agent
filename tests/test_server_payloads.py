import json

from welfare_agent.server import (
    CONTENT_LIMIT,
    CRITERIA_LIMIT,
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
