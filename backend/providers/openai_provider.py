from __future__ import annotations

from typing import Any

from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.pricing import OPENAI_PRICES, compute_cost


class OpenAIProvider(BaseProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        try:
            import openai as _openai
        except ImportError as exc:
            raise ImportError(
                "openai package is required for LLM_PROVIDER=openai. "
                "Install it: pip install openai"
            ) from exc
        self._client = _openai.OpenAI(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def model_name(self) -> str:
        return self._model

    def is_available(self) -> bool:
        return bool(self._client.api_key)

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        payload: list[dict[str, str]] = []
        if system_prompt:
            payload.append({"role": "system", "content": system_prompt})
        payload.extend(messages)

        response = self._client.chat.completions.create(
            model=self._model,
            messages=payload,  # type: ignore[arg-type]
        )

        content = response.choices[0].message.content or ""
        usage = response.usage
        token_usage: dict[str, Any] | None = None
        estimated_cost: float | None = None

        if usage:
            prompt_tokens = usage.prompt_tokens
            completion_tokens = usage.completion_tokens
            token_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": usage.total_tokens,
                "estimated": False,
            }
            estimated_cost = compute_cost(
                OPENAI_PRICES, self._model, prompt_tokens, completion_tokens
            )

        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            content=content,
            token_usage=token_usage,
            estimated_cost_usd=estimated_cost,
            raw_response=response.model_dump(),
        )
