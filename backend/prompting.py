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
            f"Write the next message the support agent sends to the customer. "
            f"Ask for their {field_desc} as a routine verification step. "
            f"Situation: {note} {known_str} "
            "One sentence. Plain prose. Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "To verify your account, could you confirm the full name as it appears on the order?"
        )

    if len(priority_missing) == 1:
        field_desc = _FIELD_LABELS.get(priority_missing[0], priority_missing[0])
        return (
            f"Write the next message the support agent sends to the customer. "
            f"Ask for their {field_desc}. {known_str} "
            "One sentence. Plain prose. Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "Could you share the order ID for the item you'd like to return — it looks like ORD-followed by four digits?"
        )

    # Multiple fields missing: ask for the first two most important ones together
    # so the conversation moves forward without overwhelming the customer.
    top_two = [_FIELD_LABELS.get(f, f) for f in priority_missing[:2]]
    fields_str = " and ".join(top_two)
    return (
        f"Write the opening message the support agent sends to start the refund request. "
        f"Ask for the customer's {fields_str}. "
        "Do not mention other details will be needed later. "
        f"{known_str} "
        "1 to 2 sentences. Plain prose. Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
        "Example of the correct style:\n"
        "To get started with your refund, could you share your email address and the order ID?"
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
            "This refund was already approved and the customer is following up. "
            "Write the support agent's response. 1 to 2 sentences. Plain prose. "
            "Confirm the refund is approved. If they have a different request, note they'd need a new conversation. "
            "Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "Your refund has already been approved and is on its way. "
            "For a separate request, please start a new conversation and we will be happy to help."
        )

    if block_reason == "ALREADY_ESCALATED":
        return (
            "This case was already escalated to a human specialist and the customer is following up. "
            "Write the support agent's response. 1 to 2 sentences. Plain prose. "
            "Confirm escalation is in progress and a specialist will follow up. "
            "Do not promise a timeline or outcome. "
            "Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "This case is already with one of our specialists for review. "
            "They will reach out to you directly once they have had a chance to look into it."
        )

    if block_reason == f"DENIED_{denial_category}":
        if denial_category == "HARD_DENIAL":
            return (
                "This refund was denied under a firm policy rule and the customer is pushing back. "
                "Write the support agent's response. 2 to 3 sentences. Plain prose. "
                "Acknowledge their frustration, restate the decision stands, and offer escalation to a human reviewer "
                "if they believe the information on file is wrong. "
                "Do not imply the outcome can change automatically. "
                "Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
                "Example of the correct style:\n"
                "We understand this is frustrating, and we are sorry for the disappointment. "
                "The denial stands under our current policy and cannot be reversed by this system. "
                "If you believe the information on file is incorrect, you can request a review by a human specialist."
            )
        if denial_category == "ESCALATABLE_DENIAL":
            return (
                "This refund was denied for a borderline reason and the customer is following up. "
                "Write the support agent's response. 2 to 3 sentences. Plain prose. "
                "Explain the automated system cannot change this decision, but escalation to a specialist is available. "
                "Offer escalation clearly. Do not approve or deny. "
                "Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
                "Example of the correct style:\n"
                "This decision cannot be changed automatically by our system. "
                "A human specialist can take a closer look if you would like to request escalation. "
                "Just let us know and we will pass this on to the right team."
            )
        if denial_category == "CORRECTABLE_DENIAL":
            return (
                "This refund was denied due to missing or unclear information and the customer can correct it. "
                "Write the support agent's response. 1 to 2 sentences. Plain prose. "
                "Let them know they can provide the missing details and the request will be re-evaluated. "
                "Do not start with 'I', 'Thank you', or any filler phrase.\n\n"
                "Example of the correct style:\n"
                "No problem — if you can share the missing details, we can take another look at this request."
            )

    # Generic fallback for any other blocked state.
    return (
        f"A final decision has already been recorded for this refund: {decision_type}. "
        "The customer is sending another message. "
        "Write the support agent's response. 1 to 2 sentences. Plain prose. "
        "Explain the status and what options are available. Do not re-evaluate. "
        "Do not start with 'I', 'Thank you', or any filler phrase."
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
            f"The refund system has approved this request. Reason: {explanation}\n\n"
            "Write the response the support agent sends to the customer. "
            "2 to 3 sentences. Plain prose only, no lists or formatting. "
            "Confirm the refund is approved and say it will appear within 3 to 5 business days. "
            "Do not start with 'I', 'Thank you', 'Of course', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "Your refund has been approved and will be credited back to your original payment method "
            "within 3 to 5 business days. If you have any questions in the meantime, feel free to reach out."
        )

    if decision_type == "DENY":
        return (
            f"The refund system has denied this request. Reason: {explanation}\n\n"
            "Write the response the support agent sends to the customer. "
            "3 to 4 sentences. Plain prose only, no lists or formatting. "
            "Acknowledge it may be disappointing, state the reason clearly, "
            "and let them know they can request escalation to a human specialist "
            "if they believe there is an error. Do not give false hope. "
            "Do not start with 'I', 'Thank you', 'Of course', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "We're sorry to share that this refund request has been denied. "
            "The item falls under our final sale policy, which does not allow returns. "
            "If you believe there has been a mistake with the information on file, "
            "you can request a review by a human specialist."
        )

    if decision_type == "ESCALATE":
        return (
            f"The refund system has escalated this case for human review. Reason: {explanation}\n\n"
            "Write the response the support agent sends to the customer. "
            "2 to 3 sentences. Plain prose only, no lists or formatting. "
            "Confirm the case has been passed to a specialist and they will follow up. "
            "Do not promise a specific outcome or timeline. "
            "Do not start with 'I', 'Thank you', 'Of course', or any filler phrase.\n\n"
            "Example of the correct style:\n"
            "This case has been escalated to one of our specialists for a closer look. "
            "They will review the details and reach out to you with an update."
        )

    return (
        f"The refund system has reached a decision: {decision_type}. Reason: {explanation}\n\n"
        "Write the response the support agent sends to the customer. "
        "2 to 3 sentences, plain prose only. "
        "Do not start with 'I', 'Thank you', 'Of course', or any filler phrase."
    )
