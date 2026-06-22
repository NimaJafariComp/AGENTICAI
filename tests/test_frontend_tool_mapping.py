from __future__ import annotations

from backend.tools import REFUND_TOOL_NAMES
from frontend.shared import TOOL_LABELS, extract_case_intel


def test_frontend_labels_cover_all_backend_refund_tools() -> None:
    missing = [tool_name for tool_name in REFUND_TOOL_NAMES if tool_name not in TOOL_LABELS]

    assert missing == []


def test_case_intel_extracts_customer_order_and_tools_from_backend_tool_names() -> None:
    detail = {
        "tool_calls": [
            {
                "tool_name": "lookup_customer",
                "status": "completed",
                "tool_output": {"customer_id": "CUST-001", "email": "ava.johnson@example.com"},
            },
            {
                "tool_name": "lookup_order",
                "status": "completed",
                "tool_output": {"order_id": "ORD-1001", "customer_id": "CUST-001"},
            },
            {
                "tool_name": "get_refund_policy",
                "status": "completed",
                "tool_output": {
                    "policy_name": "Standard Retail Refund Policy",
                    "policy_version": "2026.06",
                },
            },
            {
                "tool_name": "check_refund_eligibility",
                "status": "completed",
                "tool_output": {
                    "decision_type": "APPROVE",
                    "reason_codes": ["WITHIN_STANDARD_RETURN_WINDOW"],
                },
            },
            {
                "tool_name": "approve_refund",
                "status": "completed",
                "tool_output": {"action": "approve_refund"},
            },
        ],
        "final_decisions": [
            {
                "decision_type": "APPROVE",
                "reason_codes": ["WITHIN_STANDARD_RETURN_WINDOW"],
            }
        ],
    }

    intel = extract_case_intel(detail)

    assert intel["customer"] == {"customer_id": "CUST-001", "email": "ava.johnson@example.com"}
    assert intel["order"] == {"order_id": "ORD-1001", "customer_id": "CUST-001"}
    assert intel["reason_codes"] == ["WITHIN_STANDARD_RETURN_WINDOW"]
    assert [tool["name"] for tool in intel["tool_progress"]] == [
        "lookup_customer",
        "lookup_order",
        "get_refund_policy",
        "check_refund_eligibility",
        "approve_refund",
    ]
    assert all(tool["status"] == "succeeded" for tool in intel["tool_progress"])
