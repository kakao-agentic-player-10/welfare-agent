from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from welfare_agent.errors import ExternalApiError
from welfare_agent.ingestion.http import extract_items, parse_response_payload
from welfare_agent.ingestion.normalize import dedupe_items, normalize_item


@dataclass(frozen=True)
class SourceConfig:
    name: str
    api_url: str
    api_key: str
    api_key_param: str = "serviceKey"
    page_style: str = "standard"
    extra_params: dict[str, Any] = field(default_factory=dict)

    @property
    # API endpoint와 key가 모두 준비됐는지 확인한다.
    def ready(self) -> bool:
        return bool(self.api_url and self.api_key)


class PublicServiceClient:
    # 검색 대상 OpenAPI 설정들을 보관한다.
    def __init__(self, configs: list[SourceConfig]):
        self.configs = configs

    # 준비된 여러 공공 API를 검색하고 결과를 병합한다.
    def search(self, *, keyword: str = "", page: int = 1, size: int = 10) -> dict[str, Any]:
        ready_configs = [config for config in self.configs if config.ready]
        if not ready_configs:
            return {
                "ok": False,
                "configuration_required": ["DATA_GO_KR_SERVICE_KEY", "*_API_URL"],
                "message": "data.go.kr 서비스키와 최소 1개 이상의 OpenAPI 요청주소가 필요합니다.",
                "items": [],
            }

        results: list[dict[str, Any]] = []
        errors: list[dict[str, str]] = []
        for config in ready_configs:
            try:
                results.extend(self._search_one(config, keyword=keyword, page=page, size=size))
            except ExternalApiError as exc:
                errors.append({"source": config.name, "error": str(exc)})

        return {
            "ok": bool(results) or not errors,
            "items": dedupe_items(results)[:size],
            "raw_count": len(results),
            "sources": [config.name for config in ready_configs],
            "errors": errors,
        }

    # 단일 공공 API endpoint를 호출하고 응답 항목을 표준 형태로 바꾼다.
    def _search_one(
        self, config: SourceConfig, *, keyword: str = "", page: int = 1, size: int = 10
    ) -> list[dict[str, Any]]:
        params = pagination_params(config, page, size)
        params[config.api_key_param] = config.api_key
        params.update(config.extra_params)
        if keyword:
            params.update(_keyword_params(keyword))

        payload = self._request(config.api_url, params)
        items = []
        for raw in extract_items(payload):
            normalized = normalize_item(raw, config.name)
            if not normalized["title"] and not normalized["summary"]:
                continue
            items.append(normalized)
        return items

    def _request(self, url: str, params: dict[str, Any]) -> Any:
        try:
            response = httpx.get(url, params=params, timeout=10)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalApiError(f"OpenAPI 호출 실패: {exc}") from exc
        return parse_response_payload(response)


# API 유형별 페이지네이션 파라미터명을 맞춘다.
def pagination_params(config: SourceConfig, page: int, size: int) -> dict[str, Any]:
    if config.page_style == "odcloud":
        return {"page": page, "perPage": size, "returnType": "JSON"}
    if config.page_style == "youth":
        return {"pageNum": page, "pageSize": size, "rtnType": "json"}
    return {"pageNo": page, "numOfRows": size}


def _keyword_params(keyword: str) -> dict[str, Any]:
    return {
        "keyword": keyword,
        "searchWrd": keyword,
        "cond[서비스명::LIKE]": keyword,
        "plcyNm": keyword,
    }
