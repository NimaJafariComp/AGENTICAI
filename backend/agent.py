from __future__ import annotations

import re
from datetime import date
from uuid import uuid4

from backend.llm_client import LLMClient
from backend.prompting import (
    SYSTEM_PROMPT,
    build_decision_prompt,
    build_missing_info_prompt,
)
from backend.schemas import AgentTurnResult, DecisionType, RefundRequest
from backend.tools import RefundTools, ToolAuthorizationError
from backend.trace import TraceService


EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
ORDER_RE = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
ITEM_RE = re.compile(r"\bITEM-\d{4}-[A-Z]\b", re.IGNORECASE)


class RefundAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        refund_tools: RefundTools,
        trace_service: TraceService,
    ) -> None:
        self.llm_client = llm_client
        self.refund_tools = refund_tools
        self.trace_service = trace_service

    def process_user_message(
        self,
        *,
        session_id: str,
        message: str,
        today: date | None = None,
    ) -> AgentTurnResult:
        self.trace_service.start_session(session_id=session_id)
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="user_message",
            payload={"message": message},
        )

        extracted = self._extract_fields(message)
        missing_fields = [field for field in ("customer_email", "order_id") if not extracted.get(field)]
        if missing_fields:
            assistant_message = self._generate_missing_info_message(
                session_id=session_id,
                missing_fields=missing_fields,
            )
            return AgentTurnResult(
                session_id=session_id,
                status="needs_input",
                assistant_message=assistant_message,
                missing_fields=missing_fields,
            )

        customer = self.refund_tools.data_store.get_customer_by_email(extracted["customer_email"])
        if customer is None:
            raise ToolAuthorizationError("Customer not found for provided email.")

        order = self.refund_tools.data_store.get_order_by_id(extracted["order_id"])
        if order is None:
            raise ToolAuthorizationError("Order not found for provided order ID.")

        item_id = extracted.get("item_id") or self._infer_single_item_id(order)
        if item_id is None:
            assistant_message = self._generate_missing_info_message(
                session_id=session_id,
                missing_fields=["item_id"],
            )
            return AgentTurnResult(
                session_id=session_id,
                status="needs_input",
                assistant_message=assistant_message,
                missing_fields=["item_id"],
            )

        request = RefundRequest(
            session_id=session_id,
            customer_email=customer.email,
            customer_name=customer.name,
            order_id=order.id,
            item_id=item_id,
            issue_type=self._infer_issue_type(message),
            claim_text=message,
            requested_amount=self._infer_requested_amount(message, order.total),
            evidence_notes="Provided in message" if self._infer_evidence_provided(message) else None,
            evidence_provided=self._infer_evidence_provided(message),
            claim_inconsistent=self._infer_claim_inconsistent(message),
        )

        eligibility = self.refund_tools.check_refund_eligibility(request=request, today=today)
        terminal_output = self._apply_terminal_action(
            session_id=session_id,
            decision_type=eligibility["decision_type"],
            decision_id=eligibility["decision_id"],
        )

        assistant_message = self._generate_decision_message(
            session_id=session_id,
            decision_type=eligibility["decision_type"],
            explanation=str(eligibility["explanation"]),
            reason_codes=list(eligibility["reason_codes"]),
        )
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="assistant_message",
            payload={"message": assistant_message},
        )

        return AgentTurnResult(
            session_id=session_id,
            status="completed",
            assistant_message=assistant_message,
            decision_type=str(eligibility["decision_type"]),
            decision_id=str(eligibility["decision_id"]),
            tool_outputs={
                "check_refund_eligibility": eligibility,
                "terminal_action": terminal_output,
            },
        )

    def _generate_missing_info_message(self, *, session_id: str, missing_fields: list[str]) -> str:
        response = self.llm_client.chat(
            session_id=session_id,
            system_prompt=SYSTEM_PROMPT,
            messages=[
                {"role": "user", "content": build_missing_info_prompt(missing_fields)},
            ],
        )
        return response.content

    def _generate_decision_message(
        self,
        *,
        session_id: str,
        decision_type: str,
        explanation: str,
        reason_codes: list[str],
    ) -> str:
        response = self.llm_client.chat(
            session_id=session_id,
            system_prompt=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_decision_prompt(
                        decision_type=decision_type,
                        explanation=explanation,
                        reason_codes=reason_codes,
                    ),
                }
            ],
        )
        if response.content:
            return response.content
        return explanation

    def _apply_terminal_action(
        self,
        *,
        session_id: str,
        decision_type: str,
        decision_id: str,
    ) -> dict[str, object]:
        if decision_type == DecisionType.APPROVE.value:
            return self.refund_tools.approve_refund(session_id=session_id, decision_id=decision_id)
        if decision_type == DecisionType.DENY.value:
            return self.refund_tools.deny_refund(session_id=session_id, decision_id=decision_id)
        return self.refund_tools.escalate_refund(session_id=session_id, decision_id=decision_id)

    def _extract_fields(self, message: str) -> dict[str, str | None]:
        email_match = EMAIL_RE.search(message)
        order_match = ORDER_RE.search(message)
        item_match = ITEM_RE.search(message)
        return {
            "customer_email": email_match.group(0) if email_match else None,
            "order_id": order_match.group(0).upper() if order_match else None,
            "item_id": item_match.group(0).upper() if item_match else None,
        }

    def _infer_single_item_id(self, order) -> str | None:
        if len(order.items) == 1:
            return order.items[0].item_id
        return None

    def _infer_issue_type(self, message: str) -> str:
        lowered = message.lower()
        if "damaged" in lowered:
            return "damaged"
        if "defective" in lowered or "broken" in lowered:
            return "defective"
        if "too small" in lowered or "too big" in lowered or "doesn't fit" in lowered:
            return "size_issue"
        return "changed_mind"

    def _infer_evidence_provided(self, message: str) -> bool:
        lowered = message.lower()
        return any(term in lowered for term in ("photo", "picture", "attached", "evidence", "screenshot"))

    def _infer_claim_inconsistent(self, message: str) -> bool:
        lowered = message.lower()
        return any(term in lowered for term in ("ignore policy", "override", "manager approved", "system prompt"))

    def _infer_requested_amount(self, message: str, default_amount: float) -> float:
        amount_match = re.search(r"\$(\d+(?:\.\d{1,2})?)", message)
        if amount_match:
            return float(amount_match.group(1))
        return default_amount
