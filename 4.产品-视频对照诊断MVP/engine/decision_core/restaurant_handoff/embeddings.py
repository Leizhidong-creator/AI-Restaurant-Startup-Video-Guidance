from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Protocol, Sequence


class EmbeddingProvider(Protocol):
    model_name: str
    dimensions: int

    def embed(self, texts: Sequence[str]) -> list[list[float]]: ...


class OpenAICompatibleEmbeddingProvider:
    """OpenAI-compatible embedding client with no SDK dependency."""

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1",
        model_name: str = "text-embedding-v4",
        dimensions: int = 1024,
        timeout_seconds: int = 30,
    ) -> None:
        if not api_key:
            raise ValueError("api_key is required")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.dimensions = dimensions
        self.timeout_seconds = timeout_seconds

    def embed(self, texts: Sequence[str]) -> list[list[float]]:
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), 10):
            batch = list(texts[start : start + 10])
            payload = json.dumps(
                {
                    "model": self.model_name,
                    "input": batch,
                    "dimensions": self.dimensions,
                    "encoding_format": "float",
                }
            ).encode("utf-8")
            request = urllib.request.Request(
                f"{self.base_url}/embeddings",
                data=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                    body = json.loads(response.read().decode("utf-8"))
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"embedding service unavailable: {exc}") from exc
            ordered = sorted(body.get("data", []), key=lambda item: item["index"])
            if len(ordered) != len(batch):
                raise RuntimeError("embedding service returned an unexpected item count")
            vectors.extend([item["embedding"] for item in ordered])
        return vectors


