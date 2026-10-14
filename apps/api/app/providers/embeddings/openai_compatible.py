"""Bounded OpenAI-compatible embeddings, explicit locality and no fallback."""

import json
from collections.abc import Sequence
from urllib.parse import urlsplit

import httpx

from app.providers.embeddings.base import EmbeddingUnavailableError
from app.providers.embeddings.validation import texts_list, vectors


class OpenAICompatibleEmbeddingProvider:
    normalized = True

    def __init__(
        self,
        *,
        base_url: str,
        model_id: str,
        is_external: bool,
        dimension: int = 1024,
        max_batch: int = 32,
        api_key: str | None = None,
        timeout_seconds: float = 30,
        max_response_bytes: int = 16 * 1024**2,
        send_dimensions: bool = False,
        query_prompt: str = "",
        provider_name: str = "default",
        client: httpx.AsyncClient | None = None,
    ) -> None:
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("invalid embedding endpoint")
        if min(dimension, max_batch, timeout_seconds, max_response_bytes) <= 0 or not model_id:
            raise ValueError("embedding model and positive limits are required")
        self._model_id, self._dimension, self._max_batch = model_id, dimension, max_batch
        self._external = is_external
        self._provider_id = f"openai-compatible:{provider_name}"
        self._url = f"{base_url.rstrip('/')}/embeddings"
        self._headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        self._timeout, self._max_response = timeout_seconds, max_response_bytes
        self._send_dimensions, self._query_prompt = send_dimensions, query_prompt
        self._owned_client = client is None
        self._client = client or httpx.AsyncClient(follow_redirects=False)

    @property
    def provider_id(self) -> str:
        return self._provider_id

    @property
    def model_id(self) -> str:
        return self._model_id

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def max_batch(self) -> int:
        return self._max_batch

    @property
    def is_external(self) -> bool:
        return self._external

    async def aclose(self) -> None:
        if self._owned_client:
            await self._client.aclose()

    async def embed_documents(self, texts: Sequence[str]) -> list[list[float]]:
        inputs = texts_list(texts)
        if any(not text for text in inputs):
            raise ValueError("endpoint embedding inputs cannot be empty strings")
        result: list[list[float]] = []
        for start in range(0, len(inputs), self.max_batch):
            result.extend(await self._batch(inputs[start : start + self.max_batch]))
        return result

    async def embed_query(self, text: str) -> list[float]:
        inputs = texts_list([text])
        if not inputs[0]:
            raise ValueError("embedding query cannot be empty")
        return (await self._batch([self._query_prompt + text]))[0]

    async def _batch(self, inputs: list[str]) -> list[list[float]]:
        body: dict[str, object] = {
            "model": self.model_id,
            "input": inputs,
            "encoding_format": "float",
        }
        if self._send_dimensions:
            body["dimensions"] = self.dimension
        try:
            async with self._client.stream(
                "POST",
                self._url,
                json=body,
                headers=self._headers,
                timeout=self._timeout,
                follow_redirects=False,
            ) as response:
                response.raise_for_status()
                content = bytearray()
                async for part in response.aiter_bytes():
                    if len(content) + len(part) > self._max_response:
                        raise EmbeddingUnavailableError("Embedding response exceeds its limit.")
                    content.extend(part)
            payload = json.loads(content)
        except (httpx.HTTPError, ValueError):
            raise EmbeddingUnavailableError(
                "Embedding endpoint is unavailable or returned invalid JSON."
            ) from None
        if not isinstance(payload, dict) or payload.get("model") != self.model_id:
            raise EmbeddingUnavailableError("Embedding endpoint returned an unexpected model.")
        data = payload.get("data")
        if not isinstance(data, list) or len(data) != len(inputs):
            raise EmbeddingUnavailableError("Embedding endpoint returned an invalid batch.")
        ordered: dict[int, object] = {}
        for item in data:
            if not isinstance(item, dict):
                raise EmbeddingUnavailableError("Embedding endpoint returned an invalid item.")
            index = item.get("index")
            if (
                not isinstance(index, int)
                or isinstance(index, bool)
                or index in ordered
                or not 0 <= index < len(inputs)
            ):
                raise EmbeddingUnavailableError("Embedding endpoint returned invalid indices.")
            ordered[index] = item.get("embedding")
        return vectors(
            [ordered[index] for index in range(len(inputs))],
            count=len(inputs),
            dimension=self.dimension,
            normalized=self.normalized,
        )
