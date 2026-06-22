from __future__ import annotations

import json
import re
import time
from datetime import date
from uuid import uuid4

from backend.llm_client import LLMClient
from backend.prompting import (
    SYSTEM_PROMPT,
    build_blocked_response_prompt,
    build_decision_prompt,
    build_missing_info_prompt,
)
from backend.providers.base import ProviderResponse
from backend.schemas import AgentTurnResult, DecisionType, RefundRequest
from backend.session_guard import SessionGuard
from backend.tools import RefundTools, ToolAuthorizationError
from backend.trace import TraceService

EMAIL_RE = re.compile(r"[\w.\-+]+@[\w.\-]+\.\w+")
ORDER_RE = re.compile(r"\bORD-\d{4}\b", re.IGNORECASE)
ITEM_RE = re.compile(r"\bITEM-\d{4}-[A-Z]\b", re.IGNORECASE)
NAME_PATTERNS = [
    re.compile(r"\bmy name is ([A-Za-z][A-Za-z' -]+)", re.IGNORECASE),
    re.compile(r"\bi am ([A-Za-z][A-Za-z' -]+)", re.IGNORECASE),
    re.compile(r"\bthis is ([A-Za-z][A-Za-z' -]+)", re.IGNORECASE),
]
REQUIRED_FIELDS = ("customer_email", "customer_name", "order_id", "item_id", "issue_type")


