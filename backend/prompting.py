from __future__ import annotations

SYSTEM_PROMPT = """
You are an AI customer support assistant for e-commerce refunds.
You may be polite, concise, and helpful.
You are not allowed to override policy.
The deterministic policy engine is the only authority for APPROVE, DENY, or ESCALATE.
If a decision has already been made, explain it clearly and calmly.
""".strip()


FIELD_LABELS = {
    "customer_email": "email address",
    "customer_name": "full customer name",
    "order_id": "order ID",
    "item_id": "item ID or exact item name",
    "issue_type": "issue with the item",
}


def build_missing_info_prompt(
    missing_fields: list[str],
    *,
    known_fields: dict[str, object] | None = None,
    note: str | None = None,
) -> str:
    fields = ", ".join(FIELD_LABELS.get(field, field) for field in missing_fields)
    known = ", ".join(
        f"{FIELD_LABELS.get(key, key)}: {value}"
        for key, value in (known_fields or {}).items()
        if value
    )
    note_text = f" Context: {note}." if note else ""
    known_text = f" Already collected: {known}." if known else ""
    return (
        "Ask the customer for the missing refund details in one short message. "
        f"Missing fields: {fields}.{known_text}{note_text}"
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
