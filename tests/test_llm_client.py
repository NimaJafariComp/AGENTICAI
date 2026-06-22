import json

import httpx

from backend.data_store import DataStore
from backend.llm_client import LLMClient
from backend.providers.mock_provider import MockProvider
from backend.providers.ollama_provider import OllamaProvider
from backend.trace import TraceService


def test_ollama_provider_uses_native_chat_api() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat":
            payload = json.loads(request.content.decode("utf-8"))
            assert payload["model"] == "qwen2.5:0.5b"
            assert payload["stream"] is False
            return httpx.Response(200, json={"message": {"content": "Ollama reply"}})
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:0.5b"}]})
        return httpx.Response(404)

    provider = OllamaProvider(
        base_url="http://ollama.local",
        model="qwen2.5:0.5b",
        transport=httpx.MockTransport(handler),
    )

    assert provider.is_available() is True
    response = provider.chat(messages=[{"role": "user", "content": "hello"}])
    assert response.provider_name == "ollama"
    assert response.content == "Ollama reply"


def test_ollama_unavailable_when_model_not_pulled() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen2.5:0.5b"}]})
        return httpx.Response(404)

    provider = OllamaProvider(
        base_url="http://ollama.local",
        model="qwen3:0.6b",
        transport=httpx.MockTransport(handler),
    )

    assert provider.is_available() is False


def test_llm_client_uses_mock_provider_directly(monkeypatch) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "mock")

    client = LLMClient.from_env()
    info = client.provider_info()

    assert isinstance(client.selection.provider, MockProvider)
    assert info["requested_provider"] == "mock"
    assert info["active_provider"] == "mock"
    assert info["fallback_used"] is False


def test_llm_client_falls_back_to_mock_and_logs_trace(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://localhost:11434")
    monkeypatch.setenv("OLLAMA_MODEL", "qwen2.5:0.5b")

    monkeypatch.setattr(OllamaProvider, "is_available", lambda self: False)

    store = DataStore(runtime_db_path=tmp_path / "runtime.db")
    store.init_runtime_db()
    trace_service = TraceService(store)
    client = LLMClient.from_env(trace_service=trace_service)

    session_id = "session-provider-fallback"
    trace_service.start_session(session_id)
    reply = client.chat(
        messages=[{"role": "user", "content": "hello"}],
        session_id=session_id,
    )
    traces = store.list_traces(session_id=session_id)

    assert reply.provider_name == "mock"
    assert client.provider_info()["fallback_used"] is True
    assert len(traces) == 1
    assert traces[0].event_type == "provider_fallback"
    assert "Ollama unavailable" in traces[0].payload_json
