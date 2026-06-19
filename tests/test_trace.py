import json
from uuid import uuid4

from backend.data_store import DataStore
from backend.schemas import DecisionType
from backend.trace import TraceService


def test_trace_service_persists_session_event_tool_call_and_final_decision(tmp_path) -> None:
    runtime_db_path = tmp_path / "runtime.db"
    store = DataStore(runtime_db_path=runtime_db_path)
    store.init_runtime_db()
    trace_service = TraceService(store)

    session_id = f"session-{uuid4()}"
    trace_id = f"trace-{uuid4()}"
    tool_call_id = f"tool-{uuid4()}"
    decision_id = f"decision-{uuid4()}"

    session = trace_service.start_session(session_id=session_id, customer_email="demo@example.com")
    event = trace_service.log_event(
        trace_id=trace_id,
        session_id=session_id,
        event_type="user_message",
        payload={"message": "I need a refund."},
    )
    tool_call = trace_service.log_tool_call(
        tool_call_id=tool_call_id,
        session_id=session_id,
        tool_name="lookup_order",
        tool_input={"order_id": "ORD-1001"},
        tool_output={"found": True},
        status="completed",
    )
    final_decision = trace_service.log_final_decision(
        decision_id=decision_id,
        session_id=session_id,
        decision_type=DecisionType.APPROVE,
        request_fingerprint="req-123",
        reason_codes=["WITHIN_STANDARD_RETURN_WINDOW"],
    )

    traces = store.list_traces(session_id=session_id)
    tool_calls = store.list_tool_calls(session_id=session_id)
    decisions = store.list_final_decisions(session_id=session_id)
    counts = store.runtime_table_counts()

    assert session.session_id == session_id
    assert session.customer_email == "demo@example.com"
    assert event.event_type == "user_message"
    assert json.loads(event.payload_json) == {"message": "I need a refund."}
    assert tool_call.tool_name == "lookup_order"
    assert json.loads(tool_call.tool_input_json) == {"order_id": "ORD-1001"}
    assert json.loads(tool_call.tool_output_json) == {"found": True}
    assert final_decision.decision_type == DecisionType.APPROVE
    assert json.loads(final_decision.reason_codes_json) == ["WITHIN_STANDARD_RETURN_WINDOW"]
    assert len(traces) == 1
    assert len(tool_calls) == 1
    assert len(decisions) == 1
    assert counts == {
        "sessions": 1,
        "traces": 1,
        "tool_calls": 1,
        "final_decisions": 1,
    }
