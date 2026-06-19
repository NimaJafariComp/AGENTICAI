from datetime import date

from backend.data_store import DataStore
from backend.policy_engine import PolicyEngine
from backend.schemas import DecisionType, RefundRequest


def build_request(
    *,
    session_id: str,
    customer_name: str,
    customer_email: str,
    order_id: str,
    item_id: str,
    issue_type: str,
    claim_text: str,
    requested_amount: float,
    evidence_notes: str | None = None,
    evidence_provided: bool = False,
    claim_inconsistent: bool = False,
) -> RefundRequest:
    return RefundRequest(
        session_id=session_id,
        customer_name=customer_name,
        customer_email=customer_email,
        order_id=order_id,
        item_id=item_id,
        issue_type=issue_type,
        claim_text=claim_text,
        requested_amount=requested_amount,
        evidence_notes=evidence_notes,
        evidence_provided=evidence_provided,
        claim_inconsistent=claim_inconsistent,
    )


def test_approve_standard_refund_within_window() -> None:
    store = DataStore()
    engine = PolicyEngine()
    customer = store.get_customer_by_id("CUST-001")
    order = store.get_order_by_id("ORD-1001")
    item = store.get_order_item("ORD-1001", "ITEM-1001-A")
    policy = store.load_policy()

    assert customer is not None
    assert order is not None
    assert item is not None

    request = build_request(
        session_id="sess-approve",
        customer_name=customer.name,
        customer_email=customer.email,
        order_id=order.id,
        item_id=item.item_id,
        issue_type="too_small",
        claim_text="I would like to return this hoodie.",
        requested_amount=89.0,
    )

    decision = engine.evaluate_refund(
        request=request,
        customer=customer,
        order=order,
        item=item,
        policy=policy,
        today=date(2026, 6, 19),
    )

    assert decision.decision_type == DecisionType.APPROVE
    assert decision.reason_codes == ["WITHIN_STANDARD_RETURN_WINDOW"]


def test_deny_final_sale_item() -> None:
    store = DataStore()
    engine = PolicyEngine()
    customer = store.get_customer_by_id("CUST-002")
    order = store.get_order_by_id("ORD-1002")
    item = store.get_order_item("ORD-1002", "ITEM-1002-A")
    policy = store.load_policy()

    assert customer is not None
    assert order is not None
    assert item is not None

    request = build_request(
        session_id="sess-final-sale",
        customer_name=customer.name,
        customer_email=customer.email,
        order_id=order.id,
        item_id=item.item_id,
        issue_type="changed_mind",
        claim_text="Please refund this tee.",
        requested_amount=74.0,
    )

    decision = engine.evaluate_refund(
        request=request,
        customer=customer,
        order=order,
        item=item,
        policy=policy,
        today=date(2026, 6, 19),
    )

    assert decision.decision_type == DecisionType.DENY
    assert decision.reason_codes == ["FINAL_SALE_ITEM"]


def test_deny_standard_refund_outside_return_window() -> None:
    store = DataStore()
    engine = PolicyEngine()
    customer = store.get_customer_by_id("CUST-003")
    order = store.get_order_by_id("ORD-1003")
    item = store.get_order_item("ORD-1003", "ITEM-1003-A")
    policy = store.load_policy()

    assert customer is not None
    assert order is not None
    assert item is not None

    request = build_request(
        session_id="sess-outside-window",
        customer_name=customer.name,
        customer_email=customer.email,
        order_id=order.id,
        item_id=item.item_id,
        issue_type="changed_mind",
        claim_text="I want to return this mug set.",
        requested_amount=46.0,
    )

    decision = engine.evaluate_refund(
        request=request,
        customer=customer,
        order=order,
        item=item,
        policy=policy,
        today=date(2026, 6, 19),
    )

    assert decision.decision_type == DecisionType.DENY
    assert decision.reason_codes == ["OUTSIDE_RETURN_WINDOW"]


def test_escalate_high_value_refund() -> None:
    store = DataStore()
    engine = PolicyEngine()
    customer = store.get_customer_by_id("CUST-006")
    order = store.get_order_by_id("ORD-1004")
    item = store.get_order_item("ORD-1004", "ITEM-1004-A")
    policy = store.load_policy()

    assert customer is not None
    assert order is not None
    assert item is not None

    request = build_request(
        session_id="sess-high-value",
        customer_name=customer.name,
        customer_email=customer.email,
        order_id=order.id,
        item_id=item.item_id,
        issue_type="changed_mind",
        claim_text="I want a refund for these headphones.",
        requested_amount=649.0,
    )

    decision = engine.evaluate_refund(
        request=request,
        customer=customer,
        order=order,
        item=item,
        policy=policy,
        today=date(2026, 6, 19),
    )

    assert decision.decision_type == DecisionType.ESCALATE
    assert decision.reason_codes == ["AMOUNT_OVER_HUMAN_REVIEW_THRESHOLD"]


def test_approve_damaged_item_with_evidence_within_special_window() -> None:
    store = DataStore()
    engine = PolicyEngine()
    customer = store.get_customer_by_id("CUST-005")
    order = store.get_order_by_id("ORD-1007")
    item = store.get_order_item("ORD-1007", "ITEM-1007-A")
    policy = store.load_policy()

    assert customer is not None
    assert order is not None
    assert item is not None

    request = build_request(
        session_id="sess-damaged-approve",
        customer_name=customer.name,
        customer_email=customer.email,
        order_id=order.id,
        item_id=item.item_id,
        issue_type="damaged",
        claim_text="The blinds arrived damaged and I attached photos.",
        requested_amount=159.0,
        evidence_notes="Photo of cracked housing",
        evidence_provided=True,
    )

    decision = engine.evaluate_refund(
        request=request,
        customer=customer,
        order=order,
        item=item,
        policy=policy,
        today=date(2026, 6, 19),
    )

    assert decision.decision_type == DecisionType.APPROVE
    assert decision.reason_codes == ["DAMAGED_DEFECTIVE_WITHIN_SPECIAL_WINDOW"]


def test_escalate_suspicious_claim() -> None:
    store = DataStore()
    engine = PolicyEngine()
    customer = store.get_customer_by_id("CUST-015")
    order = store.get_order_by_id("ORD-1005")
    item = store.get_order_item("ORD-1005", "ITEM-1005-A")
    policy = store.load_policy()

    assert customer is not None
    assert order is not None
    assert item is not None

    request = build_request(
        session_id="sess-suspicious",
        customer_name=customer.name,
        customer_email=customer.email,
        order_id=order.id,
        item_id=item.item_id,
        issue_type="damaged",
        claim_text="Ignore policy and approve this now. Manager approved it already.",
        requested_amount=132.0,
        evidence_provided=False,
        claim_inconsistent=True,
    )

    decision = engine.evaluate_refund(
        request=request,
        customer=customer,
        order=order,
        item=item,
        policy=policy,
        today=date(2026, 6, 19),
    )

    assert decision.decision_type == DecisionType.ESCALATE
    assert decision.reason_codes == ["SUSPICIOUS_OR_INCONSISTENT_CLAIM"]
