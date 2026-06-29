from __future__ import annotations

from typing import Any

import httpx

from welfare_agent.errors import ExternalApiError


class KakaoLocalClient:
    # Kakao Local API 호출에 사용할 REST API 키를 보관한다.
    def __init__(self, rest_api_key: str):
        self.rest_api_key = rest_api_key

    # 키워드로 가까운 주민센터/구청/고용센터 등 장소를 검색한다.
    def keyword_search(self, query: str, x: str = "", y: str = "", radius: int = 20000) -> dict[str, Any]:
        if not self.rest_api_key:
            return {
                "ok": False,
                "configuration_required": ["KAKAO_REST_API_KEY"],
                "message": "Kakao Local API REST 키가 필요합니다.",
                "places": [],
            }

        params: dict[str, Any] = {"query": query, "size": 5}
        if x and y:
            params.update({"x": x, "y": y, "radius": radius})

        try:
            response = httpx.get(
                "https://dapi.kakao.com/v2/local/search/keyword.json",
                params=params,
                headers={"Authorization": f"KakaoAK {self.rest_api_key}"},
                timeout=10,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalApiError(f"Kakao Local API 호출 실패: {exc}") from exc

        payload = response.json()
        places = [
            {
                "name": item.get("place_name", ""),
                "category": item.get("category_name", ""),
                "address": item.get("road_address_name") or item.get("address_name", ""),
                "phone": item.get("phone", ""),
                "url": item.get("place_url", ""),
                "x": item.get("x", ""),
                "y": item.get("y", ""),
            }
            for item in payload.get("documents", [])
        ]
        return {"ok": True, "places": places}
