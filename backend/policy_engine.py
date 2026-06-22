from __future__ import annotations

from datetime import date

from backend.schemas import (
    Customer,
    DecisionType,
    Order,
    OrderItem,
    PolicyDecision,
    RefundPolicyDocument,
    RefundRequest,
)


class PolicyEngineError(RuntimeError):
    """Raised when refund policy evaluation cannot proceed safely."""


class PolicyEngine:
    def evaluate_refund(
        self,
        *,
        request: RefundRequest,
        customer: Customer,
        order: Order,
        item: OrderItem,
        policy: RefundPolicyDocument,
        today: date,
    ) -> PolicyDecision:
        self._validate_request_matches_order(request=request, customer=customer, order=order, item=item)

        metadata = policy.metadata
        days_since_delivery = (today - item.delivered_at).days
        issue_type = request.issue_type.strip().lower()
        claim_text = request.claim_text.strip().lower()
        evidence_missing = metadata.damaged_defective.requires_review_if_evidence_missing and not request.evidence_provided
        suspicious_terms = ("ignore policy", "override", "manager approved", "prompt", "system prompt")

        is_damaged_flow = issue_type in {"damaged", "defective"} or "damaged" in claim_text or "defective" in claim_text

        if metadata.final_sale_non_refundable and item.final_sale:
            if is_damaged_flow:
                return PolicyDecision(
                    decision_type=DecisionType.ESCALATE,
                    reason_codes=["FINAL_SALE_ITEM_DAMAGE_CLAIM"],
                    policy_rules=["final_sale_non_refundable", "damaged_defective"],
                    explanation="The item is marked as final sale, but a damage or defect has been reported. A specialist will review this case.",
                    eligible=False,
                    requires_human_review=True,
                )
            return PolicyDecision(
                decision_type=DecisionType.DENY,
                reason_codes=["FINAL_SALE_ITEM"],
                policy_rules=["final_sale_non_refundable"],
                explanation="The item is marked as final sale and is not eligible for a return or refund.",
                eligible=False,
                requires_human_review=False,
            )

        if (
            metadata.suspicious_claim_escalation.enabled
            and (
                request.claim_inconsistent
                or customer.risk_score >= metadata.suspicious_claim_escalation.risk_score_threshold
                or any(term in claim_text for term in suspicious_terms)
            )
        ):
            return PolicyDecision(
                decision_type=DecisionType.ESCALATE,
                reason_codes=["SUSPICIOUS_OR_INCONSISTENT_CLAIM"],
                policy_rules=["suspicious_claim_escalation"],
                explanation="This case has been referred to a specialist for further review.",
                eligible=False,
                requires_human_review=True,
            )

        if request.requested_amount > metadata.human_escalation_amount:
            return PolicyDecision(
                decision_type=DecisionType.ESCALATE,
                reason_codes=["AMOUNT_OVER_HUMAN_REVIEW_THRESHOLD"],
                policy_rules=["human_escalation_amount"],
                explanation="The refund amount is above the limit for automatic processing and needs specialist review.",
                eligible=False,
                requires_human_review=True,
            )

        if is_damaged_flow:
            if not metadata.damaged_defective.eligible:
                return PolicyDecision(
                    decision_type=DecisionType.DENY,
                    reason_codes=["DAMAGED_DEFECTIVE_NOT_ELIGIBLE"],
                    policy_rules=["damaged_defective.eligible"],
                    explanation="Damaged and defective items are not eligible for a refund under the current return policy.",
                    eligible=False,
                    requires_human_review=False,
                )

            if days_since_delivery > metadata.damaged_defective.special_window_days:
                return PolicyDecision(
                    decision_type=DecisionType.DENY,
                    reason_codes=["DAMAGED_DEFECTIVE_OUTSIDE_SPECIAL_WINDOW"],
                    policy_rules=["damaged_defective.special_window_days"],
                    explanation="The item was reported as damaged or defective, but the report was received after the eligible window has passed.",
                    eligible=False,
                    requires_human_review=False,
                )

            if evidence_missing:
                return PolicyDecision(
                    decision_type=DecisionType.ESCALATE,
                    reason_codes=["MISSING_DAMAGE_EVIDENCE"],
                    policy_rules=["damaged_defective.requires_review_if_evidence_missing"],
                    explanation="The item was reported as damaged or defective, but no supporting evidence was provided. A specialist will review this case.",
                    eligible=False,
                    requires_human_review=True,
                )

            return PolicyDecision(
                decision_type=DecisionType.APPROVE,
                reason_codes=["DAMAGED_DEFECTIVE_WITHIN_SPECIAL_WINDOW"],
                policy_rules=["damaged_defective.special_window_days"],
                explanation="The item was reported as damaged or defective within the eligible window.",
                eligible=True,
                requires_human_review=False,
            )

        if days_since_delivery > metadata.return_window_days:
            return PolicyDecision(
                decision_type=DecisionType.DENY,
                reason_codes=["OUTSIDE_RETURN_WINDOW"],
                policy_rules=["return_window_days"],
                explanation="Refund request falls outside the standard return window.",
                eligible=False,
                requires_human_review=False,
            )

        return PolicyDecision(
            decision_type=DecisionType.APPROVE,
            reason_codes=["WITHIN_STANDARD_RETURN_WINDOW"],
            policy_rules=["return_window_days"],
            explanation="The item is within the return window and is eligible for a refund.",
            eligible=True,
            requires_human_review=False,
        )

    def _validate_request_matches_order(
        self,
        *,
        request: RefundRequest,
        customer: Customer,
        order: Order,
        item: OrderItem,
    ) -> None:
        if order.customer_id != customer.id:
            raise PolicyEngineError("Order does not belong to customer.")
        if item not in order.items:
            raise PolicyEngineError("Item does not belong to order.")
        if request.order_id != order.id:
            raise PolicyEngineError("Request order_id does not match supplied order.")
        if request.item_id != item.item_id:
            raise PolicyEngineError("Request item_id does not match supplied item.")
        normalized_email = request.customer_email.strip().lower()
        if normalized_email != customer.email.lower():
            raise PolicyEngineError("Request customer_email does not match supplied customer.")
