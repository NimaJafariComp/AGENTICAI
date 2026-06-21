import json
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, UploadFile

from backend.agent import RefundAgent
from backend.data_store import DataStore
from backend.llm_client import LLMClient
from backend.policy_engine import PolicyEngine
from backend.schemas import (
    ChatMessageRequest,
    ChatSessionResponse,
    CreateChatSessionRequest,
    FinalDecisionResponse,
    SessionDetailResponse,
    ToolCallResponse,
    TraceResponse,
    TranscriptionResponse,
)
from backend.tools import RefundTools
from backend.trace import TraceService
from backend.transcription import TranscriptionError, TranscriptionService

load_dotenv(Path(__file__).resolve().parents[1] / ".env")

data_store = DataStore()
trace_service = TraceService(data_store)
llm_client = LLMClient.from_env(trace_service=trace_service)
refund_tools = RefundTools(data_store, PolicyEngine(), trace_service)
refund_agent = RefundAgent(llm_client, refund_tools, trace_service)
transcription_service = TranscriptionService()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    data_store.init_runtime_db()
    yield


app = FastAPI(title="AgenticAI Backend", version="0.1.0", lifespan=lifespan)


@app.get("/health")
def health() -> dict[str, object]:
    summary = data_store.summary()
    return {
        "status": "ok",
        "milestone": "10",
        "seed_data": summary.model_dump(),
        "runtime_tables": data_store.runtime_table_counts(),
        "provider": llm_client.provider_info(),
    }


@app.post("/api/chat/sessions", response_model=ChatSessionResponse)
def create_chat_session(payload: CreateChatSessionRequest) -> ChatSessionResponse:
    session = trace_service.start_session(
        session_id=f"session-{uuid4()}",
        customer_email=payload.customer_email,
    )
    return _chat_session_response(session)


@app.post("/api/chat/{session_id}/messages")
def post_chat_message(session_id: str, payload: ChatMessageRequest):
    try:
        result = refund_agent.process_user_message(session_id=session_id, message=payload.message)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result.model_dump()


