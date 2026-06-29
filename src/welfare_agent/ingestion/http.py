from __future__ import annotations

import json
from typing import Any
import xml.etree.ElementTree as ET

import httpx

from welfare_agent.errors import ExternalApiError


# API 응답 안에서 실제 목록 배열을 재귀적으로 찾는다.
def extract_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]

    if not isinstance(payload, dict):
        return []

    for key in (
        "data",
        "youthPolicyList",
        "items",
        "item",
        "servList",
        "services",
        "result",
        "results",
        "dsList",
        "dsSch",
    ):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        if isinstance(value, dict):
            nested = extract_items(value)
            if nested:
                return nested

    for value in payload.values():
        nested = extract_items(value)
        if nested:
            return nested

    return []


# HTTP 응답을 JSON 또는 XML dict로 파싱한다.
def parse_response_payload(response: httpx.Response) -> Any:
    try:
        return response.json()
    except json.JSONDecodeError:
        text = response.text.strip()
        if text.startswith("<"):
            try:
                return xml_to_dict(ET.fromstring(text))
            except ET.ParseError as exc:
                raise ExternalApiError("OpenAPI XML 응답 파싱에 실패했습니다.") from exc
        raise ExternalApiError("OpenAPI 응답이 JSON 또는 XML 형식이 아닙니다.")


# XML 루트 노드를 dict 구조로 변환한다.
def xml_to_dict(element: ET.Element) -> dict[str, Any]:
    return {element.tag: element_to_value(element)}


# XML 하위 노드를 문자열/list/dict 값으로 재귀 변환한다.
def element_to_value(element: ET.Element) -> Any:
    children = list(element)
    if not children:
        return (element.text or "").strip()

    result: dict[str, Any] = {}
    for child in children:
        value = element_to_value(child)
        if child.tag in result:
            existing = result[child.tag]
            if not isinstance(existing, list):
                result[child.tag] = [existing]
            result[child.tag].append(value)
        else:
            result[child.tag] = value
    return result
