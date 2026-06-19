from fastapi.testclient import TestClient

from backend.main import app


def test_health_reports_current_milestone_and_seed_counts() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["milestone"] == "5"
    assert payload["seed_data"]["customer_count"] == 15
    assert payload["seed_data"]["order_count"] == 18
    assert set(payload["runtime_tables"]) == {
        "sessions",
        "traces",
        "tool_calls",
        "final_decisions",
    }
    assert all(isinstance(value, int) and value >= 0 for value in payload["runtime_tables"].values())
