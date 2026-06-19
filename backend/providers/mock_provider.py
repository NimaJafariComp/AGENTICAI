from __future__ import annotations

from backend.providers.base import BaseProvider, ProviderResponse


class MockProvider(BaseProvider):
    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return "mock-static"

    def is_available(self) -> bool:
        return True

    def chat(
        self,
        *,
        messages: list[dict[str, str]],
        system_prompt: str | None = None,
    ) -> ProviderResponse:
        user_message = ""
        for message in reversed(messages):
            if message.get("role") == "user":
                user_message = message.get("content", "")
                break

        lowered = user_message.lower()
        if "decision:" in lowered:
            if "approve" in lowered:
                content = "Your refund is approved under our policy. I can confirm the request has been completed."
            elif "deny" in lowered:
                content = "Your refund request is denied under the refund policy. I can explain the specific reason if helpful."
            else:
                content = "Your request has been escalated for human review under the refund policy."
        elif "refund" in lowered:
            content = (
                "I can help with your refund request. Please share your email, order ID, "
                "item, and what went wrong so I can check eligibility."
            )
        elif "hello" in lowered or "hi" in lowered:
            content = "Hello. I can help with refund requests and policy questions."
        else:
            content = (
                "I can help gather refund details and explain next steps. "
                "Please share your email and order ID."
            )

        return ProviderResponse(
            provider_name=self.provider_name,
            model_name=self.model_name,
            content=content,
            raw_response={"mock": True, "system_prompt_used": bool(system_prompt)},
        )
