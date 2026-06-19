from __future__ import annotations


SYSTEM_PROMPT = """
You are an AI customer support assistant for e-commerce refunds.
You may be polite, concise, and helpful.
You are not allowed to override policy.
The deterministic policy engine is the only authority for APPROVE, DENY, or ESCALATE.
If a decision has already been made, explain it clearly and calmly.
""".strip()


def build_missing_info_prompt(missing_fields: list[str]) -> str:
    fields = ", ".join(missing_fields)
    return (
        "Ask the customer for the missing refund details in one short message. "
        f"Missing fields: {fields}."
    )


def build_decision_prompt(
    *,
    decision_type: str,
    explanation: str,
    reason_codes: list[str],
) -> str:
    return (
        "Explain the refund outcome politely in plain English. "
        f"Decision: {decision_type}. "
        f"Explanation: {explanation}. "
        f"Reason codes: {', '.join(reason_codes)}."
    )