@app.post("/api/chat/{session_id}/transcriptions", response_model=TranscriptionResponse)
async def create_transcription(
    session_id: str,
    audio: UploadFile = File(...),
) -> TranscriptionResponse:
    try:
        data_store.get_session(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    audio_bytes = await audio.read()
    trace_service.log_event(
        trace_id=f"trace-{uuid4()}",
        session_id=session_id,
        event_type="voice_input_received",
        payload={
            "filename": audio.filename or "voice-note.wav",
            "content_type": audio.content_type,
            "size_bytes": len(audio_bytes),
        },
    )
    trace_service.log_event(
        trace_id=f"trace-{uuid4()}",
        session_id=session_id,
        event_type="speech_to_text_started",
        payload={
            "provider": transcription_service.provider,
            "model_name": transcription_service.model_name,
            "language": transcription_service.language,
        },
    )

    try:
        result = transcription_service.transcribe_bytes(
            audio_bytes=audio_bytes,
            filename=audio.filename or "voice-note.wav",
            content_type=audio.content_type,
        )
    except TranscriptionError as exc:
        trace_service.log_event(
            trace_id=f"trace-{uuid4()}",
            session_id=session_id,
            event_type="speech_to_text_failed",
            payload={
                "provider": transcription_service.provider,
                "model_name": transcription_service.model_name,
                "filename": audio.filename or "voice-note.wav",
                "content_type": audio.content_type,
                "error": str(exc),
            },
        )
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    trace_service.log_event(
        trace_id=f"trace-{uuid4()}",
        session_id=session_id,
        event_type="speech_to_text_result",
        payload={
            "provider": result.provider,
            "model_name": result.model_name,
            "language": result.language,
            "filename": audio.filename or "voice-note.wav",
            "content_type": audio.content_type,
            "size_bytes": len(audio_bytes),
            "transcript": result.transcript,
            "duration_ms": result.duration_ms,
            "warnings": result.warnings,
        },
        latency_ms=result.latency_ms,
    )
    return TranscriptionResponse(
        transcript=result.transcript,
        provider=result.provider,
        model_name=result.model_name,
        language=result.language,
        latency_ms=result.latency_ms,
        duration_ms=result.duration_ms,
        warnings=result.warnings,
    )


@app.get("/api/chat/{session_id}", response_model=SessionDetailResponse)
def get_chat_session(session_id: str) -> SessionDetailResponse:
    return _build_session_detail(session_id)


@app.get("/api/admin/traces", response_model=list[TraceResponse])
def list_admin_traces() -> list[TraceResponse]:
    return [_trace_response(trace) for trace in data_store.list_traces()]


@app.get("/api/admin/traces/{trace_id}", response_model=TraceResponse)
def get_admin_trace(trace_id: str) -> TraceResponse:
    try:
        trace = data_store.get_trace(trace_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _trace_response(trace)


@app.get("/api/admin/sessions", response_model=list[ChatSessionResponse])
def list_admin_sessions() -> list[ChatSessionResponse]:
    return [_chat_session_response(session) for session in data_store.list_sessions()]


@app.get("/api/policy")
def get_policy() -> dict[str, object]:
    policy = data_store.load_policy()
    return {
        "metadata": policy.metadata.model_dump(),
        "markdown_body": policy.markdown_body,
    }


@app.get("/api/customers/{customer_id}")
def get_customer(customer_id: str) -> dict[str, object]:
    customer = data_store.get_customer_by_id(customer_id)
    if customer is None:
        raise HTTPException(status_code=404, detail=f"Customer not found: {customer_id}")
    return customer.model_dump()


@app.get("/api/orders/{order_id}")
def get_order(order_id: str) -> dict[str, object]:
    order = data_store.get_order_by_id(order_id)
    if order is None:
        raise HTTPException(status_code=404, detail=f"Order not found: {order_id}")
    return order.model_dump()


def _build_session_detail(session_id: str) -> SessionDetailResponse:
    try:
        session = data_store.get_session(session_id)
    except Exception as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    traces = [_trace_response(trace) for trace in data_store.list_traces(session_id=session_id)]
    tool_calls = [_tool_call_response(call) for call in data_store.list_tool_calls(session_id=session_id)]
    final_decisions = [
        _final_decision_response(decision) for decision in data_store.list_final_decisions(session_id=session_id)
    ]
    return SessionDetailResponse(
        session=_chat_session_response(session),
        traces=traces,
        tool_calls=tool_calls,
        final_decisions=final_decisions,
    )


def _chat_session_response(session) -> ChatSessionResponse:
    return ChatSessionResponse(
        session_id=session.session_id,
        customer_email=session.customer_email,
        created_at=session.created_at,
        updated_at=session.updated_at,
    )


def _trace_response(trace) -> TraceResponse:
    return TraceResponse(
        trace_id=trace.trace_id,
        session_id=trace.session_id,
        event_type=trace.event_type,
        payload=json.loads(trace.payload_json),
        latency_ms=trace.latency_ms,
        token_usage=json.loads(trace.token_usage_json) if trace.token_usage_json else None,
        estimated_cost_usd=trace.estimated_cost_usd,
        created_at=trace.created_at,
    )


def _tool_call_response(call) -> ToolCallResponse:
    return ToolCallResponse(
        tool_call_id=call.tool_call_id,
        session_id=call.session_id,
        tool_name=call.tool_name,
        tool_input=json.loads(call.tool_input_json),
        tool_output=json.loads(call.tool_output_json) if call.tool_output_json else None,
        status=call.status,
        latency_ms=call.latency_ms,
        retry_group=call.retry_group,
        attempt_number=call.attempt_number,
        error_message=call.error_message,
        created_at=call.created_at,
    )


def _final_decision_response(decision) -> FinalDecisionResponse:
    return FinalDecisionResponse(
        decision_id=decision.decision_id,
        session_id=decision.session_id,
        decision_type=decision.decision_type.value,
        used=decision.used,
        request_fingerprint=decision.request_fingerprint,
        reason_codes=json.loads(decision.reason_codes_json),
        created_at=decision.created_at,
        used_at=decision.used_at,
    )
