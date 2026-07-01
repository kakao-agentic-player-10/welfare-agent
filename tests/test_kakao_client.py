from welfare_agent.clients.kakao import KakaoLocalClient


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
                    }
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
        "places": [{"name": "마포구청", "address": "서울 마포구 월드컵로 212"}],
        "source": "proxy",
    }
    assert called["url"] == "https://proxy.example.test/v1/kakao/local/search"
    assert called["json"] == {
        "query": "마포구 주민센터",
        "size": 5,
        "x": "126.9",
        "y": "37.5",
        "radius": 20000,
    }
    assert called["headers"]["Authorization"] == "Bearer proxy-token"
    assert called["timeout"] == 3