class RefundAgent:
    def __init__(
        self,
        llm_client: LLMClient,
        refund_tools: RefundTools,
        trace_service: TraceService,
        session_guard: SessionGuard | None = None,
    ) -> None:
        self.llm_client = llm_client
        self.refund_tools = refund_tools
        self.trace_service = trace_service
        self.session_guard = session_guard or SessionGuard(refund_tools.data_store)

    def process_user_message(
        self,
        *,
        session_id: str,
        message: str,
        today: date | None = None,
    ) -> AgentTurnResult:
        turn_started_at = time.perf_counter()
        self.trace_service.start_session(session_id=session_id)
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="user_message",
            payload={"message": message},
        )

        # ── Session decision guard ────────────────────────────────────────────
        gate = self.session_guard.evaluate(session_id)
        if not gate.allowed:
            response = self.llm_client.chat(
                session_id=session_id,
                system_prompt=SYSTEM_PROMPT,
                messages=[{
                    "role": "user",
                    "content": build_blocked_response_prompt(
                        block_reason=gate.block_reason or "",
                        decision_type=gate.decision_type or "",
                        reason_codes=gate.reason_codes,
                        denial_category=gate.denial_category.value if gate.denial_category else None,
                    ),
                }],
            )
            self._log_llm_response(session_id=session_id, response=response, response_kind="blocked")
            total_latency_ms = self._elapsed_ms(turn_started_at)
            self.trace_service.log_event(
                trace_id=f"trace-{uuid4()}",
                session_id=session_id,
                event_type="turn_summary",
                payload={
                    "status": "blocked",
                    "chip_status": gate.chip_status,
                    "block_reason": gate.block_reason,
                    "reason_codes": gate.reason_codes,
                },
                latency_ms=total_latency_ms,
            )
            return AgentTurnResult(
                session_id=session_id,
                status="blocked",
                assistant_message=response.content,
                decision_type=gate.decision_type,
                latency_ms=total_latency_ms,
                token_usage=response.token_usage or {},
                estimated_cost_usd=response.estimated_cost_usd,
            )
        # ─────────────────────────────────────────────────────────────────────

        intake_state = self._collect_intake_state(session_id=session_id)
        self.trace_service.start_session(
            session_id=session_id,
            customer_email=self._string_or_none(intake_state.get("customer_email")),
            intake_state=intake_state,
        )

        missing_fields = [field for field in REQUIRED_FIELDS if not intake_state.get(field)]
        if missing_fields:
            response = self._generate_missing_info_message(
                session_id=session_id,
                missing_fields=missing_fields,
                intake_state=intake_state,
            )
            return self._build_needs_input_result(
                session_id=session_id,
                intake_state=intake_state,
                missing_fields=missing_fields,
                response=response,
                started_at=turn_started_at,
            )

        customer = self.refund_tools.data_store.get_customer_by_email(str(intake_state["customer_email"]))
        if customer is None:
            raise ToolAuthorizationError("Customer not found for provided email.")

        if not self._names_match(str(intake_state["customer_name"]), customer.name):
            response = self._generate_missing_info_message(
                session_id=session_id,
                missing_fields=["customer_name"],
                intake_state=intake_state,
                note="The provided customer name does not match the account. Ask for the full exact name on the order.",
            )
            return self._build_needs_input_result(
                session_id=session_id,
                intake_state=intake_state,
                missing_fields=["customer_name"],
                response=response,
                started_at=turn_started_at,
            )

        order = self.refund_tools.data_store.get_order_by_id(str(intake_state["order_id"]))
        if order is None:
            raise ToolAuthorizationError("Order not found for provided order ID.")
        if order.customer_id != customer.id:
            raise ToolAuthorizationError("Provided order does not belong to the provided customer.")

        item_id = str(intake_state["item_id"])
        item = self.refund_tools.data_store.get_order_item(order.id, item_id)
        if item is None:
            raise ToolAuthorizationError("Provided item does not belong to the provided order.")

        cumulative_claim_text = self._collect_user_message_text(session_id=session_id)
        evidence_provided = self._infer_evidence_provided(cumulative_claim_text)
        request = RefundRequest(
            session_id=session_id,
            customer_email=customer.email,
            customer_name=str(intake_state["customer_name"]),
            order_id=order.id,
            item_id=item_id,
            issue_type=str(intake_state["issue_type"]),
            claim_text=cumulative_claim_text,
            requested_amount=self._infer_requested_amount(cumulative_claim_text, item.price),
            evidence_notes="Provided in message" if evidence_provided else None,
            evidence_provided=evidence_provided,
            claim_inconsistent=self._infer_claim_inconsistent(cumulative_claim_text),
        )

        eligibility = self.refund_tools.check_refund_eligibility(request=request, today=today)
        terminal_output = self._apply_terminal_action(
            session_id=session_id,
            decision_type=eligibility["decision_type"],
            decision_id=eligibility["decision_id"],
        )

        response = self._generate_decision_message(
            session_id=session_id,
            decision_type=eligibility["decision_type"],
            explanation=str(eligibility["explanation"]),
            reason_codes=list(eligibility["reason_codes"]),
        )
        self._log_llm_response(session_id=session_id, response=response, response_kind="decision")

        assistant_message = response.content
        total_latency_ms = self._elapsed_ms(turn_started_at)
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="assistant_message",
            payload={
                "message": assistant_message,
                "decision_type": eligibility["decision_type"],
                "decision_id": eligibility["decision_id"],
            },
            latency_ms=response.latency_ms,
            token_usage=response.token_usage,
            estimated_cost_usd=response.estimated_cost_usd,
        )
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="turn_summary",
            payload={
                "status": "completed",
                "decision_type": eligibility["decision_type"],
                "decision_id": eligibility["decision_id"],
                "reason_codes": eligibility["reason_codes"],
                "policy_rules": eligibility["policy_rules"],
                "intake_state": intake_state,
            },
            latency_ms=total_latency_ms,
            token_usage=response.token_usage,
            estimated_cost_usd=response.estimated_cost_usd,
        )

        return AgentTurnResult(
            session_id=session_id,
            status="completed",
            assistant_message=assistant_message,
            decision_type=str(eligibility["decision_type"]),
            decision_id=str(eligibility["decision_id"]),
            latency_ms=total_latency_ms,
            token_usage=response.token_usage or {},
            estimated_cost_usd=response.estimated_cost_usd,
            intake_state=intake_state,
            tool_outputs={
                "check_refund_eligibility": eligibility,
                "terminal_action": terminal_output,
            },
        )

    def _build_needs_input_result(
        self,
        *,
        session_id: str,
        intake_state: dict[str, object],
        missing_fields: list[str],
        response: ProviderResponse,
        started_at: float,
    ) -> AgentTurnResult:
        self._log_llm_response(session_id=session_id, response=response, response_kind="missing_info")
        assistant_message = response.content
        total_latency_ms = self._elapsed_ms(started_at)
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="assistant_message",
            payload={"message": assistant_message, "status": "needs_input"},
            latency_ms=response.latency_ms,
            token_usage=response.token_usage,
            estimated_cost_usd=response.estimated_cost_usd,
        )
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="turn_summary",
            payload={
                "status": "needs_input",
                "missing_fields": missing_fields,
                "intake_state": intake_state,
            },
            latency_ms=total_latency_ms,
            token_usage=response.token_usage,
            estimated_cost_usd=response.estimated_cost_usd,
        )
        return AgentTurnResult(
            session_id=session_id,
            status="needs_input",
            assistant_message=assistant_message,
            missing_fields=missing_fields,
            latency_ms=total_latency_ms,
            token_usage=response.token_usage or {},
            estimated_cost_usd=response.estimated_cost_usd,
            intake_state=intake_state,
        )

    def _generate_missing_info_message(
        self,
        *,
        session_id: str,
        missing_fields: list[str],
        intake_state: dict[str, object],
        note: str | None = None,
    ) -> ProviderResponse:
        return self.llm_client.chat(
            session_id=session_id,
            system_prompt=SYSTEM_PROMPT,
            messages=[
                {
                    "role": "user",
                    "content": build_missing_info_prompt(
                        missing_fields,
                        known_fields=intake_state,
                        note=note,
                    ),
                },
            ],
        )

    def _generate_decision_message(
        self,
        *,
        session_id: str,
        decision_type: str,
        explanation: str,
        reason_codes: list[str],
    ) -> ProviderResponse:
        return self.llm_client.chat(
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

    def _collect_intake_state(self, *, session_id: str) -> dict[str, object]:
        session = self.refund_tools.data_store.get_session(session_id)
        combined_text = self._collect_user_message_text(session_id=session_id)
        extracted = self._extract_fields(combined_text)
        if not extracted.get("customer_email") and session.customer_email:
            extracted["customer_email"] = session.customer_email

        order_id = self._string_or_none(extracted.get("order_id"))
        if order_id:
            order = self.refund_tools.data_store.get_order_by_id(order_id)
            if order is not None and not extracted.get("item_id"):
                item_id = self._match_item_name_to_order(combined_text, order)
                if item_id:
                    extracted["item_id"] = item_id

        return extracted

    def _collect_user_message_text(self, *, session_id: str) -> str:
        messages: list[str] = []
        for trace in self.refund_tools.data_store.list_traces(session_id=session_id):
            if trace.event_type != "user_message":
                continue
            payload = json.loads(trace.payload_json)
            message = payload.get("message")
            if isinstance(message, str):
                messages.append(message)
        return "\n".join(messages)

    def _log_llm_response(
        self,
        *,
        session_id: str,
        response: ProviderResponse,
        response_kind: str,
    ) -> None:
        self.trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="llm_response",
            payload={
                "response_kind": response_kind,
                "provider_name": response.provider_name,
                "model_name": response.model_name,
                "content": response.content,
            },
            latency_ms=response.latency_ms,
            token_usage=response.token_usage,
            estimated_cost_usd=response.estimated_cost_usd,
        )

    def _extract_fields(self, message: str) -> dict[str, str | None]:
        email_match = EMAIL_RE.search(message)
        order_match = ORDER_RE.search(message)
        item_match = ITEM_RE.search(message)
        return {
            "customer_email": email_match.group(0) if email_match else None,
            "customer_name": self._extract_customer_name(message),
            "order_id": order_match.group(0).upper() if order_match else None,
            "item_id": item_match.group(0).upper() if item_match else None,
            "issue_type": self._infer_issue_type(message),
        }

    def _extract_customer_name(self, message: str) -> str | None:
        for pattern in NAME_PATTERNS:
            match = pattern.search(message)
            if not match:
                continue
            candidate = re.split(r"[,.!\n]", match.group(1).strip(), maxsplit=1)[0].strip()
            candidate = re.sub(r"\s+", " ", candidate)
            if len(candidate.split()) >= 2:
                return candidate.title()
        return None

    def _match_item_name_to_order(self, message: str, order) -> str | None:
        lowered = message.lower()
        for item in order.items:
            if item.name.lower() in lowered:
                return item.item_id
        return None

    def _infer_issue_type(self, message: str) -> str | None:
        lowered = message.lower()
        if "damaged" in lowered:
            return "damaged"
        if "defective" in lowered or "broken" in lowered:
            return "defective"
        if "too small" in lowered or "too big" in lowered or "doesn't fit" in lowered:
            return "size_issue"
        if any(term in lowered for term in ("changed my mind", "don't want", "do not want", "no longer want")):
            return "changed_mind"
        return None

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

    def _names_match(self, provided_name: str, expected_name: str) -> bool:
        normalize = lambda value: re.sub(r"[^a-z0-9]+", " ", value.lower()).strip()
        return normalize(provided_name) == normalize(expected_name)

    def _string_or_none(self, value: object) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        return text or None

    def _elapsed_ms(self, started_at: float) -> int:
        return max(1, round((time.perf_counter() - started_at) * 1000))
