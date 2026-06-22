from __future__ import annotations

import json
from datetime import date
from uuid import uuid4

import pytest

from backend.agent import RefundAgent
from backend.data_store import DataStore
from backend.demo_scenarios import DEMO_SCENARIOS, DemoScenario
from backend.llm_client import LLMClient
from backend.policy_engine import PolicyEngine
from backend.tools import RefundTools
from backend.trace import TraceService


def make_agent(tmp_path) -> tuple[RefundAgent, DataStore]:
    store = DataStore(runtime_db_path=tmp_path / f"runtime-{uuid4()}.db")
    store.init_runtime_db()
    trace_service = TraceService(store)
    llm_client = LLMClient.from_env(trace_service=trace_service)
    tools = RefundTools(store, PolicyEngine(), trace_service)
    return RefundAgent(llm_client, tools, trace_service), store


@pytest.mark.parametrize("scenario", DEMO_SCENARIOS, ids=[scenario["key"] for scenario in DEMO_SCENARIOS])
def test_demo_scenario_reaches_declared_outcome(
    scenario: DemoScenario,
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")
    agent, store = make_agent(tmp_path)
    session_id = f"session-{uuid4()}"

    result = agent.process_user_message(
        session_id=session_id,
        message=scenario["message"],
        today=date(2026, 6, 19),
    )

    decisions = store.list_final_decisions(session_id=session_id)
    traces = store.list_traces(session_id=session_id)
    tool_calls = store.list_tool_calls(session_id=session_id)

    assert result.status == "completed"
    assert result.missing_fields == []
    assert result.decision_type == scenario["expected"]
    assert len(decisions) == 1
    assert decisions[0].decision_type.value == scenario["expected"]
    assert json.loads(decisions[0].reason_codes_json) == scenario["expected_reason_codes"]
    assert result.intake_state["item_id"]
    assert any(call.tool_name == "check_refund_eligibility" for call in tool_calls)

    failed_lookup_calls = [
        call for call in tool_calls if call.tool_name == "lookup_order" and call.status == "failed"
    ]
    retry_events = [trace for trace in traces if trace.event_type == "tool_retry"]

    if scenario["expect_retry"]:
        assert failed_lookup_calls
        assert retry_events
        assert any(call.tool_name == "lookup_order" and call.attempt_number == 2 for call in tool_calls)
    else:
        assert failed_lookup_calls == []
        assert retry_events == []
