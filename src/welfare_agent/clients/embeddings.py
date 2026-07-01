from __future__ import annotations

from dataclasses import dataclass

import httpx
from openai import OpenAI

from welfare_agent.errors import ExternalApiError


MAX_EMBEDDING_INPUT_CHARS = 6000


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    model: str = "text-embedding-3-small"
    dimensions: int = 1536
    proxy_url: str = ""
    proxy_token: str = ""
    timeout_seconds: float = 30.0

    @property
    def ready(self) -> bool:
        return bool(self.api_key or self.proxy_url)


class OpenAIEmbeddingClient:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._client = OpenAI(api_key=config.api_key) if config.api_key else None

    def embed_one(self, text: str) -> list[float] | None:
        embeddings = self.embed_many([text])
        return embeddings[0] if embeddings else None

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        inputs = [prepare_embedding_input(text) for text in texts]
        if not inputs:
            return []

        if not self._client:
            return self._embed_many_via_proxy(inputs)

        kwargs: dict[str, object] = self._embedding_request_payload(inputs)
        response = self._client.embeddings.create(**kwargs)
        return [item.embedding for item in response.data]

    def _embed_many_via_proxy(self, inputs: list[str]) -> list[list[float]]:
        if not self.config.proxy_url:
            return []

        headers = {"Content-Type": "application/json"}
        if self.config.proxy_token:
            headers["Authorization"] = f"Bearer {self.config.proxy_token}"

        try:
            response = httpx.post(
                self.config.proxy_url,
                json=self._embedding_request_payload(inputs),
                headers=headers,
                timeout=self.config.timeout_seconds,
            )
            response.raise_for_status()
            embeddings = parse_proxy_embeddings(response.json())
        except httpx.HTTPError as exc:
            raise ExternalApiError(f"임베딩 프록시 호출 실패: {exc}") from exc
        except ValueError as exc:
            raise ExternalApiError("임베딩 프록시 응답을 JSON으로 파싱하지 못했습니다.") from exc

        if len(embeddings) != len(inputs):
            raise ExternalApiError("임베딩 프록시 응답 개수가 요청 개수와 다릅니다.")
        return embeddings

    def _embedding_request_payload(self, inputs: list[str]) -> dict[str, object]:
        payload: dict[str, object] = {"model": self.config.model, "input": inputs}
        if self.config.dimensions and self.config.model.startswith("text-embedding-3"):
            payload["dimensions"] = self.config.dimensions
        return payload


def parse_proxy_embeddings(payload: object) -> list[list[float]]:
    if not isinstance(payload, dict):
        raise ExternalApiError("임베딩 프록시 응답 형식이 올바르지 않습니다.")

    raw_embeddings = payload.get("embeddings")
    if raw_embeddings is None and "embedding" in payload:
        raw_embeddings = [payload["embedding"]]
    if raw_embeddings is None and isinstance(payload.get("data"), list):
        raw_embeddings = [
            item.get("embedding") if isinstance(item, dict) else item
            for item in payload["data"]
        ]

    if not isinstance(raw_embeddings, list):
        raise ExternalApiError("임베딩 프록시 응답에 embeddings 배열이 없습니다.")

    embeddings: list[list[float]] = []
    for embedding in raw_embeddings:
        if not isinstance(embedding, list):
            raise ExternalApiError("임베딩 프록시 응답의 embedding 값이 배열이 아닙니다.")
        embeddings.append([float(value) for value in embedding])
    return embeddings


def prepare_embedding_input(text: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return "empty"
    return normalized[:MAX_EMBEDDING_INPUT_CHARS]
