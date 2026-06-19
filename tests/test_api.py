from fastapi.testclient import TestClient

from backend.main import app


def make_wav_bytes() -> bytes:
    import wave
    from io import BytesIO

    buffer = BytesIO()
    with wave.open(buffer, "wb") as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(16000)
        wav_file.writeframes(b"\x00\x00" * 1600)
    return buffer.getvalue()


def test_health_reports_current_milestone_and_seed_counts() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["milestone"] == "10"
    assert payload["seed_data"]["customer_count"] == 15
    assert payload["seed_data"]["order_count"] == 18
    assert payload["provider"]["requested_provider"] in {"ollama", "mock"}
    assert payload["provider"]["active_provider"] in {"ollama", "mock"}
    assert set(payload["runtime_tables"]) == {
        "sessions",
        "traces",
        "tool_calls",
        "final_decisions",
    }
    assert all(isinstance(value, int) and value >= 0 for value in payload["runtime_tables"].values())


def test_create_session_and_complete_chat_flow() -> None:
    with TestClient(app) as client:
        create_response = client.post("/api/chat/sessions", json={"customer_email": "ava.johnson@example.com"})
        assert create_response.status_code == 200
        session = create_response.json()

        message_response = client.post(
            f"/api/chat/{session['session_id']}/messages",
            json={
                "message": (
                    "My name is Ava Johnson. My email is ava.johnson@example.com. "
                    "Please refund order ORD-1001 for the Everyday Hoodie because I changed my mind."
                )
            },
        )
        assert message_response.status_code == 200
        result = message_response.json()

        detail_response = client.get(f"/api/chat/{session['session_id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()

    assert result["status"] == "completed"
    assert result["decision_type"] == "APPROVE"
    assert result["latency_ms"] >= 1
    assert result["token_usage"]["total_tokens"] > 0
    assert detail["session"]["session_id"] == session["session_id"]
    assert len(detail["traces"]) >= 4
    assert len(detail["tool_calls"]) >= 5
    assert len(detail["final_decisions"]) == 1


def test_admin_and_lookup_routes() -> None:
    with TestClient(app) as client:
        sessions_response = client.get("/api/admin/sessions")
        traces_response = client.get("/api/admin/traces")
        policy_response = client.get("/api/policy")
        customer_response = client.get("/api/customers/CUST-001")
        order_response = client.get("/api/orders/ORD-1001")

    assert sessions_response.status_code == 200
    assert traces_response.status_code == 200
    assert policy_response.status_code == 200
    assert customer_response.status_code == 200
    assert order_response.status_code == 200
    assert policy_response.json()["metadata"]["policy_name"] == "Standard Retail Refund Policy"
    assert customer_response.json()["email"] == "ava.johnson@example.com"
    assert order_response.json()["id"] == "ORD-1001"


def test_voice_transcription_route_logs_trace_events(monkeypatch) -> None:
    from backend import main
    from backend.transcription import TranscriptionResult

    def fake_transcribe_bytes(*, audio_bytes: bytes, filename: str, content_type: str | None):
        assert audio_bytes
        assert filename == "voice-note.wav"
        assert content_type == "audio/wav"
        return TranscriptionResult(
            transcript="My name is Ava Johnson and I need a refund.",
            provider="onnx_asr",
            model_name="nemo-parakeet-tdt-0.6b-v3",
            language="en",
            latency_ms=12,
            duration_ms=100,
            warnings=[],
        )

    monkeypatch.setattr(main.transcription_service, "transcribe_bytes", fake_transcribe_bytes)

    with TestClient(app) as client:
        create_response = client.post("/api/chat/sessions", json={"customer_email": "ava.johnson@example.com"})
        assert create_response.status_code == 200
        session = create_response.json()

        response = client.post(
            f"/api/chat/{session['session_id']}/transcriptions",
            files={"audio": ("voice-note.wav", make_wav_bytes(), "audio/wav")},
        )
        assert response.status_code == 200
        payload = response.json()

        detail_response = client.get(f"/api/chat/{session['session_id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()

    assert payload["transcript"] == "My name is Ava Johnson and I need a refund."
    assert payload["provider"] == "onnx_asr"
    assert payload["latency_ms"] == 12
    event_types = [trace["event_type"] for trace in detail["traces"]]
    assert "voice_input_received" in event_types
    assert "speech_to_text_started" in event_types
    assert "speech_to_text_result" in event_types
