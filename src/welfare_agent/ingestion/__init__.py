from __future__ import annotations

from typing import Any

from welfare_agent.ingestion.client import (
    PublicServiceClient,
    SourceConfig,
    pagination_params,
)
from welfare_agent.ingestion.http import extract_items, xml_to_dict
from welfare_agent.ingestion.normalize import normalize_item


# settings로부터 동기화/검색 대상 OpenAPI 소스 설정들을 만든다.
def build_sources(settings: Any) -> list[SourceConfig]:
    key = settings.data_go_kr_service_key
    return [
        SourceConfig(
            "public_service_benefits",
            settings.public_service_api_url,
            key,
            page_style="odcloud",
        ),
        SourceConfig(
            "youth_policy",
            settings.youth_policy_api_url,
            settings.youth_policy_api_key,
            "apiKeyNm",
            page_style="youth",
        ),
    ]


__all__ = [
    "PublicServiceClient",
    "build_sources",
    "extract_items",
    "normalize_item",
    "pagination_params",
    "xml_to_dict",
]
