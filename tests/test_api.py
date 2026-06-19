from fastapi.testclient import TestClient

from backend.main import app


def test_health_reports_current_milestone_and_seed_counts() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["milestone"] == "9"
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
            json={"message": "My email is ava.johnson@example.com and order ORD-1001 should be refunded."},
        )
        assert message_response.status_code == 200
        result = message_response.json()

        detail_response = client.get(f"/api/chat/{session['session_id']}")
        assert detail_response.status_code == 200
        detail = detail_response.json()

    assert result["status"] == "completed"
    assert result["decision_type"] == "APPROVE"
    assert detail["session"]["session_id"] == session["session_id"]
    assert len(detail["traces"]) >= 2
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
