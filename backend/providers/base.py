from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, ConfigDict


class ProviderResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider_name: str
    model_name: str
    content: str
    raw_response: dict[str, Any] | None = None


class BaseProvider(ABC):
    @property
    @abstractmethod
    def provider_name(self) -> str: ...

    @property
    @abstractmethod
    def model_name(self) -> str: ...

    @abstractmethod
    def is_available(self) -> bool: ...

    @abstractmethod
    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ProviderResponse: ...
