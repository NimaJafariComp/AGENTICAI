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


def build_blocked_response_prompt(
    *,
    block_reason: str,
    decision_type: str,
    reason_codes: list[str],
    denial_category: str | None = None,
) -> str:
    codes = ", ".join(reason_codes) if reason_codes else "none recorded"

    if block_reason == "ALREADY_APPROVED":
        return (
            "The customer is sending a follow-up message, but this refund has already been approved. "
            "Politely confirm that the refund was approved and no further action is needed in this session. "
            "If they want to start a different refund request, suggest opening a new session. "
            f"Reason codes on file: {codes}."
        )

    if block_reason == "ALREADY_ESCALATED":
        return (
            "The customer is sending a follow-up message, but this case has already been escalated for human review. "
            "Politely explain that no automatic approval or denial can be issued at this point. "
            "They may add notes or evidence, but the final outcome awaits the human reviewer. "
            f"Escalation reason codes: {codes}."
        )

    if block_reason == f"DENIED_{denial_category}":
        if denial_category == "HARD_DENIAL":
            return (
                "The customer is attempting to revisit a refund that was already denied under a hard policy rule. "
                "Politely restate the denial reason without re-evaluating. "
                "Do not approve or imply approval is possible. "
                "If they believe the information on file is incorrect, they may escalate for human review. "
                f"Denial reason codes: {codes}."
            )
        if denial_category == "ESCALATABLE_DENIAL":
            return (
                "The customer is attempting to revisit a denied refund. "
                "The denial reason falls into a category that may be reviewed by a human, "
                "but cannot be automatically approved or reversed by this system. "
                "Politely explain this and offer escalation as the appropriate next step. "
                f"Denial reason codes: {codes}."
            )

    # Generic fallback
    return (
        f"The refund session already has a final decision: {decision_type}. "
        f"Reason codes: {codes}. "
        "Politely explain the current status and what options are available to the customer."
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
