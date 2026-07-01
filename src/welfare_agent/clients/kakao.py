from __future__ import annotations

from typing import Any

import httpx

from welfare_agent.errors import ExternalApiError


DEFAULT_PLACE_LIMIT = 3
VISIT_OFFICE_GUIDANCE = (
    "방문 신청은 보통 주민등록상 주소지 관할 동주민센터/행정복지센터에서 진행합니다. "
    "아래 장소가 본인 주소지 관할 센터인지 방문 전 전화로 확인하세요."
)
VISIT_OFFICE_DISPLAY_POLICY = "사용자에게는 지역별로 가까운 후보 1~2곳만 간단히 보여주세요."


class KakaoLocalClient:
    # Kakao Local API 호출에 사용할 REST API 키를 보관한다.
    def __init__(
        self,
        rest_api_key: str,
        *,
        proxy_url: str = "",
        proxy_token: str = "",
        proxy_timeout_seconds: float = 10,
    ):
        self.rest_api_key = rest_api_key
        self.proxy_url = proxy_url
        self.proxy_token = proxy_token
        self.proxy_timeout_seconds = proxy_timeout_seconds

    # 키워드로 가까운 주민센터/구청/고용센터 등 장소를 검색한다.
    def keyword_search(self, query: str, x: str = "", y: str = "", radius: int = 20000) -> dict[str, Any]:
        if self.proxy_url:
            return self._keyword_search_via_proxy(query=query, x=x, y=y, radius=radius)

        if not self.rest_api_key:
            return {
                "ok": False,
                "configuration_required": ["KAKAO_REST_API_KEY", "KAKAO_LOCAL_PROXY_URL"],
                "message": "Kakao Local API REST 키 또는 Kakao Local 프록시 URL이 필요합니다.",
                "places": [],
            }

        params: dict[str, Any] = {"query": query, "size": DEFAULT_PLACE_LIMIT}
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
        return visit_office_response(places)

    def _keyword_search_via_proxy(
        self,
        *,
        query: str,
        x: str = "",
        y: str = "",
        radius: int = 20000,
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {"query": query, "size": DEFAULT_PLACE_LIMIT}
        if x and y:
            payload.update({"x": x, "y": y, "radius": radius})

        headers = {}
        if self.proxy_token:
            headers["Authorization"] = f"Bearer {self.proxy_token}"

        try:
            response = httpx.post(
                self.proxy_url,
                json=payload,
                headers=headers,
                timeout=self.proxy_timeout_seconds,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ExternalApiError(f"Kakao Local 프록시 호출 실패: {exc}") from exc

        result = response.json()
        places = result.get("places", [])
        if not isinstance(places, list):
            places = []
        return visit_office_response(places, ok=bool(result.get("ok", True)), source="proxy")


def visit_office_response(
    places: list[dict[str, Any]],
    *,
    ok: bool = True,
    source: str = "direct",
) -> dict[str, Any]:
    return {
        "ok": ok,
        "places": places[:DEFAULT_PLACE_LIMIT],
        "guidance": VISIT_OFFICE_GUIDANCE,
        "display_policy": VISIT_OFFICE_DISPLAY_POLICY,
        "source": source,
    }
