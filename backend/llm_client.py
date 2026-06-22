from __future__ import annotations

import os
import time
from dataclasses import dataclass
from uuid import uuid4

from backend.providers.base import BaseProvider, ProviderResponse
from backend.providers.mock_provider import MockProvider
from backend.providers.ollama_provider import OllamaProvider
from backend.trace import TraceService

# API providers are imported lazily inside their branches so that missing
# optional packages only raise at runtime when the provider is actually selected.


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


@dataclass
class ProviderSelection:
    provider: BaseProvider
    requested_provider: str
    fallback_used: bool
    fallback_reason: str | None = None


class LLMClient:
    def __init__(
        self,
        selection: ProviderSelection,
        trace_service: TraceService | None = None,
    ) -> None:
        self.selection = selection
        self.trace_service = trace_service
        self._fallback_logged_sessions: set[str] = set()

    @classmethod
    def from_env(cls, trace_service: TraceService | None = None) -> LLMClient:
        requested_provider = os.getenv("LLM_PROVIDER", "ollama").strip().lower() or "ollama"

        if requested_provider == "mock":
            selection = ProviderSelection(
                provider=MockProvider(),
                requested_provider="mock",
                fallback_used=False,
            )
            return cls(selection, trace_service=trace_service)

        if requested_provider == "ollama":
            provider = OllamaProvider(
                base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
                model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
                mode=os.getenv("OLLAMA_MODE", "local"),
                availability_timeout=_env_float("OLLAMA_AVAILABILITY_TIMEOUT_SECONDS", 5.0),
                chat_timeout=_env_float("OLLAMA_CHAT_TIMEOUT_SECONDS", 90.0),
            )
            if provider.is_available():
                selection = ProviderSelection(
                    provider=provider,
                    requested_provider="ollama",
                    fallback_used=False,
                )
            else:
                selection = ProviderSelection(
                    provider=MockProvider(),
                    requested_provider="ollama",
                    fallback_used=True,
                    fallback_reason="Ollama unavailable; fell back to MockProvider.",
                )
            return cls(selection, trace_service=trace_service)

        if requested_provider == "openai":
            from backend.providers.openai_provider import OpenAIProvider
            api_key = os.getenv("OPENAI_API_KEY", "")
            if not api_key:
                selection = ProviderSelection(
                    provider=MockProvider(),
                    requested_provider="openai",
                    fallback_used=True,
                    fallback_reason="OPENAI_API_KEY is not set; fell back to MockProvider.",
                )
            else:
                provider = OpenAIProvider(
                    api_key=api_key,
                    model=os.getenv("OPENAI_MODEL", "gpt-4o-mini"),
                )
                selection = ProviderSelection(
                    provider=provider,
                    requested_provider="openai",
                    fallback_used=False,
                )
            return cls(selection, trace_service=trace_service)

        if requested_provider == "anthropic":
            from backend.providers.anthropic_provider import AnthropicProvider
            api_key = os.getenv("ANTHROPIC_API_KEY", "")
            if not api_key:
                selection = ProviderSelection(
                    provider=MockProvider(),
                    requested_provider="anthropic",
                    fallback_used=True,
                    fallback_reason="ANTHROPIC_API_KEY is not set; fell back to MockProvider.",
                )
            else:
                provider = AnthropicProvider(
                    api_key=api_key,
                    model=os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"),
                )
                selection = ProviderSelection(
                    provider=provider,
                    requested_provider="anthropic",
                    fallback_used=False,
                )
            return cls(selection, trace_service=trace_service)

        selection = ProviderSelection(
            provider=MockProvider(),
            requested_provider=requested_provider,
            fallback_used=True,
            fallback_reason=f"Unknown provider '{requested_provider}'; fell back to MockProvider.",
        )
        return cls(selection, trace_service=trace_service)

    def _try_reconnect(self) -> None:
        """If we fell back to mock, re-probe the originally requested provider."""
        if not self.selection.fallback_used:
            return
        if self.selection.requested_provider != "ollama":
            return
        candidate = OllamaProvider(
            base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "llama3.2:3b"),
            mode=os.getenv("OLLAMA_MODE", "local"),
            availability_timeout=_env_float("OLLAMA_AVAILABILITY_TIMEOUT_SECONDS", 5.0),
            chat_timeout=_env_float("OLLAMA_CHAT_TIMEOUT_SECONDS", 90.0),
        )
        if candidate.is_available():
            self.selection = ProviderSelection(
                provider=candidate,
                requested_provider="ollama",
                fallback_used=False,
            )
            self._fallback_logged_sessions.clear()

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        session_id: str | None = None,
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        self._try_reconnect()
        if session_id and self.selection.fallback_used and session_id not in self._fallback_logged_sessions:
            self._log_fallback(session_id)
            self._fallback_logged_sessions.add(session_id)
        started_at = time.perf_counter()
        response = self.selection.provider.chat(messages=messages, system_prompt=system_prompt)
        latency_ms = max(1, round((time.perf_counter() - started_at) * 1000))
        return response.model_copy(update={"latency_ms": latency_ms})

    def provider_info(self) -> dict[str, object]:
        self._try_reconnect()
        return {
            "requested_provider": self.selection.requested_provider,
            "active_provider": self.selection.provider.provider_name,
            "model_name": self.selection.provider.model_name,
            "fallback_used": self.selection.fallback_used,
            "fallback_reason": self.selection.fallback_reason,
        }

    def _log_fallback(self, session_id: str) -> None:
        if self.trace_service is None or self.selection.fallback_reason is None:
            return
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="provider_fallback",
            payload=self.provider_info(),
        )
