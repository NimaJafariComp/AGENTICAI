from datetime import date
from uuid import uuid4

import pytest

from backend.data_store import DataStore
from backend.policy_engine import PolicyEngine
from backend.schemas import DecisionType, RefundRequest
from backend.tools import RefundTools, ToolAuthorizationError
from backend.trace import TraceService


def make_tools(tmp_path) -> RefundTools:
    runtime_db_path = tmp_path / "runtime.db"
    store = DataStore(runtime_db_path=runtime_db_path)
    store.init_runtime_db()
    trace_service = TraceService(store)
    return RefundTools(store, PolicyEngine(), trace_service)


def build_request(
    *,
    session_id: str,
    customer_email: str,
    customer_name: str,
    order_id: str,
    item_id: str,
    issue_type: str,
    claim_text: str,
    requested_amount: float,
    evidence_provided: bool = False,
    claim_inconsistent: bool = False,
) -> RefundRequest:
    return RefundRequest(
        session_id=session_id,
        customer_email=customer_email,
        customer_name=customer_name,
        order_id=order_id,
        item_id=item_id,
        issue_type=issue_type,
        claim_text=claim_text,
        requested_amount=requested_amount,
        evidence_provided=evidence_provided,
        claim_inconsistent=claim_inconsistent,
    )


def test_can_only_approve_with_matching_decision_id(tmp_path) -> None:
    tools = make_tools(tmp_path)
    session_id = f"session-{uuid4()}"
    request = build_request(
        session_id=session_id,
        customer_email="ava.johnson@example.com",
        customer_name="Ava Johnson",
        order_id="ORD-1001",
        item_id="ITEM-1001-A",
        issue_type="too_small",
        claim_text="I want to return this hoodie.",
        requested_amount=89.0,
    )

    eligibility = tools.check_refund_eligibility(request=request, today=date(2026, 6, 19))
    result = tools.approve_refund(session_id=session_id, decision_id=eligibility["decision_id"])

    assert eligibility["decision_type"] == DecisionType.APPROVE.value
    assert result["action"] == "approve_refund"
    assert result["decision_type"] == DecisionType.APPROVE.value


def test_cannot_approve_escalation_decision(tmp_path) -> None:
    tools = make_tools(tmp_path)
    session_id = f"session-{uuid4()}"
    request = build_request(
        session_id=session_id,
        customer_email="ethan.brooks@example.com",
        customer_name="Ethan Brooks",
        order_id="ORD-1004",
        item_id="ITEM-1004-A",
        issue_type="changed_mind",
        claim_text="Please refund these headphones.",
        requested_amount=649.0,
    )

    eligibility = tools.check_refund_eligibility(request=request, today=date(2026, 6, 19))

    assert eligibility["decision_type"] == DecisionType.ESCALATE.value
    with pytest.raises(ToolAuthorizationError, match="authorizes ESCALATE"):
        tools.approve_refund(session_id=session_id, decision_id=eligibility["decision_id"])


def test_cannot_reuse_decision_id(tmp_path) -> None:
    tools = make_tools(tmp_path)
    session_id = f"session-{uuid4()}"
    request = build_request(
        session_id=session_id,
        customer_email="noah.martinez@example.com",
        customer_name="Noah Martinez",
        order_id="ORD-1002",
        item_id="ITEM-1002-A",
        issue_type="changed_mind",
        claim_text="Refund this final sale tee.",
        requested_amount=74.0,
    )

    eligibility = tools.check_refund_eligibility(request=request, today=date(2026, 6, 19))
    first = tools.deny_refund(session_id=session_id, decision_id=eligibility["decision_id"])

    assert first["action"] == "deny_refund"
    with pytest.raises(ToolAuthorizationError, match="already been used"):
        tools.deny_refund(session_id=session_id, decision_id=eligibility["decision_id"])


def test_missing_decision_id_fails(tmp_path) -> None:
    tools = make_tools(tmp_path)

    with pytest.raises(ToolAuthorizationError, match="Missing or invalid decision_id"):
        tools.escalate_refund(session_id="session-missing", decision_id="decision-does-not-exist")
