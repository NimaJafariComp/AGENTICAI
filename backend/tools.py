from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

from backend.data_store import DataStore, DataStoreError
from backend.policy_engine import PolicyEngine
from backend.schemas import DecisionType, RefundRequest
from backend.trace import TraceService


DECISION_TTL = timedelta(minutes=30)


class ToolAuthorizationError(RuntimeError):
    """Raised when a protected tool is called without a valid policy decision."""


class RefundTools:
    def __init__(
        self,
        data_store: DataStore,
        policy_engine: PolicyEngine,
        trace_service: TraceService | None = None,
    ) -> None:
        self.data_store = data_store
        self.policy_engine = policy_engine
        self.trace_service = trace_service

    def lookup_customer(self, *, email: str, session_id: str | None = None):
        customer = self.data_store.get_customer_by_email(email)
        if customer is None:
            raise ToolAuthorizationError(f"Customer not found for email: {email}")
        if session_id is not None:
            self._log_tool_call(
                session_id=session_id,
                tool_name="lookup_customer",
                tool_input={"email": email},
                tool_output={"customer_id": customer.id, "email": customer.email},
            )
        return customer

    def lookup_order(self, *, order_id: str, session_id: str | None = None):
        order = self.data_store.get_order_by_id(order_id)
        if order is None:
            raise ToolAuthorizationError(f"Order not found: {order_id}")
        if session_id is not None:
            self._log_tool_call(
                session_id=session_id,
                tool_name="lookup_order",
                tool_input={"order_id": order_id},
                tool_output={"order_id": order.id, "customer_id": order.customer_id},
            )
        return order

    def get_refund_policy(self, *, session_id: str | None = None):
        policy = self.data_store.load_policy()
        if session_id is not None:
            self._log_tool_call(
                session_id=session_id,
                tool_name="get_refund_policy",
                tool_input={},
                tool_output={
                    "policy_name": policy.metadata.policy_name,
                    "policy_version": policy.metadata.policy_version,
                },
            )
        return policy

    def check_refund_eligibility(
        self,
        *,
        request: RefundRequest,
        today: date | None = None,
    ) -> dict[str, object]:
        customer = self.lookup_customer(email=request.customer_email, session_id=request.session_id)
        order = self.lookup_order(order_id=request.order_id, session_id=request.session_id)
        item = self.data_store.get_order_item(request.order_id, request.item_id)
        if item is None:
            raise ToolAuthorizationError(f"Order item not found: {request.item_id}")

        policy = self.get_refund_policy(session_id=request.session_id)
        evaluation_date = today or datetime.now(UTC).date()
        decision = self.policy_engine.evaluate_refund(
            request=request,
            customer=customer,
            order=order,
            item=item,
            policy=policy,
            today=evaluation_date,
        )

        decision_id = f"decision-{uuid4()}"
        request_fingerprint = self._build_request_fingerprint(request)
        self.data_store.create_final_decision(
            payload=self._decision_record_payload(
                decision_id=decision_id,
                session_id=request.session_id,
                decision_type=decision.decision_type,
                request_fingerprint=request_fingerprint,
                reason_codes=decision.reason_codes,
            )
        )

        self._log_tool_call(
            session_id=request.session_id,
            tool_name="check_refund_eligibility",
            tool_input={
                "order_id": request.order_id,
                "item_id": request.item_id,
                "issue_type": request.issue_type,
                "requested_amount": request.requested_amount,
            },
            tool_output={
                "decision_id": decision_id,
                "decision_type": decision.decision_type.value,
                "reason_codes": decision.reason_codes,
            },
        )

        return {
            "decision_id": decision_id,
            "decision_type": decision.decision_type.value,
            "reason_codes": decision.reason_codes,
            "policy_rules": decision.policy_rules,
            "explanation": decision.explanation,
            "eligible": decision.eligible,
            "requires_human_review": decision.requires_human_review,
            "request_fingerprint": request_fingerprint,
        }

    def approve_refund(self, *, session_id: str, decision_id: str) -> dict[str, object]:
        return self._consume_protected_decision(
            session_id=session_id,
            decision_id=decision_id,
            expected_decision=DecisionType.APPROVE,
            tool_name="approve_refund",
        )

    def deny_refund(self, *, session_id: str, decision_id: str) -> dict[str, object]:
        return self._consume_protected_decision(
            session_id=session_id,
            decision_id=decision_id,
            expected_decision=DecisionType.DENY,
            tool_name="deny_refund",
        )

    def escalate_refund(self, *, session_id: str, decision_id: str) -> dict[str, object]:
        return self._consume_protected_decision(
            session_id=session_id,
            decision_id=decision_id,
            expected_decision=DecisionType.ESCALATE,
            tool_name="escalate_refund",
        )

    def _consume_protected_decision(
        self,
        *,
        session_id: str,
        decision_id: str,
        expected_decision: DecisionType,
        tool_name: str,
    ) -> dict[str, object]:
        try:
            final_decision = self.data_store.get_final_decision(decision_id)
        except DataStoreError as exc:
            raise ToolAuthorizationError("Missing or invalid decision_id.") from exc

        if final_decision.session_id != session_id:
            raise ToolAuthorizationError("decision_id does not belong to this session.")
        if final_decision.decision_type != expected_decision:
            raise ToolAuthorizationError(
                f"decision_id authorizes {final_decision.decision_type.value}, not {expected_decision.value}."
            )
        if final_decision.used:
            raise ToolAuthorizationError("decision_id has already been used.")
        if datetime.now(UTC) - final_decision.created_at > DECISION_TTL:
            raise ToolAuthorizationError("decision_id has expired.")

        updated = self.data_store.mark_final_decision_used(decision_id)
        response = {
            "decision_id": updated.decision_id,
            "action": tool_name,
            "status": "completed",
            "decision_type": updated.decision_type.value,
            "used_at": updated.used_at.isoformat() if updated.used_at else None,
            "reason_codes": json.loads(updated.reason_codes_json),
        }
        self._log_tool_call(
            session_id=session_id,
            tool_name=tool_name,
            tool_input={"decision_id": decision_id},
            tool_output=response,
        )
        return response

    def _decision_record_payload(
        self,
        *,
        decision_id: str,
        session_id: str,
        decision_type: DecisionType,
        request_fingerprint: str,
        reason_codes: list[str],
    ):
        from backend.schemas import CreateRuntimeFinalDecisionInput

        return CreateRuntimeFinalDecisionInput(
            decision_id=decision_id,
            session_id=session_id,
            decision_type=decision_type,
            request_fingerprint=request_fingerprint,
            reason_codes=reason_codes,
        )

    def _build_request_fingerprint(self, request: RefundRequest) -> str:
        fingerprint_source = json.dumps(
            {
                "session_id": request.session_id,
                "customer_email": request.customer_email.lower(),
                "order_id": request.order_id,
                "item_id": request.item_id,
                "issue_type": request.issue_type,
                "requested_amount": request.requested_amount,
                "claim_text": request.claim_text,
                "claim_inconsistent": request.claim_inconsistent,
                "evidence_provided": request.evidence_provided,
            },
            sort_keys=True,
        )
        return hashlib.sha256(fingerprint_source.encode("utf-8")).hexdigest()

    def _log_tool_call(
        self,
        *,
        session_id: str,
        tool_name: str,
        tool_input: dict[str, object],
        tool_output: dict[str, object],
    ) -> None:
        if self.trace_service is None:
            return
        self.trace_service.log_tool_call(
            tool_call_id=f"tool-{uuid4()}",
            session_id=session_id,
            tool_name=tool_name,
            tool_input=tool_input,
            tool_output=tool_output,
            status="completed",
        )
