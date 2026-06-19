from __future__ import annotations

from backend.data_store import DataStore
from backend.schemas import (
    CreateRuntimeFinalDecisionInput,
    CreateRuntimeSessionInput,
    CreateRuntimeToolCallInput,
    CreateRuntimeTraceInput,
    RuntimeFinalDecision,
    RuntimeSession,
    RuntimeToolCall,
    RuntimeTrace,
)


class TraceService:
    def __init__(self, data_store: DataStore) -> None:
        self.data_store = data_store

    def start_session(
        self,
        session_id: str,
        customer_email: str | None = None,
        intake_state: dict[str, object] | None = None,
    ) -> RuntimeSession:
        return self.data_store.create_session(
            CreateRuntimeSessionInput(
                session_id=session_id,
                customer_email=customer_email,
                intake_state=intake_state,
            )
        )

    def log_event(
        self,
        trace_id: str,
        session_id: str,
        event_type: str,
        payload: object,
        latency_ms: int | None = None,
        token_usage: dict[str, object] | None = None,
        estimated_cost_usd: float | None = None,
    ) -> RuntimeTrace:
        return self.data_store.append_trace(
            CreateRuntimeTraceInput(
                trace_id=trace_id,
                session_id=session_id,
                event_type=event_type,
                payload=payload,
                latency_ms=latency_ms,
                token_usage=token_usage,
                estimated_cost_usd=estimated_cost_usd,
            )
        )

    def log_tool_call(
        self,
        tool_call_id: str,
        session_id: str,
        tool_name: str,
        tool_input: object,
        tool_output: object = None,
        status: str = "completed",
        latency_ms: int | None = None,
        retry_group: str | None = None,
        attempt_number: int = 1,
        error_message: str | None = None,
    ) -> RuntimeToolCall:
        return self.data_store.create_tool_call(
            CreateRuntimeToolCallInput(
                tool_call_id=tool_call_id,
                session_id=session_id,
                tool_name=tool_name,
                tool_input=tool_input,
                tool_output=tool_output,
                status=status,
                latency_ms=latency_ms,
                retry_group=retry_group,
                attempt_number=attempt_number,
                error_message=error_message,
            )
        )

    def log_final_decision(
        self,
        decision_id: str,
        session_id: str,
        decision_type: str,
        request_fingerprint: str,
        reason_codes: list[str],
    ) -> RuntimeFinalDecision:
        return self.data_store.create_final_decision(
            CreateRuntimeFinalDecisionInput(
                decision_id=decision_id,
                session_id=session_id,
                decision_type=decision_type,
                request_fingerprint=request_fingerprint,
                reason_codes=reason_codes,
            )
        )
