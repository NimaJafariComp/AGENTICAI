from __future__ import annotations

from typing import Any

import httpx

from backend.providers.base import BaseProvider, ProviderResponse


class OllamaProvider(BaseProvider):
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        mode: str = "local",
        timeout: float = 5.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._model = model
        self.mode = mode
        self.timeout = timeout
        self.transport = transport

    @property
    def provider_name(self) -> str:
        return "ollama"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        try:
            with self._client() as client:
                response = client.get("/api/tags")
            return response.status_code == 200
        except httpx.HTTPError:
            return False

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        payload_messages = []
        if system_prompt:
            payload_messages.append({"role": "system", "content": system_prompt})
        payload_messages.extend(messages)

        payload: dict[str, Any] = {
            "model": self._model,
            "messages": payload_messages,
            "stream": False,
        }

        with self._client() as client:
            response = client.post("/api/chat", json=payload)
            response.raise_for_status()
            data = response.json()

        content = data.get("message", {}).get("content", "")
        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            content=content,
            raw_response=data,
        )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        )
