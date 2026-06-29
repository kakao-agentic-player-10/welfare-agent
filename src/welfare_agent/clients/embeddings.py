from __future__ import annotations

from dataclasses import dataclass

from openai import OpenAI


MAX_EMBEDDING_INPUT_CHARS = 6000


@dataclass(frozen=True)
class EmbeddingConfig:
    api_key: str
    model: str = "text-embedding-3-small"
    dimensions: int = 1536

    @property
    def ready(self) -> bool:
        return bool(self.api_key)


class OpenAIEmbeddingClient:
    def __init__(self, config: EmbeddingConfig):
        self.config = config
        self._client = OpenAI(api_key=config.api_key) if config.ready else None

    def embed_one(self, text: str) -> list[float] | None:
        embeddings = self.embed_many([text])
        return embeddings[0] if embeddings else None

    def embed_many(self, texts: list[str]) -> list[list[float]]:
        if not self._client:
            return []
        inputs = [prepare_embedding_input(text) for text in texts]
        if not inputs:
            return []

        kwargs: dict[str, object] = {"model": self.config.model, "input": inputs}
        if self.config.dimensions and self.config.model.startswith("text-embedding-3"):
            kwargs["dimensions"] = self.config.dimensions

        response = self._client.embeddings.create(**kwargs)
        return [item.embedding for item in response.data]


def prepare_embedding_input(text: str) -> str:
    normalized = " ".join((text or "").split()).strip()
    if not normalized:
        return "empty"
    return normalized[:MAX_EMBEDDING_INPUT_CHARS]
