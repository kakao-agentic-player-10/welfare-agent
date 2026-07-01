from welfare_agent.clients.embeddings import (
    EmbeddingConfig,
    OpenAIEmbeddingClient,
    parse_proxy_embeddings,
)


def test_parse_proxy_embeddings_accepts_openai_compatible_response():
    payload = {"data": [{"embedding": ["0.1", 0.2]}]}

    assert parse_proxy_embeddings(payload) == [[0.1, 0.2]]


def test_embed_many_uses_proxy_when_openai_key_is_missing(monkeypatch):
    called = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"embeddings": [[0.1, 0.2], [0.3, 0.4]]}

    def fake_post(url, json, headers, timeout):
        called["url"] = url
        called["json"] = json
        called["headers"] = headers
        called["timeout"] = timeout
        return Response()

    monkeypatch.setattr("welfare_agent.clients.embeddings.httpx.post", fake_post)

    client = OpenAIEmbeddingClient(
        EmbeddingConfig(
            api_key="",
            proxy_url="https://example.test/embeddings",
            proxy_token="proxy-token",
            timeout_seconds=7,
        )
    )

    embeddings = client.embed_many(["  청년   월세  ", ""])

    assert embeddings == [[0.1, 0.2], [0.3, 0.4]]
    assert called["url"] == "https://example.test/embeddings"
    assert called["json"] == {
        "model": "text-embedding-3-small",
        "input": ["청년 월세", "empty"],
        "dimensions": 1536,
    }
    assert called["headers"]["Authorization"] == "Bearer proxy-token"
    assert called["timeout"] == 7
