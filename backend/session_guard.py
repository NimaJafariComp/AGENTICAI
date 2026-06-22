"""
Session decision guard.

Reads a session's existing final decisions, tool calls, and traces, then
returns a SessionGate that tells the agent whether the incoming user message
is allowed to trigger a fresh policy evaluation, and why if not.

Decision hierarchy (applied in this order):
  APPROVE   → terminal; no further evaluation allowed in this session.
  ESCALATE  → auto-decision locked; no approve or deny allowed.
  DENY      → depends on the denial category of the reason codes:
                HARD        → terminal; no re-evaluation.
                ESCALATABLE → no auto-decision; may escalate.
                CORRECTABLE → allowed; user may provide missing info.
  INCOMPLETE  (tool calls / traces but no final decision) → allowed.
  ERRORED     (at least one failed tool call, no final decision) → allowed.
  NO_ACTIVITY (nothing yet) → allowed.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field

from backend.data_store import DataStore
from backend.schemas import DenialCategory

# ── Reason-code classification ────────────────────────────────────────────────

HARD_DENIAL_CODES: frozenset[str] = frozenset({
    "FINAL_SALE_ITEM",
    "OUTSIDE_RETURN_WINDOW",
    "DAMAGED_DEFECTIVE_NOT_ELIGIBLE",
    "DAMAGED_DEFECTIVE_OUTSIDE_SPECIAL_WINDOW",
    "NON_REFUNDABLE_ITEM",
    "DUPLICATE_REFUND_ALREADY_PROCESSED",
})

CORRECTABLE_DENIAL_CODES: frozenset[str] = frozenset({
    "MISSING_RECEIPT",
    "MISSING_ORDER_ID",
    "MISSING_ITEM_CONDITION",
    "MISSING_PURCHASE_DATE",
    "UNCLEAR_REQUEST",
    "MISSING_DAMAGE_EVIDENCE",
})

ESCALATABLE_DENIAL_CODES: frozenset[str] = frozenset({
    "POLICY_EXCEPTION_REQUESTED",
    "CUSTOMER_DISPUTES_POLICY_DATA",
    "BORDERLINE_RETURN_WINDOW",
    "HIGH_VALUE_ORDER",
    "CONFLICTING_INFORMATION",
    "POSSIBLE_FRAUD",
    "SUSPICIOUS_OR_INCONSISTENT_CLAIM",
})


def classify_denial(reason_codes: list[str]) -> DenialCategory:
    """
    HARD wins over ESCALATABLE wins over CORRECTABLE.
    Unknown codes default to HARD (conservative).
    """
    codes = set(reason_codes)
    if codes & HARD_DENIAL_CODES:
        return DenialCategory.HARD
    if codes & ESCALATABLE_DENIAL_CODES:
        return DenialCategory.ESCALATABLE
    if codes & CORRECTABLE_DENIAL_CODES:
        return DenialCategory.CORRECTABLE
    return DenialCategory.HARD


# ── Gate result ───────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class SessionGate:
    """
    allowed=True  → proceed with normal intake + policy evaluation.
    allowed=False → return a blocked response; use `block_reason` + `reason_codes`
                    to build the LLM prompt.
    """
    allowed: bool
    chip_status: str                       # mirrors frontend chip label
    decision_type: str | None              # APPROVE / DENY / ESCALATE or None
    denial_category: DenialCategory | None # set only when decision_type==DENY
    reason_codes: list[str] = field(default_factory=list)
    block_reason: str | None = None        # structured key; used in prompt builder


# ── Guard ─────────────────────────────────────────────────────────────────────

class SessionGuard:
    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store

    def evaluate(self, session_id: str) -> SessionGate:
        decisions  = self.data_store.list_final_decisions(session_id=session_id)
        tool_calls = self.data_store.list_tool_calls(session_id=session_id)
        traces     = self.data_store.list_traces(session_id=session_id)

        if decisions:
            latest       = decisions[-1]
            dt           = latest.decision_type.value
            reason_codes = json.loads(latest.reason_codes_json)

            if dt == "APPROVE":
                return SessionGate(
                    allowed=False,
                    chip_status="APPROVE",
                    decision_type="APPROVE",
                    denial_category=None,
                    reason_codes=reason_codes,
                    block_reason="ALREADY_APPROVED",
                )

            if dt == "ESCALATE":
                return SessionGate(
                    allowed=False,
                    chip_status="ESCALATE",
                    decision_type="ESCALATE",
                    denial_category=None,
                    reason_codes=reason_codes,
                    block_reason="ALREADY_ESCALATED",
                )

            if dt == "DENY":
                category = classify_denial(reason_codes)
                if category == DenialCategory.CORRECTABLE:
                    # Allow the user to supply missing information.
                    return SessionGate(
                        allowed=True,
                        chip_status="DENY",
                        decision_type="DENY",
                        denial_category=category,
                        reason_codes=reason_codes,
                        block_reason=None,
                    )
                return SessionGate(
                    allowed=False,
                    chip_status="DENY",
                    decision_type="DENY",
                    denial_category=category,
                    reason_codes=reason_codes,
                    block_reason=f"DENIED_{category.value}",
                )

        # No final decision — derive chip from activity
        has_failed = any(c.status == "failed" for c in tool_calls)
        has_activity = bool(tool_calls) or bool(
            t for t in traces if t.event_type not in {"user_message", "assistant_message"}
        )

        if has_failed:
            chip = "ERRORED"
        elif has_activity:
            chip = "INCOMPLETE"
        else:
            chip = "NO_ACTIVITY"

        return SessionGate(
            allowed=True,
            chip_status=chip,
            decision_type=None,
            denial_category=None,
            reason_codes=[],
            block_reason=None,
        )
