from fastapi.testclient import TestClient

from backend.main import app


def test_health_reports_milestone_2_and_seed_counts() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()

    assert payload["status"] == "ok"
    assert payload["milestone"] == "2"
    assert payload["seed_data"]["customer_count"] == 15
    assert payload["seed_data"]["order_count"] == 18
    assert payload["runtime_tables"] == {
        "sessions": 0,
        "traces": 0,
        "tool_calls": 0,
        "final_decisions": 0,
    }
