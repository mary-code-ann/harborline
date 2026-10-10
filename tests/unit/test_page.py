"""The chat page is served even when Postgres is down."""

from fastapi.testclient import TestClient

from app.main import app


def test_chat_page_loads() -> None:
    with TestClient(app) as client:
        response = client.get("/")
    assert response.status_code == 200
    assert "Harborline" in response.text
    assert "NW-1001" in response.text
    assert "fictional" in response.text
    assert "$1000" not in response.text


def test_health() -> None:
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_websocket_answers_when_a_call_starts() -> None:
    with TestClient(app) as client:
        with client.websocket_connect("/ws?account=NW-1001") as socket:
            message = socket.receive_json()
    assert message["text"]
    assert message["state"] in {"VERIFYING", "ENDED"}
