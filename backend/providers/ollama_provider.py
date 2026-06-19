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
            if response.status_code != 200:
                return False
            return self._model_is_pulled(response.json())
        except httpx.HTTPError:
            return False

    def _model_is_pulled(self, tags_data: dict[str, Any]) -> bool:
        models = tags_data.get("models") or []
        available = {str(entry.get("name", "")) for entry in models}
        # Ollama reports tagged names like "llama3.2:3b"; accept an untagged
        # match too so "llama3.2" resolves against "llama3.2:latest".
        if self._model in available:
            return True
        base_names = {name.split(":", 1)[0] for name in available}
        return self._model.split(":", 1)[0] in base_names

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
            token_usage=self._extract_token_usage(data),
            estimated_cost_usd=0.0 if self.mode == "local" else None,
            raw_response=data,
        )

    def _client(self) -> httpx.Client:
        return httpx.Client(
            base_url=self.base_url,
            timeout=self.timeout,
            transport=self.transport,
        )

    def _extract_token_usage(self, response_data: dict[str, Any]) -> dict[str, Any] | None:
        prompt_tokens = response_data.get("prompt_eval_count")
        completion_tokens = response_data.get("eval_count")
        if prompt_tokens is None and completion_tokens is None:
            return None
        prompt_value = int(prompt_tokens or 0)
        completion_value = int(completion_tokens or 0)
        return {
            "prompt_tokens": prompt_value,
            "completion_tokens": completion_value,
            "total_tokens": prompt_value + completion_value,
            "estimated": False,
        }
