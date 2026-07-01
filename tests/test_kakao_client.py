from welfare_agent.clients.kakao import (
    DEFAULT_PLACE_LIMIT,
    VISIT_OFFICE_DISPLAY_POLICY,
    VISIT_OFFICE_GUIDANCE,
    KakaoLocalClient,
)


def test_keyword_search_uses_proxy_when_configured(monkeypatch):
    called = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {
                "ok": True,
                "places": [
                    {
                        "name": "마포구청",
                        "address": "서울 마포구 월드컵로 212",
                    },
                    {
                        "name": "서교동주민센터",
                        "address": "서울 마포구 동교로15길 7",
                    },
                    {
                        "name": "망원1동주민센터",
                        "address": "서울 마포구 포은로6길 10",
                    },
                    {
                        "name": "대흥동주민센터",
                        "address": "서울 마포구 신촌로26길 10",
                    },
                ],
            }

    def fake_post(url, json, headers, timeout):
        called["url"] = url
        called["json"] = json
        called["headers"] = headers
        called["timeout"] = timeout
        return Response()

    monkeypatch.setattr("welfare_agent.clients.kakao.httpx.post", fake_post)

    client = KakaoLocalClient(
        "",
        proxy_url="https://proxy.example.test/v1/kakao/local/search",
        proxy_token="proxy-token",
        proxy_timeout_seconds=3,
    )

    result = client.keyword_search("마포구 주민센터", x="126.9", y="37.5")

    assert result == {
        "ok": True,
        "places": [
            {"name": "마포구청", "address": "서울 마포구 월드컵로 212"},
            {"name": "서교동주민센터", "address": "서울 마포구 동교로15길 7"},
            {"name": "망원1동주민센터", "address": "서울 마포구 포은로6길 10"},
        ],
        "guidance": VISIT_OFFICE_GUIDANCE,
        "display_policy": VISIT_OFFICE_DISPLAY_POLICY,
        "source": "proxy",
    }
    assert called["url"] == "https://proxy.example.test/v1/kakao/local/search"
    assert called["json"] == {
        "query": "마포구 주민센터",
        "size": DEFAULT_PLACE_LIMIT,
        "x": "126.9",
        "y": "37.5",
        "radius": 20000,
    }
    assert called["headers"]["Authorization"] == "Bearer proxy-token"
    assert called["timeout"] == 3
