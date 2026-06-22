from __future__ import annotations

SYSTEM_PROMPT = """
You are Aria, a customer support specialist at an e-commerce refund desk.
You are kind, direct, and honest. You work within a refund policy you did not write and cannot change.

Your responsibilities:
- Guide customers through providing the details needed to process their refund request.
- Communicate refund decisions clearly and with appropriate empathy.
- Handle follow-up questions calmly after a final decision has been made.

Format rules — always follow these:
- Write in plain prose only. No bullet points, no numbered lists, no headers, no bold or italic formatting.
- Keep responses to 2 to 4 sentences. A decision explanation may be one sentence longer if necessary.
- Never open with a filler phrase. Do not start with "Of course!", "Sure!", "Absolutely!", "Great question!", "Happy to help!", "Certainly!", or anything similar.
- Do not start your first sentence with the word "I".
- When only one detail is missing, ask for only that one thing. Do not pile on future questions.

Hard rules — never break these:
- Never mention internal system terms: no decision IDs, session IDs, reason codes, policy engine, or tool names.
- Never invent details about an order, customer account, or policy rule.
- Never promise a refund outcome that has not been confirmed by the system.
- Never suggest the policy can be overridden or that you can make exceptions.
- You may acknowledge that a situation is frustrating or disappointing. You may not change the outcome.
- If a customer argues or repeats themselves, respond calmly and do not repeat yourself.
""".strip()


# Human-readable labels for intake fields used in customer-facing prompts.
_FIELD_LABELS: dict[str, str] = {
    "customer_email": "email address on the account",
    "customer_name":  "full name as it appears on the account",
    "order_id":       "order ID (it looks like ORD- followed by four digits)",
    "item_id":        "the name or item ID of the specific item to be refunded",
    "issue_type":     "what is wrong with the item",
}

# Priority order for progressive intake — ask for these in order when many are missing.
_INTAKE_PRIORITY = (
    "customer_email",
    "order_id",
    "customer_name",
    "item_id",
    "issue_type",
)

# Keep public alias so any existing import of FIELD_LABELS still works.
FIELD_LABELS = _FIELD_LABELS


def build_missing_info_prompt(
    missing_fields: list[str],
    *,
    known_fields: dict[str, object] | None = None,
    note: str | None = None,
) -> str:
    known = {k: v for k, v in (known_fields or {}).items() if v}
    known_str = (
        "Information already collected: "
        + ", ".join(f"{_FIELD_LABELS.get(k, k)}: {v}" for k, v in known.items())
        + "."
        if known else ""
    )

    # Sort by priority so the most important field is always asked first.
    priority_missing = sorted(
        missing_fields,
        key=lambda f: _INTAKE_PRIORITY.index(f) if f in _INTAKE_PRIORITY else 99,
    )

    if note:
        # Name-mismatch or verification scenario — single-field, special context.
        field_desc = _FIELD_LABELS.get(priority_missing[0], priority_missing[0])
        return (
            f"Ask the customer to provide their {field_desc}. "
            f"Situation: {note} "
            f"{known_str} "
            "Be polite and phrase it as a routine verification step, not an accusation. "
            "One sentence is enough."
        )

    if len(priority_missing) == 1:
        field_desc = _FIELD_LABELS.get(priority_missing[0], priority_missing[0])
        return (
            f"Ask the customer for their {field_desc} in one friendly, conversational sentence. "
            f"{known_str}"
        )

    # Multiple fields missing: ask for the first two most important ones together
    # so the conversation moves forward without overwhelming the customer.
    top_two = [_FIELD_LABELS.get(f, f) for f in priority_missing[:2]]
    fields_str = " and ".join(top_two)
    return (
        f"Greet the customer and ask for their {fields_str} to get started. "
        "Do not mention that other details will be needed later. "
        "Keep it to one or two friendly sentences. "
        f"{known_str}"
    )


