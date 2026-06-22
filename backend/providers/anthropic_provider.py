from __future__ import annotations

from typing import Any

from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.pricing import ANTHROPIC_PRICES, compute_cost

_MAX_TOKENS = 1024


class AnthropicProvider(BaseProvider):
    def __init__(self, *, api_key: str, model: str) -> None:
        try:
            import anthropic as _anthropic
        except ImportError as exc:
            raise ImportError(
                "anthropic package is required for LLM_PROVIDER=anthropic. "
                "Install it: pip install anthropic"
            ) from exc
        self._client = _anthropic.Anthropic(api_key=api_key)
        self._model = model

    @property
    def provider_name(self) -> str:
        return "anthropic"

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
        # Anthropic does not allow a system message in the messages list;
        # it is passed as a separate top-level parameter.
        kwargs: dict[str, Any] = {
            "model": self._model,
            "max_tokens": _MAX_TOKENS,
            "messages": messages,
        }
        if system_prompt:
            kwargs["system"] = system_prompt

        response = self._client.messages.create(**kwargs)

        content = "".join(
            block.text for block in response.content if hasattr(block, "text")
        )
        usage = response.usage
        token_usage: dict[str, Any] | None = None
        estimated_cost: float | None = None

        if usage:
            prompt_tokens = usage.input_tokens
            completion_tokens = usage.output_tokens
            token_usage = {
                "prompt_tokens": prompt_tokens,
                "completion_tokens": completion_tokens,
                "total_tokens": prompt_tokens + completion_tokens,
                "estimated": False,
            }
            estimated_cost = compute_cost(
                ANTHROPIC_PRICES, self._model, prompt_tokens, completion_tokens
            )

        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            content=content,
            token_usage=token_usage,
            estimated_cost_usd=estimated_cost,
            raw_response={"id": response.id, "model": response.model, "stop_reason": response.stop_reason},
        )