def build_blocked_response_prompt(
    *,
    block_reason: str,
    decision_type: str,
    reason_codes: list[str],
    denial_category: str | None = None,
) -> str:
    if block_reason == "ALREADY_APPROVED":
        return (
            "This refund has already been approved in a previous message and the customer is following up. "
            "Write one or two sentences confirming the refund is approved and will be processed. "
            "If they have a different request, let them know they would need to start a new conversation. "
            "Be warm and brief."
        )

    if block_reason == "ALREADY_ESCALATED":
        return (
            "This case has already been escalated to a human specialist for review and the customer is following up. "
            "Write one or two sentences confirming the escalation is in progress and a specialist will follow up. "
            "Do not promise a specific outcome or timeline. "
            "Do not issue any approval or denial — that decision belongs to the human reviewer."
        )

    if block_reason == f"DENIED_{denial_category}":
        if denial_category == "HARD_DENIAL":
            return (
                "This refund was previously denied under a firm policy rule that cannot be reversed automatically, "
                "and the customer is pushing back or asking again. "
                "Write 2 to 3 sentences: acknowledge their frustration, restate that the decision stands, "
                "and let them know that if they believe the information on file is wrong, "
                "they can request escalation to a human reviewer. "
                "Do not suggest the outcome can change without human review. "
                "Be honest and empathetic, not cold."
            )
        if denial_category == "ESCALATABLE_DENIAL":
            return (
                "This refund was previously denied for a reason a human reviewer could examine further, "
                "and the customer is following up. "
                "Write 2 to 3 sentences: explain that the automated system cannot change this decision, "
                "but they can request escalation to a specialist who can take a closer look. "
                "Offer escalation as the clear next step. Do not approve or deny."
            )
        if denial_category == "CORRECTABLE_DENIAL":
            return (
                "This refund was previously denied because required information was missing or unclear, "
                "and the customer may be able to correct this. "
                "Write 1 to 2 sentences: let them know they can provide the corrected or missing information "
                "and the request will be re-evaluated. Be encouraging but honest."
            )

    # Generic fallback for any other blocked state.
    return (
        f"A final decision has already been recorded for this session: {decision_type}. "
        "The customer is sending another message. "
        "Write 1 to 2 sentences explaining the current status calmly. "
        "Describe what options are available to them. Do not re-evaluate the request."
    )


def build_decision_prompt(
    *,
    decision_type: str,
    explanation: str,
    reason_codes: list[str],
) -> str:
    """Generate a customer-facing message explaining a refund decision.

    Reason codes are intentionally excluded — they are internal identifiers
    that should never appear in customer-facing text. The human-readable
    explanation carries all the context the LLM needs.
    """
    if decision_type == "APPROVE":
        return (
            f"The refund system has approved this request. Reason: {explanation} "
            "Write a warm, clear message confirming the approval. "
            "Mention that the refund will typically appear within 3 to 5 business days. "
            "Keep it positive and brief — 2 to 3 sentences."
        )

    if decision_type == "DENY":
        return (
            f"The refund system has denied this request. Reason: {explanation} "
            "Write an empathetic message explaining the denial. "
            "Acknowledge that this may be disappointing. "
            "Let them know that if they believe there is an error in the information on file, "
            "they can request escalation to a human specialist. "
            "Do not give false hope about an automatic reversal. "
            "Keep it honest and human — 3 to 4 sentences."
        )

    if decision_type == "ESCALATE":
        return (
            f"The refund system has escalated this case for human review. Reason: {explanation} "
            "Write a reassuring message explaining that the case is being reviewed by a specialist. "
            "Let the customer know they will be contacted with an update. "
            "Do not promise a specific outcome or timeframe. "
            "Keep it calm and clear — 2 to 3 sentences."
        )

    return (
        f"The refund system has reached a decision: {decision_type}. Reason: {explanation} "
        "Explain the outcome clearly and professionally in 2 to 3 sentences."
    )
